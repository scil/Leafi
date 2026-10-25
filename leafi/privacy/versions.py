"""What a prepared request was filtered under, so the transport can refuse it if that changed (design D12).

Two versions live in the database and move in the writer's own transaction: the household's `protected_version`
(bumped by triggers on every change to learners' names, aliases, kinds, forgetting, and to `household_terms`)
and each learner's `privacy.version` (bumped by `leafi.privacy.settings`). The household privacy keys live in
`.env`, which cannot share a transaction with the database, so they are bound by a fingerprint instead: an HMAC
of their effective values (the file's values with this process's environment overrides applied, as `Settings`
resolves them). No counter is written anywhere, so there is no two-store write a crash can split.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from leafi.core.config import LEGACY_TIER_KEYS, TIER_KEYS, effective_tiers, process_environment
from leafi.core.storage import loads

# The household keys whose change must stop requests prepared before it (design D12).
POLICY_KEYS = ("TTS_EDGE_MODE", "PRIVACY_NAME_DETECTOR",
               "LOCAL_MODELS", "MAGPIE_URL", "OLLAMA_URL", "PRIVACY_OPS_LOG_DAYS", "HOUSEHOLD_TZ", "BRAIN_ROUTES")
# The Brain tiers enter the fingerprint by their EFFECTIVE value (M7 design D9): writing the tier keys while
# commenting out an equal legacy key changes nothing for a running process; changing what is routed does.
TIER_READ_KEYS = (*TIER_KEYS.values(), *LEGACY_TIER_KEYS.values())


@dataclass(frozen=True)
class Source:
    """A source learner as egress sees it: missing (`kind` None), forgetting, and its privacy version."""

    learner_id: int
    kind: str | None
    forgetting: bool
    privacy_version: int


@dataclass(frozen=True)
class Snapshot:
    protected_version: int
    sources: tuple[Source, ...]


def protected_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM privacy_state WHERE key='protected_version'").fetchone()
    return int(row[0]) if row else 0


def snapshot(conn: sqlite3.Connection, learner_ids: Iterable[int]) -> Snapshot:
    """Both versions in one read; the caller runs it inside the read transaction that also reads the lists."""
    ids = sorted(set(learner_ids))
    rows = {}
    if ids:
        marks = ", ".join("?" for _ in ids)
        rows = {r[0]: r for r in conn.execute(
            f"SELECT id, kind, forgetting, settings FROM learners WHERE id IN ({marks})", ids)}
    out = []
    for i in ids:
        r = rows.get(i)
        if r is None:
            out.append(Source(i, None, False, 0))
        else:
            out.append(Source(i, r[1], bool(r[2]), int(loads(r[3], {}).get("privacy.version", 0))))
    return Snapshot(protected_version(conn), tuple(out))


def stale(prepared: Snapshot, now: Snapshot) -> str | None:
    """The reason a request prepared under `prepared` may not be sent now, or None."""
    if prepared.protected_version != now.protected_version:
        return "protected names changed"
    for a, b in zip(prepared.sources, now.sources, strict=True):
        if b.kind is None:
            return f"source learner {a.learner_id} is gone"
        if b.forgetting:
            return f"source learner {a.learner_id} is being forgotten"
        if (a.kind, a.privacy_version) != (b.kind, b.privacy_version):
            return f"privacy settings of learner {a.learner_id} changed"
    return None


def policy_values(env_file: Path | None = Path(".env"), environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The effective household privacy keys: `.env` (parsed as `Settings` parses it), overridden by the process
    environment (pydantic-settings: the environment wins; names are case-insensitive)."""
    from dotenv import dotenv_values

    environ = process_environment() if environ is None else environ
    read = (*POLICY_KEYS, *TIER_READ_KEYS)
    values: dict[str, str] = {}
    if env_file is not None and Path(env_file).exists():
        for k, v in dotenv_values(env_file, encoding="utf-8").items():
            if k.upper() in read and v is not None:
                values[k.upper()] = v
    for k, v in environ.items():
        if k.upper() in read:
            values[k.upper()] = v
    return values


def fingerprint(secret: bytes, values: Mapping[str, str]) -> str:
    tiers = effective_tiers({k: v for k, v in values.items() if k in TIER_READ_KEYS})
    body = json.dumps({**{k: values.get(k) for k in POLICY_KEYS}, "BRAIN_TIERS": tiers}, sort_keys=True,
                      separators=(",", ":"))
    return hmac.new(secret, b"policy:" + body.encode(), hashlib.sha256).hexdigest()


class PolicyWatch:
    """This process's fingerprint, taken when it loaded its settings, and a cheap check that `.env` still matches:
    the file is reparsed only when its mtime or size changed."""

    def __init__(self, secret: bytes, env_file: Path | None = Path(".env"),
                 environ: Mapping[str, str] | None = None) -> None:
        self._secret = secret
        self._env_file = Path(env_file) if env_file is not None else None
        self._environ = environ
        self.loaded = fingerprint(secret, policy_values(self._env_file, environ))
        self._stamp = self._file_stamp()
        self._current = self.loaded

    def _file_stamp(self) -> tuple[int, int] | None:
        if self._env_file is None:
            return None
        try:
            st = self._env_file.stat()
        except FileNotFoundError:
            return None
        return st.st_mtime_ns, st.st_size

    def current(self) -> str:
        stamp = self._file_stamp()
        if stamp != self._stamp:
            self._stamp = stamp
            self._current = fingerprint(self._secret, policy_values(self._env_file, self._environ))
        return self._current

    def stale(self) -> bool:
        """True once `.env`'s privacy keys differ from what this process loaded: refuse study egress until a
        restart (design D12)."""
        return self.current() != self.loaded
