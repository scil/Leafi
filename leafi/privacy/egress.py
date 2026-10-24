"""The one way out (ADR-0018 §2, M5 design D5–D9, D16): `prepare` at the call, a mediating transport at the wire.

`prepare(destination, purpose, Outgoing(...))` takes a request as fields, before any encoding. Text that came
from a person is a `Text` with its provenance; a plain string is the caller's own (`system`). It refuses what
the destination, the purpose or the source learners' settings do not allow, replaces every protected name for a
cloud destination (`leafi.privacy.pseudonym`; for a model-bound destination such as Ollama, "cloud" is decided per
model by `destinations.effective`, M7 design D1, and the body's model must be the one named to `prepare`), encodes the fields itself into the exact bytes to send, writes the
`egress_log` row (`sending`) and returns a `Prepared` holding an attempt token.

The token's id travels in the `x-leafi-token` header of the one request it was made for; the mediating
transport removes it before anything is hashed or sent, claims the token (it leaves the store at once, so a
second submission of any request finds nothing), checks that the outgoing request is the prepared one — for the
anthropic SDK, which serialises the body itself, the parsed body must equal the prepared value and the SDK's own
bytes are what is sent — and then, before each transmission, the retry included: the household policy
fingerprint, the source versions, the budget hook, and the reservation (`transmitted_attempts + 1`, committed
before any byte leaves). Each transmission resolves and connects under a `netguard` grant that lives until the
response stream is closed. Refusals are a synthetic 403 (`{"refused": reason}`); a text request is retried once
on a connect error or a 5xx; a redirect is never followed.

A learner's own words are also run through the name detector (`leafi.privacy.detector`) before they reach a
cloud destination.

M5b: nothing calls this yet (M5c moves every caller). Not here yet, each landing with its callers in M5c: the
synchronous transport and the `ops` download hops of D16 (doctor, the HF adapter), the WebSocket client (edge-tts
`mediated`).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlencode, urlsplit

import httpx2
import psutil

from leafi.core import netguard
from leafi.core.config import Settings
from leafi.core.provenance import PARENT_SOURCE, Provenance
from leafi.core.storage import Store, _FileLock, now_iso
from leafi.privacy import destinations as dests
from leafi.privacy import pseudonym, versions
from leafi.privacy import secret as keyfile
from leafi.privacy import settings as privacy_settings
from leafi.privacy.destinations import Destination
from leafi.privacy.pseudonym import Mapping

log = logging.getLogger("leafi.privacy.egress")

TOKEN_HEADER = "x-leafi-token"
DEFAULT_TTL_S = 30.0
DOWNLOAD_TTL_S = 120.0
READ_ALLOWANCE_S = 30.0  # a response stream's grant may outlive the token's expiry by this much (D2, D7)
RETRY_WAIT_S = 0.5
BUSY_TIMEOUT_MS = 150
CLOUD_TEXT_CLASSES = ("learner", "derived_from_learner")


class Refused(PermissionError):
    """`prepare` will not make this request; the reason names the rule."""


@dataclass(frozen=True)
class Text:
    """A string with the provenance of ADR-0018 §3: `learner`, `derived_from_learner`, `parent`, `page` or
    `system`, and the learners it came from."""

    value: str
    provenance: str = "system"
    sources: tuple[int, ...] = ()  # may hold PARENT_SOURCE (0): parent text went into this (M7 design D2)

    @property
    def prov(self) -> Provenance:
        return Provenance(self.provenance, self.sources)


@dataclass
class Outgoing:
    method: str = "POST"
    path: str = "/"  # may hold `{name}` placeholders filled from `path_fields`, each URL-quoted after filtering
    path_fields: dict[str, Text | str] = field(default_factory=dict)
    query: dict[str, Text | str] = field(default_factory=dict)
    json: Any = None  # may hold `Text` leaves
    form: dict[str, Text | str] | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Token:
    id: str
    destination: Destination
    purpose: str
    learner_id: int | None
    session_id: int | None
    attempt_id: int
    method: str
    url: str
    body: bytes
    body_value: Any  # the prepared JSON value, or None
    digest: str
    snapshot: versions.Snapshot | None
    fingerprint: str
    expires: float
    transmissions: int
    model: str | None = None   # the model `prepare` checked against the body (M7 design D1)
    locality: str = "cloud"    # `destinations.effective()` for that model
    budget: Budget | None = None  # the caller's ledger, asked before and charged after each reservation (M7 D7)
    reserved: int = 0          # transmissions reserved so far

    @property
    def study(self) -> bool:
        return self.purpose != dests.OPS


class Budget(Protocol):
    """A caller's allowance for one request (M7 design D7). `can_cover` is pure and runs inside the reservation
    transaction, so a refusal reserves nothing; `charge` runs once, after that transaction committed, before the
    transmission: what is charged is what was reserved (reservation accounting). `first` tells the first
    transmission from the mediator's one retry."""

    def can_cover(self, first: bool) -> bool: ...

    def charge(self, first: bool) -> None: ...


