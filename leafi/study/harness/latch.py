"""Controls and cancellation, one owner (ADR-0017 §1).

`s.terminal` is monotonic: the first `terminate(reason)` wins, and setting it is the only way to interrupt the
session; the setter also cancels the session's anyio `CancelScope`, so the latch is always set before anything is
cancelled. The scope has no deadline: `deadline_watcher` sleeps until the hard deadline and then terminates with
`time_up_session`. Children are spawned only through `spawn` into the session's `TaskGroup`; a child that fails
sets `internal_error` before its exception propagates. `checkpoint()` after every await reloads changed settings
(bumping the epoch) and raises `Terminal` once the latch is set. Skips are consumed exactly once by `take_skip`.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import anyio
import anyio.abc

from leafi.study.harness.status import REASONS, ActivityStatus, for_reason

log = logging.getLogger("leafi.harness")


class Terminal(Exception):
    """Raised by `checkpoint` once the latch is set; carries the reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class Epoch:
    """ADR-0017 §1: an item built under one epoch is dropped if the epoch has changed when it would be used."""

    session_id: int | None = None
    learner_id: int | None = None
    cycle_id: int | None = None
    page_read_id: int | None = None
    revision_id: int | None = None
    turn_id: int = 0
    learner_settings_version: int = 0
    household_settings_version: int = 0

    def key(self) -> tuple:
        return (self.session_id, self.learner_id, self.cycle_id, self.page_read_id, self.revision_id, self.turn_id,
                self.learner_settings_version, self.household_settings_version)

    def bump(self) -> None:
        self.turn_id += 1


Versions = Callable[[], tuple[int, int]]


@dataclass
class Latch:
    epoch: Epoch = field(default_factory=Epoch)
    terminal: str | None = None
    terminated_at: float | None = None
    scope: anyio.CancelScope | None = None
    tg: anyio.abc.TaskGroup | None = None
    hard_deadline: float = float("inf")  # time.monotonic() clock
    skips: deque = field(default_factory=deque)
    versions: Versions | None = None  # (learner settings_version, household version); None in tests
    on_settings_change: Callable[[], None] | None = None

    # ---- the latch
    def terminate(self, reason: str) -> bool:
        """Set the latch (first reason wins) and cancel the scope. Returns whether this call set it."""
        if reason not in REASONS:
            raise ValueError(f"terminal reason {reason!r}")
        if self.terminal is not None:
            return False
        self.terminal = reason
        self.terminated_at = time.monotonic()
        log.info("session terminal: %s", reason)
        if self.scope is not None:
            self.scope.cancel()
        return True

    def status(self) -> ActivityStatus:
        """The mapping function (§1) for a cancelled activity."""
        return for_reason(self.terminal)

    def checkpoint(self) -> None:
        """After every await: settings reload (a busy read keeps the previous settings), then the latch."""
        if self.versions is not None:
            try:
                learner_v, household_v = self.versions()
            except Exception:  # a busy store keeps the previous settings (§7.3)
                log.warning("settings read failed; previous settings kept", exc_info=True)
            else:
                e = self.epoch
                if (learner_v, household_v) != (e.learner_settings_version, e.household_settings_version):
                    e.learner_settings_version, e.household_settings_version = learner_v, household_v
                    e.bump()
                    if self.on_settings_change is not None:
                        self.on_settings_change()
        if self.terminal is not None:
            raise Terminal(self.terminal)

    # ---- skips: consumed exactly once
    def post_skip(self) -> None:
        self.skips.append(time.monotonic())

    def take_skip(self) -> bool:
        if self.skips:
            self.skips.popleft()
            return True
        return False

    def drain_skips(self) -> int:
        n = len(self.skips)
        self.skips.clear()
        return n

    # ---- children and the deadline
    def spawn(self, fn: Callable[..., Awaitable[None]], *args) -> None:
        if self.tg is None:
            raise RuntimeError("spawn outside the session's task group")

        async def guarded() -> None:
            try:
                await fn(*args)
            except anyio.get_cancelled_exc_class():
                raise
            except Exception:
                log.exception("child task failed")
                self.terminate("internal_error")  # before the exception reaches the task group
                raise

        self.tg.start_soon(guarded)

    async def deadline_watcher(self) -> None:
        while True:
            now = time.monotonic()
            if now >= self.hard_deadline:
                self.terminate("time_up_session")
                return
            await anyio.sleep(min(self.hard_deadline - now, 3600.0))  # re-read: the deadline may move
