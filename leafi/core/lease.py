"""Speech lease (GLOSSARY): the study session's exclusive right to speak through the shared Mouths.

File `data/leafi.lock` holds `{"pid", "token", "expires"}`. It is held while the pid is alive and the
expiry (wall clock) is in the future; a stale file is taken over. Standard library only, so the legacy
habit track (`agent/speaker.py`) can import it lazily without the rest of Leafi.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path("data/leafi.lock")


class LeaseHeld(RuntimeError):
    pass


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # os.kill(pid, 0) would call TerminateProcess on Windows; ask the kernel instead.
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def holder(path: Path = DEFAULT_PATH, now: float | None = None) -> dict | None:
    """The live lease record, or None when the lease is free (missing, expired or dead pid)."""
    rec = _read(path)
    if not rec:
        return None
    now = time.time() if now is None else now
    if float(rec.get("expires", 0)) <= now:
        return None
    if not pid_alive(int(rec.get("pid", 0))):
        return None
    return rec


def is_held(path: Path = DEFAULT_PATH) -> bool:
    return holder(path) is not None


@dataclass
class Lease:
    path: Path
    token: str
    ttl_s: float

    def renew(self) -> None:
        rec = _read(self.path)
        if not rec or rec.get("token") != self.token:
            raise LeaseHeld("lease lost")
        _write(self.path, self.token, self.ttl_s)

    def release(self) -> None:
        rec = _read(self.path)
        if rec and rec.get("token") == self.token:
            try:
                self.path.unlink()
            except OSError:
                pass


def _write(path: Path, token: str, ttl_s: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"pid": os.getpid(), "token": token, "expires": time.time() + ttl_s}),
                   encoding="utf-8")
    os.replace(tmp, path)


def acquire(path: Path = DEFAULT_PATH, ttl_s: float = 60.0) -> Lease:
    rec = holder(path)
    if rec is not None and int(rec.get("pid", 0)) != os.getpid():
        raise LeaseHeld(f"speech lease held by pid {rec.get('pid')}")
    token = uuid.uuid4().hex
    _write(path, token, ttl_s)
    return Lease(path, token, ttl_s)