@dataclass
class Prepared:
    token_id: str
    method: str
    url: str
    body: bytes
    json: Any  # the prepared JSON value (Text replaced), for an SDK that builds the body itself
    headers: dict[str, str]
    mapping: Mapping
    attempt_id: int | None = None  # the `egress_log` row: a cancelled caller reads its transmissions there (M7 D5)

    def request(self) -> httpx2.Request:
        """The request for an httpx2 adapter: exactly the prepared bytes, the token header attached."""
        return httpx2.Request(self.method, self.url, content=self.body,
                              headers={**self.headers, TOKEN_HEADER: self.token_id})

    def reverse(self, text: str) -> str:
        return self.mapping.reverse(text)


class TokenStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, Token] = {}

    def add(self, tok: Token) -> list[Token]:
        """Store `tok`; returns the tokens that expired unclaimed (their rows become `failed`)."""
        now = time.monotonic()
        with self._lock:
            gone = [t for t in self._tokens.values() if t.expires <= now]
            for t in gone:
                del self._tokens[t.id]
            self._tokens[tok.id] = tok
        return gone

    def claim(self, token_id: str) -> Token | None:
        """Atomic: the first claim removes the token; any later one, for any request, finds nothing."""
        with self._lock:
            tok = self._tokens.pop(token_id, None)
        if tok is not None and tok.expires <= time.monotonic():
            return None
        return tok


# ---------------------------------------------------------------- encoding


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict:
    out: dict = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate JSON key {k!r}")
        out[k] = v
    return out


def _reject_constant(name: str):
    raise ValueError(f"non-finite number {name}")


def strict_parse(body: bytes) -> Any:
    """JSON as the transport accepts it: UTF-8, no duplicate keys, no NaN or infinities."""
    return json.loads(body.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)


def _digest(key: bytes, dest: Destination, method: str, url: str, body: bytes) -> str:
    u = urlsplit(url)
    head = json.dumps([dest.scheme, (u.hostname or "").lower(), u.port or dest.port, method.upper(), u.path,
                       u.query], separators=(",", ":")).encode()
    return hmac.new(key, b"egress:" + head + b"\n" + body, hashlib.sha256).hexdigest()


def owner() -> str:
    """This process as `pid:start` (`egress_log.owner`, `reading_sessions.owner`)."""
    return _owner()


def owner_alive(value: str | None) -> bool:
    return _owner_alive(value)


def _owner() -> str:
    pid = os.getpid()
    try:
        started = int(psutil.Process(pid).create_time())
    except psutil.Error:
        started = 0
    return f"{pid}:{started}"


def _owner_alive(owner: str | None) -> bool:
    if not owner or ":" not in owner:
        return False
    pid_s, started_s = owner.split(":", 1)
    try:
        p = psutil.Process(int(pid_s))
        return int(p.create_time()) == int(started_s)
    except (psutil.Error, ValueError):
        return False


def refused(reason: str, request: httpx2.Request | None = None) -> httpx2.Response:
    log.warning("egress refused: %s", reason)
    return httpx2.Response(403, json={"refused": reason}, request=request)


# ---------------------------------------------------------------- egress


