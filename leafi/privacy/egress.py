"""The one way out (ADR-0018 §2, M5 design D5–D9, D16): `prepare` at the call, a mediating transport at the wire.

`prepare(destination, purpose, Outgoing(...))` takes a request as fields, before any encoding. Text that came
from a person is a `Text` with its provenance; a plain string is the caller's own (`system`). It refuses what
the destination, the purpose or the source learners' settings do not allow, replaces every protected name for a
cloud destination (`leafi.privacy.pseudonym`), encodes the fields itself into the exact bytes to send, writes the
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
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx2
import psutil

from leafi.core import netguard
from leafi.core.config import Settings
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
    sources: tuple[int, ...] = ()


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

    @property
    def study(self) -> bool:
        return self.purpose != dests.OPS


@dataclass
class Prepared:
    token_id: str
    method: str
    url: str
    body: bytes
    json: Any  # the prepared JSON value (Text replaced), for an SDK that builds the body itself
    headers: dict[str, str]
    mapping: Mapping

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
        self.tokens = TokenStore()
        self.owner = _owner()
        self._local = threading.local()
        Store(self.db_path).close()  # the file exists at the current schema (or NeedsMigration is raised)
        self._lock = _FileLock(self.db_path, exclusive=False)  # never beside a migration
        self._inner = inner
        self.recover()

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
                ttl_s: float | None = None) -> Prepared:
        dest = destination if isinstance(destination, Destination) else self.registry.get(destination)
        if dest is None:
            raise Refused(f"no destination {destination!r}")
        if purpose not in dest.purposes:
            raise Refused(f"{dest.name} does not accept purpose {purpose!r}")
        if purpose == "media":
            raise Refused("media is refused until M9 (design D20)")
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
        sources = sorted({s for t in texts for s in t.sources} | ({learner_id} if study and learner_id else set()))
        c = self._conn()
        cloud = dest.locality == "cloud"
        legacy = self.settings.redact_list()
        if cloud:  # allocation writes; done before the read snapshot so the snapshot sees the surrogates
            pseudonym.surrogates(c, self.key, pseudonym.load_lists(c, legacy))
        c.execute("BEGIN")
        try:
            snap = versions.snapshot(c, sources) if study else None
            privacy = {i: privacy_settings.from_row(i, c.execute(
                "SELECT kind, forgetting, settings FROM learners WHERE id=?", (i,)).fetchone()) for i in sources}
            p = pseudonym.build_read(c, self.key, legacy) if cloud else None
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
                    time.monotonic() + ttl, 2 if purpose in dests.TEXT_PURPOSES else 1)
        for gone in self.tokens.add(tok):
            self._finish(gone, "failed")
        return Prepared(tok.id, tok.method, url, body, body_value, headers, mapping)

    def contains_protected(self, text: str) -> bool:
        """Whether `text` holds a listed name (TTS routing, design D13): such a line is spoken locally."""
        c = self._conn()
        version = versions.protected_version(c)
        cached = getattr(self, "_lists", None)
        if cached is None or cached[0] != version:
            lists = pseudonym.load_lists(c, self.settings.redact_list())
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

    def detector(self):
        """The name detector for a learner's own words (design D11), loaded on first need (spaCy takes seconds);
        None when it is off or its model is missing (list-only, warned by `detector.load`)."""
        if not hasattr(self, "_detector"):
            from leafi.privacy import detector

            self._detector = detector.load(self.settings)
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
        """Immediately before a transmission: the policy, the versions, the budget, then the reservation — the
        version check and the reservation in one write transaction (U11), retried while busy until the expiry."""
        if tok.study and self.watch.current() != tok.fingerprint:
            return "household privacy settings changed"
        if self.budget is not None and not self.budget(tok):
            return "over budget"
        while True:
            c = self._conn()
            try:
                c.execute("BEGIN IMMEDIATE")
                try:
                    if tok.snapshot is not None:
                        now = versions.snapshot(c, [s.learner_id for s in tok.snapshot.sources])
                        reason = versions.stale(tok.snapshot, now)
                        if reason is not None:
                            c.execute("ROLLBACK")
                            return reason
                    c.execute("UPDATE egress_log SET transmitted_attempts = transmitted_attempts + 1, updated_at=? "
                              "WHERE id=?", (now_iso(), tok.attempt_id))
                    c.execute("COMMIT")
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
    """ADR-0018 §3 for a cloud destination: a learner's words only with every source learner allowing it."""
    if t.provenance in CLOUD_TEXT_CLASSES:
        if not t.sources:
            raise Refused(f"{t.provenance} text without its source learners")
        for s in t.sources:
            p = privacy.get(s)
            if p is None or not p.cloud_text_allowed:
                why = ("no school answer" if p is not None and p.kind == "learner" and p.cloud_text
                       and not p.school_answered else "cloud.text off, a guest, or not a learner")
                raise Refused(f"learner {s}'s own words may not leave: {why}")
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
