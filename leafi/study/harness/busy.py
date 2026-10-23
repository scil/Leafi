"""Busy store (ADR-0017 §7.3): the study process opens its store with a short `busy_timeout` and retries a busy
write with anyio sleeps inside the step's remaining time, so no write blocks the event loop for more than 300 ms;
other processes keep 5 s.

150 ms, not the ADR's 250: measured on Windows (2026-10-23), SQLite's busy handler sleeps in a dozen short steps
and each `Sleep` rounds up to the 15.6 ms timer tick, so 250 ms blocked the loop for 344-360 ms.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable

import anyio

STUDY_BUSY_TIMEOUT_MS = 150
STEP_S = 5.0  # how long one step's write may keep retrying before the activity ends `store_busy`


class StoreBusy(Exception):
    """A write stayed busy past its step's time limit."""


def is_busy(e: BaseException) -> bool:
    if not isinstance(e, sqlite3.OperationalError):
        return False
    msg = str(e).lower()
    return "locked" in msg or "busy" in msg


async def retry[T](fn: Callable[[], T], *, limit_s: float | None = None, first_s: float = 0.05,
                   max_s: float = 0.5) -> T:
    deadline = time.monotonic() + (STEP_S if limit_s is None else limit_s)  # read at call time: tests shorten it
    delay = first_s
    while True:
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if not is_busy(e):
                raise
            if time.monotonic() + delay >= deadline:
                raise StoreBusy(str(e)) from e
            await anyio.sleep(delay)
            delay = min(delay * 2, max_s)