class Egress:
    """One per process (built after `leafi.bootstrap`). `resolve` and `inner` are seams for tests: the real
    resolution and the transport that puts bytes on the socket."""

    def __init__(self, settings: Settings, *, registry: dict[str, Destination] | None = None,
                 env_file: Path | None = Path(".env"), budget: Callable[[Token], bool] | None = None,
                 inner: httpx2.AsyncBaseTransport | None = None, resolve=None) -> None:
        self.resolve = resolve or _resolve  # async (host, port, ttl) -> addresses; tests resolve to TEST-NET
        self.settings = settings
        self.db_path = Path(settings.db_path)
        self.registry = registry if registry is not None else dests.registry(settings)
        self.key = keyfile.load(settings.data_dir)
        self.watch = versions.PolicyWatch(self.key, env_file)
        self.budget = budget
        self.detector_state = "unloaded"  # unloaded | loading | ready | off | failed
        self._detector = None
        self._det_lock, self._det_done = threading.Lock(), threading.Event()
        self.tokens = TokenStore()
        self.owner = _owner()
        self._local = threading.local()
        Store(self.db_path).close()  # the file exists at the current schema (or NeedsMigration is raised)
        self._lock = _FileLock(self.db_path, exclusive=False)  # never beside a migration
        self._inner = inner
        self.recover()
        self.import_legacy_terms(env_file)
        self.prune_ops(getattr(settings, "privacy_ops_log_days", 30))

    def import_legacy_terms(self, env_file: Path | None) -> int:
        """A `REDACT_TERMS` still set in `.env` or the environment moves into `household_terms` (idempotent; M5
        design D12): its names stay protected after the key was retired. `leafi privacy terms import` then
        removes the line from `.env`."""
        from leafi.core.config import legacy_redact_terms
        from leafi.core.storage import import_legacy_terms

        terms = legacy_redact_terms(env_file) if env_file is not None else []
        if not terms:
            return 0
        c = self._conn()
        c.execute("BEGIN IMMEDIATE")
        try:
            n = import_legacy_terms(c, terms)
            c.execute("COMMIT")
        except BaseException:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise
        if n:
            log.warning("imported %d REDACT_TERMS term(s) into household_terms; remove the key from .env with "
                        "`python -m leafi privacy terms import`", n)
        return n

    def prune_ops(self, days: int) -> int:
        """`ops` attempts older than `PRIVACY_OPS_LOG_DAYS` are deleted (ADR-0018 §5); study attempts stay until
        their learner is forgotten."""
        import datetime as dt

        cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=max(1, int(days)))).isoformat(timespec="milliseconds")
        return self._conn().execute("DELETE FROM egress_log WHERE purpose='ops' AND created_at < ?",
                                    (cutoff,)).rowcount

    # ---- database (a connection per thread; the shared Store is not thread-safe, design U5)
    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(str(self.db_path), isolation_level=None)
            c.execute("PRAGMA foreign_keys = ON")
            c.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            self._local.conn = c
        return c

    def recover(self) -> int:
        """`sending` rows of a process that is gone become `unknown`, keeping their transmission counts (D8)."""
        c = self._conn()
        rows = c.execute("SELECT id, owner FROM egress_log WHERE status = 'sending'").fetchall()
        dead = [r[0] for r in rows if r[1] != self.owner and not _owner_alive(r[1])]
        for i in dead:
            c.execute("UPDATE egress_log SET status='unknown', updated_at=? WHERE id=? AND status='sending'",
                      (now_iso(), i))
        return len(dead)

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None
        self._lock.release()

    # ---- prepare
    def prepare(self, destination: str | Destination, purpose: str, out: Outgoing, *,
                learner_id: int | None = None, session_id: int | None = None,
                ttl_s: float | None = None, model: str | None = None,
                budget: Budget | None = None) -> Prepared:
        dest = destination if isinstance(destination, Destination) else self.registry.get(destination)
        if dest is None:
            raise Refused(f"no destination {destination!r}")
        if purpose not in dest.purposes:
            raise Refused(f"{dest.name} does not accept purpose {purpose!r}")
        if purpose == "media":
            raise Refused("media is refused until M9 (design D20)")
        if dest.model_bound and model is None:
            raise Refused(f"{dest.name}: a request there names the model it is for (M7 design D1)")
        if model is not None:  # the model checked is the one sent; the mediator then compares the whole body
            sent = out.json.get("model") if isinstance(out.json, dict) else None
            if sent != model:
                raise Refused(f"{dest.name}: the body names model {sent!r}, not {model!r}")
        locality = dests.effective(dest, model, self.settings)
        study = purpose != dests.OPS
        if study and learner_id is None:
            from leafi.privacy import runtime

            att = runtime.attribution.get()
            if att is not None:
                learner_id, session_id = att.learner_id, session_id if session_id is not None else att.session_id
        if study and learner_id is None:
            raise Refused("a study purpose needs the learner the attempt is attributed to (design D5)")
        if study and self.watch.stale():
            raise Refused("household privacy settings changed since this process started; restart it")
        texts = list(_texts(out))
        # PARENT_SOURCE is a flag, not a learner: never in the snapshot, the privacy map or the log (M7 D2, S1)
        sources = sorted({s for t in texts for s in t.sources if s != PARENT_SOURCE}
                         | ({learner_id} if study and learner_id else set()))
        c = self._conn()
        cloud = locality == "cloud"
        if cloud:  # allocation writes; done before the read snapshot so the snapshot sees the surrogates
            pseudonym.surrogates(c, self.key, pseudonym.load_lists(c))
        c.execute("BEGIN")
        try:
            snap = versions.snapshot(c, sources) if study else None
            privacy = {i: privacy_settings.from_row(i, c.execute(
                "SELECT kind, forgetting, settings FROM learners WHERE id=?", (i,)).fetchone()) for i in sources}
            p = pseudonym.build_read(c, self.key) if cloud else None
        finally:
            c.execute("COMMIT")
        if cloud:
            for t in texts:
                _gate(t, privacy, self.settings)
        mapping = Mapping()
        words = {w.casefold() for t in texts for w in re.findall(r"\w+", t.value)}
        words |= {w.casefold() for s in _plain_strings(out) for w in re.findall(r"\w+", s)}

        det = self.detector() if cloud and any(t.provenance in CLOUD_TEXT_CLASSES for t in texts) else None

        def fill(v: Text | str) -> str:
            if p is None:
                return v.value if isinstance(v, Text) else v
            if isinstance(v, Text):
                own = v.provenance in CLOUD_TEXT_CLASSES
                return p.apply(v.value, mapping, payload_words=words, detector=det if own else None)
            return p.apply(v, mapping, payload_words=words)

        path = out.path.format(**{k: quote(fill(v), safe="") for k, v in out.path_fields.items()})
        query = urlencode(sorted((k, fill(v)) for k, v in out.query.items()))
        headers = dict(out.headers)
        body_value = None
        if out.json is not None:
            body_value = _walk(out.json, fill)
            body = canonical_json(body_value)
            headers.setdefault("content-type", "application/json")
        elif out.form is not None:
            body = urlencode(sorted((k, fill(v)) for k, v in out.form.items())).encode()
            headers.setdefault("content-type", "application/x-www-form-urlencoded")
        else:
            body = b""
        host = sorted(dest.hosts)[0]
        default = 443 if dest.scheme in ("https", "wss") else 80
        netloc = host if dest.port == default else f"{host}:{dest.port}"
        url = f"{dest.scheme}://{netloc}{path}" + (f"?{query}" if query else "")
        digest = _digest(self.key, dest, out.method, url, body)
        ttl = ttl_s if ttl_s is not None else (DEFAULT_TTL_S if study else DOWNLOAD_TTL_S)
        cur = c.execute(
            "INSERT INTO egress_log(destination, purpose, learner_id, session_id, payload_size, body_hmac, status, "
            "transmitted_attempts, owner, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, 'sending', 0, ?, ?, ?)",
            (dest.name, purpose, learner_id if study else None, session_id, len(body), digest, self.owner,
             now_iso(), now_iso()))
        tok = Token(secrets.token_urlsafe(18), dest, purpose, learner_id, session_id, int(cur.lastrowid),
                    out.method.upper(), url, body, body_value, digest, snap, self.watch.loaded,
                    time.monotonic() + ttl, 2 if purpose in dests.TEXT_PURPOSES else 1, model, locality, budget)
        for gone in self.tokens.add(tok):
            self._finish(gone, "failed")
        return Prepared(tok.id, tok.method, url, body, body_value, headers, mapping, tok.attempt_id)

    def contains_protected(self, text: str) -> bool:
        """Whether `text` holds a listed name (TTS routing, design D13): such a line is spoken locally."""
        c = self._conn()
        version = versions.protected_version(c)
        cached = getattr(self, "_lists", None)
        if cached is None or cached[0] != version:
            lists = pseudonym.load_lists(c)
            cached = self._lists = (version, lists.pattern())
        return cached[1] is not None and cached[1].search(pseudonym.norm(text)) is not None

    @contextlib.asynccontextmanager
    async def library_call(self, prepared: Prepared):
        """For a library that opens its own connection (edge-tts `library` mode, design D14): claims the token,
        admits the transmission, and holds a grant to the destination's host for the duration of the call. The
        library must send exactly `prepared.json`'s text, which the caller passes it."""
        tok = self.tokens.claim(prepared.token_id)
        if tok is None:
            raise Refused("attempt token spent, expired or unknown")
        status = "unknown"
        try:
            reason = await self.admit(tok)
            if reason is not None:
                status = "failed"
                raise Refused(reason)
            host = sorted(tok.destination.hosts)[0]
            ttl = max(0.1, tok.expires - time.monotonic()) + READ_ALLOWANCE_S
            addresses = await self.resolve(host, tok.destination.port, ttl)
            with netguard.grant(host, addresses, tok.destination.port, ttl_s=ttl):
                try:
                    yield
                except BaseException as e:
                    status = "failed" if isinstance(e, Exception) else "unknown"
                    raise
            status = "sent"
        finally:
            self._finish(tok, status)

    async def fetch(self, destination: str, path: str, target: Path) -> None:
        """An `ops` download (doctor, design D16): `GET` the destination's `path` into `target`, following a
        redirect only to a host the destination lists, at most its hop limit, each hop its own prepared request,
        token and grant; credentials are never carried (none are sent)."""
        dest = self.registry[destination]
        hops = 0
        out = Outgoing(method="GET", path=path, headers={})
        while True:
            p = self.prepare(dest, dests.OPS, out)
            async with self.client_for(dest, timeout=httpx2.Timeout(60.0)) as c:
                async with c.stream("GET", p.url, headers={TOKEN_HEADER: p.token_id}) as r:
                    if r.status_code in (301, 302, 303, 307, 308) and "location" in r.headers:
                        nxt = urlsplit(str(r.url.join(r.headers["location"])))
                        allowed = dest.redirects.hosts | dest.hosts if dest.redirects else set()
                        hops += 1
                        if (nxt.hostname or "") not in allowed or nxt.scheme != "https" or (
                                dest.redirects and hops > dest.redirects.max_hops):
                            raise Refused(f"{destination}: redirect to {nxt.hostname!r} not allowed")
                        dest = Destination(f"{destination}>{nxt.hostname}", "https", frozenset({nxt.hostname}),
                                           nxt.port or 443, frozenset({dests.OPS}), "cloud",
                                           redirects=self.registry[destination].redirects)
                        out = Outgoing(method="GET", path=nxt.path or "/",
                                       query=dict(_pairs(nxt.query)), headers={})
                        continue
                    if r.status_code == 403 and r.headers.get("content-type", "").startswith("application/json"):
                        body = await r.aread()
                        raise Refused(json.loads(body).get("refused", "refused"))
                    r.raise_for_status()
                    target.parent.mkdir(parents=True, exist_ok=True)
                    part = target.with_name(target.name + ".part")
                    with open(part, "wb") as f:  # noqa: ASYNC230 - doctor's own loop runs nothing else
                        async for chunk in r.aiter_bytes(1 << 20):
                            f.write(chunk)
                    part.replace(target)
                    return

    # ---- the name detector (design D11; M7 design D8: loaded off the event loop, four states plus `failed`)
    def start_detector(self) -> None:
        """Begin loading the detector in a worker thread (spaCy takes seconds). Called at process start by every
        process that may prepare learner text, so a study session normally finds it `ready`; a no-op once begun."""
        from leafi.privacy import detector

        with self._det_lock:
            if self.detector_state != "unloaded":
                return
            if detector.state(self.settings) != "on":  # off, or its model missing: nothing heavy to load
                self._detector, self.detector_state = detector.load(self.settings), "off"
                self._det_done.set()
                return
            self.detector_state = "loading"
        threading.Thread(target=self._load_detector, name="leafi-detector", daemon=True).start()

    def _load_detector(self) -> None:
        from leafi.privacy import detector

        try:
            det, state = detector.load(self.settings), None
        except Exception:  # noqa: BLE001 - a broken model is reported, and replacement falls back to the lists
            log.warning("name detector failed to load; list-only replacement", exc_info=True)
            det, state = None, "failed"
        with self._det_lock:
            self._detector = det
            self.detector_state = state or ("ready" if det is not None else "off")
        self._det_done.set()

    def detector(self):
        """The name detector for a learner's own words, or None (off, model missing, or `failed`: list-only,
        warned). Inside a study session (an attribution is set) it never loads on the event loop: while it is
        `unloaded` or `loading` the leaf is refused (`detector not ready`) and the call falls back like any
        refusal. Outside a session it loads, or waits for the load, as M5 did."""
        from leafi.privacy import runtime

        if self.detector_state == "unloaded":
            self.start_detector()  # settles `off` at once; a model on disk starts loading
        if self.detector_state in ("ready", "off", "failed"):
            return self._detector
        if runtime.attribution.get() is not None:
            raise Refused("detector not ready: learner text waits until the name detector has loaded")
        self.start_detector()
        self._det_done.wait()
        return self._detector

    # ---- clients
    def client(self, destination: str, **kw) -> httpx2.AsyncClient:
        """An httpx2 client whose every request must carry a token prepared for `destination`."""
        return self.client_for(self.registry[destination], **kw)

    def client_for(self, dest: Destination, **kw) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=MediatingTransport(self, dest, self._inner), trust_env=False,
                                  follow_redirects=False, **kw)

    # ---- the attempt
    def _finish(self, tok: Token, status: str) -> None:
        try:
            self._conn().execute("UPDATE egress_log SET status=?, updated_at=? WHERE id=? AND status='sending'",
                                 (status, now_iso(), tok.attempt_id))
        except sqlite3.Error:
            log.warning("egress_log %s not updated to %s", tok.attempt_id, status, exc_info=True)

    async def admit(self, tok: Token) -> str | None:
        """Immediately before a transmission: inside each attempt of one write transaction (U11; M7 design D7),
        retried while busy until the expiry — the household fingerprint, the versions, the budget's `can_cover`,
        the reservation; after the commit, one charge. A busy attempt rolls back and repeats every check, so a
        change during the wait is seen and nothing is charged twice; a refusal charges nothing."""
        first = tok.reserved == 0
        while True:
            c = self._conn()
            try:
                c.execute("BEGIN IMMEDIATE")
                try:
                    reason = None
                    if tok.study and self.watch.current() != tok.fingerprint:
                        reason = "household privacy settings changed"
                    elif tok.snapshot is not None:
                        now = versions.snapshot(c, [s.learner_id for s in tok.snapshot.sources])
                        reason = versions.stale(tok.snapshot, now)
                    if reason is None and tok.budget is not None and not tok.budget.can_cover(first):
                        reason = "over budget"
                    if reason is None and tok.budget is None and self.budget is not None and not self.budget(tok):
                        reason = "over budget"  # the process-wide hook (tests); a token's own budget wins
                    if reason is not None:
                        c.execute("ROLLBACK")
                        return reason
                    c.execute("UPDATE egress_log SET transmitted_attempts = transmitted_attempts + 1, updated_at=? "
                              "WHERE id=?", (now_iso(), tok.attempt_id))
                    c.execute("COMMIT")
                    tok.reserved += 1
                    if tok.budget is not None:
                        tok.budget.charge(first)  # synchronous: nothing can cut it after the commit
                    return None
                except BaseException:
                    if c.in_transaction:
                        c.execute("ROLLBACK")
                    raise
            except sqlite3.OperationalError as e:
                if e.sqlite_errorname not in ("SQLITE_BUSY", "SQLITE_LOCKED"):
                    raise
                if time.monotonic() + 0.05 > tok.expires:
                    return "database busy until the attempt expired"
                await asyncio.sleep(0.05)


