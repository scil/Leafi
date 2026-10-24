"""The filler (ADR-0017 §5; M7 design D12): when a Brain call has not returned after 0.8 s, Faces show "…" and the
PC Mouth says one short filler line. The filler runs in its own task group, never through the session's `spawn`:
a filler error is logged and never ends the session; when the call returns the filler is cancelled and its
cleanup awaited before anything else speaks (one speaker at a time); it does not speak once the epoch changed.
On the camera Mouth it shows Face text only (pushing a clip at the call's start waits for the go2rtc measurement,
M10)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import anyio

from leafi.core.ports import Display
from leafi.study import phrases

log = logging.getLogger("leafi.brain.filler")

FILLER_S = 0.8


async def with_filler[T](call: Awaitable[T], *, show: Callable[[Display], Awaitable[None]],
                      say: Callable[[str], Awaitable[None]] | None, epoch: Callable[[], tuple],
                      after_s: float = FILLER_S) -> T:
    """Await `call`; meanwhile, past `after_s`, the filler. `say` None (the camera Mouth, or no Mouth): Face only."""
    start = epoch()
    result: list = []

    async def filler() -> None:
        try:
            await anyio.sleep(after_s)
            if epoch() != start:
                return
            await show(Display("status", "…"))
            if say is not None:
                await say(phrases.say("filler"))
        except anyio.get_cancelled_exc_class():
            raise
        except Exception:  # noqa: BLE001 - the filler never ends the session
            log.warning("filler failed", exc_info=True)

    async with anyio.create_task_group() as tg:
        tg.start_soon(filler)
        try:
            result.append(await call)
        finally:
            tg.cancel_scope.cancel()  # leaving the group awaits the filler's cleanup
    return result[0]
