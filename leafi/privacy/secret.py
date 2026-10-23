"""The install's HMAC secret `data/egress.key` (design D8): 32 random bytes, made once, read once per process.

Created by writing a temporary file and linking it into place, so two processes racing to create it agree on one
key: the loser of `os.link` reads the winner's file, never a half-written one. Any length but 32 fails closed.
Included in `leafi backup` (a restored database without its key would re-pseudonymise with different surrogates).
"""

from __future__ import annotations

import os
import secrets
import threading
from pathlib import Path

KEY_BYTES = 32
FILENAME = "egress.key"

_lock = threading.Lock()
_cache: dict[Path, bytes] = {}


class KeyFileInvalid(RuntimeError):
    """`data/egress.key` exists with the wrong length: egress refuses until the owner restores or removes it."""


def key_path(data_dir: Path) -> Path:
    return Path(data_dir) / FILENAME


def load(data_dir: Path) -> bytes:
    path = key_path(data_dir).resolve()
    with _lock:
        if path in _cache:
            return _cache[path]
        if not path.exists():
            _create(path)
        key = path.read_bytes()
        if len(key) != KEY_BYTES:
            raise KeyFileInvalid(f"{path} holds {len(key)} bytes, not {KEY_BYTES}; restore it from a backup, or "
                                 "delete it to start new surrogates (every stored surrogate is then reallocated)")
        _cache[path] = key
        return key


def _create(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(secrets.token_bytes(KEY_BYTES))
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, path)  # fails if another process put its key there first; then theirs is the key
        except FileExistsError:
            pass
    finally:
        tmp.unlink(missing_ok=True)


def _forget_cache() -> None:
    """Tests only."""
    with _lock:
        _cache.clear()