def _texts(out: Outgoing):
    vals = [*out.path_fields.values(), *out.query.values(), *(out.form or {}).values()]
    yield from (v for v in vals if isinstance(v, Text))
    yield from _json_texts(out.json)


def _json_texts(v):
    if isinstance(v, Text):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _json_texts(x)
    elif isinstance(v, list | tuple):
        for x in v:
            yield from _json_texts(x)


def _plain_strings(out: Outgoing):
    vals = [*out.path_fields.values(), *out.query.values(), *(out.form or {}).values()]
    yield from (v for v in vals if isinstance(v, str))

    def walk(v):
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict):
            for x in v.values():
                yield from walk(x)
        elif isinstance(v, list | tuple):
            for x in v:
                yield from walk(x)

    yield from walk(out.json)


def _walk(v, fill):
    if isinstance(v, Text | str):
        return fill(v)
    if isinstance(v, dict):
        return {k: _walk(x, fill) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_walk(x, fill) for x in v]
    return v


def _gate(t: Text, privacy: dict[int, privacy_settings.LearnerPrivacy], settings: Settings) -> None:
    """ADR-0018 §3 for a cloud destination: a learner's words only with every source learner allowing it; text
    of parent origin (a mixed output carrying PARENT_SOURCE, M7 design D2) only with CLOUD_PARENT_TEXT on too."""
    if PARENT_SOURCE in t.sources and not getattr(settings, "cloud_parent_text", False):
        raise Refused("parent text may not leave (CLOUD_PARENT_TEXT off)")
    if t.provenance in CLOUD_TEXT_CLASSES:
        learners = [s for s in t.sources if s != PARENT_SOURCE]
        if not learners:
            raise Refused(f"{t.provenance} text without its source learners")
        for s in learners:
            p = privacy.get(s)
            if p is None or not p.cloud_text_allowed:
                raise Refused(f"learner {s}'s own words may not leave: cloud.text off, a guest, or not a learner")
    elif t.provenance == "parent" and not getattr(settings, "cloud_parent_text", False):
        raise Refused("parent text may not leave (CLOUD_PARENT_TEXT off)")
    elif t.provenance not in ("page", "system", "parent"):
        raise Refused(f"unknown provenance {t.provenance!r}")


# ---------------------------------------------------------------- the transport


class _GrantStream(httpx2.AsyncByteStream):
    """A response body whose grant is revoked when it is closed (or fully read)."""

    def __init__(self, inner, on_close: Callable[[], None]) -> None:
        self._inner, self._on_close, self._closed = inner, on_close, False

    async def __aiter__(self):
        try:
            async for chunk in self._inner:
                yield chunk
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._inner.aclose()
        finally:
            self._on_close()


class MediatingTransport(httpx2.AsyncBaseTransport):
    def __init__(self, egress: Egress, dest: Destination, inner: httpx2.AsyncBaseTransport | None = None) -> None:
        self.egress, self.dest = egress, dest
        self.inner = inner or httpx2.AsyncHTTPTransport(
            retries=0, limits=httpx2.Limits(max_keepalive_connections=0))

    async def aclose(self) -> None:
        await self.inner.aclose()

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        ids = request.headers.get_list(TOKEN_HEADER)
        if TOKEN_HEADER in request.headers:
            del request.headers[TOKEN_HEADER]  # never on the wire, never hashed
        if len(ids) != 1:
            return refused("no attempt token" if not ids else "more than one attempt token", request)
        tok = self.egress.tokens.claim(ids[0])
        if tok is None:
            return refused("attempt token spent, expired or unknown", request)
        try:
            body = await request.aread()
            reason = self._mismatch(tok, request, body)
            if reason is not None:
                self.egress._finish(tok, "failed")
                return refused(reason, request)
            return await self._send(tok, request)
        except BaseException:
            self.egress._finish(tok, "unknown")
            raise

    def _mismatch(self, tok: Token, request: httpx2.Request, body: bytes) -> str | None:
        if tok.destination is not self.dest:
            return "token prepared for another destination"
        if request.method.upper() != tok.method or str(request.url) != tok.url:
            return "request is not the one prepared"
        for name, value in request.headers.items():
            if not self.dest.accepts_header(name, value):
                return f"header {name!r} not accepted by {self.dest.name}"
        if tok.body_value is not None and body != tok.body:
            try:
                parsed = strict_parse(body)
            except (ValueError, UnicodeDecodeError) as e:
                return f"body not acceptable: {e}"
            if canonical_json(parsed) != tok.body:  # type-strict: canonical JSON tells true from 1 from 1.0
                return "body differs from the prepared one"
        elif tok.body_value is None and body != tok.body:
            return "body differs from the prepared one"
        return None

    async def _send(self, tok: Token, request: httpx2.Request) -> httpx2.Response:
        for attempt in range(tok.transmissions):
            if time.monotonic() >= tok.expires:
                self.egress._finish(tok, "failed")
                return refused("attempt expired", request)
            reason = await self.egress.admit(tok)
            if reason is not None:
                self.egress._finish(tok, "failed")
                return refused(reason, request)
            last = attempt + 1 == tok.transmissions
            try:
                resp = await self._transmit(tok, request)
            except netguard.NetworkDenied as e:
                self.egress._finish(tok, "failed")
                return refused(str(e), request)
            except (httpx2.ConnectError, httpx2.ConnectTimeout) as e:
                denied = _denial(e)  # anyio reports a refused connect as a failed one: never retry a refusal
                if denied is not None:
                    self.egress._finish(tok, "failed")
                    return refused(str(denied), request)
                if last:
                    self.egress._finish(tok, "failed")
                    raise
                await asyncio.sleep(min(RETRY_WAIT_S, max(0.0, tok.expires - time.monotonic())))
                continue
            if resp.status_code >= 500 and not last:
                await resp.aclose()
                await asyncio.sleep(min(RETRY_WAIT_S, max(0.0, tok.expires - time.monotonic())))
                continue
            if 300 <= resp.status_code < 400 and "location" in resp.headers:
                if not tok.study and self.dest.redirects is not None:
                    self.egress._finish(tok, "sent")  # an ops download hop: `Egress.fetch` checks the target
                    return resp
                await resp.aclose()
                self.egress._finish(tok, "failed")
                return refused(f"redirect from {self.dest.name} not followed", request)
            self.egress._finish(tok, "sent" if resp.status_code < 400 else "failed")
            return resp
        self.egress._finish(tok, "failed")  # pragma: no cover - the loop always returns
        return refused("no transmission left", request)

    async def _transmit(self, tok: Token, request: httpx2.Request) -> httpx2.Response:
        host = (request.url.host or "").lower()
        port = request.url.port or self.dest.port
        ttl = max(0.1, tok.expires - time.monotonic()) + READ_ALLOWANCE_S
        addresses = await self.egress.resolve(host, port, ttl)
        g, ctx = netguard.open_grant(host, addresses, port, ttl_s=ttl)
        try:
            resp = await self.inner.handle_async_request(request)
        except BaseException:
            netguard.leave(ctx)
            netguard.revoke(g)
            raise
        netguard.leave(ctx)
        resp.stream = _GrantStream(resp.stream, lambda: netguard.revoke(g))
        return resp


def _pairs(query: str) -> list[tuple[str, str]]:
    from urllib.parse import parse_qsl

    return parse_qsl(query, keep_blank_values=True)


def _denial(exc: BaseException) -> netguard.NetworkDenied | None:
    """The guard's refusal anywhere in an exception's causes (anyio and httpcore wrap it)."""
    seen: set[int] = set()
    todo = [exc]
    while todo:
        e = todo.pop()
        if id(e) in seen:
            continue
        seen.add(id(e))
        if isinstance(e, netguard.NetworkDenied):
            return e
        todo += [x for x in (e.__cause__, e.__context__) if x is not None]
        todo += list(getattr(e, "exceptions", ()))
    return None


async def _resolve(host: str, port: int, ttl: float) -> list[str]:
    if netguard._ip(host) is not None or netguard._is_loopback(host):
        return ["127.0.0.1", "::1"] if host == "localhost" else [host]
    with netguard.grant(host, [], None, ttl_s=min(ttl, 10.0), kind="resolve"):
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=0)
    return sorted({ai[4][0].split("%")[0] for ai in infos})
