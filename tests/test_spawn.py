"""ADR-0017 §1: the latch is set before anything is cancelled; children only through `spawn`."""

from __future__ import annotations

import time

import anyio
import pytest

from leafi.study.harness.latch import Latch, Terminal


async def _session_body(latch: Latch, body) -> list[str]:
    seen: list[str] = []
    try:
        with anyio.CancelScope() as latch.scope:
            async with anyio.create_task_group() as latch.tg:
                latch.spawn(latch.deadline_watcher)
                try:
                    await body(latch, seen)
                finally:
                    latch.tg.cancel_scope.cancel()
    except* Terminal:
        seen.append("terminal")
    except* RuntimeError:
        seen.append("child error reached the session")
    return seen


async def test_a_failing_child_sets_internal_error_before_the_body_is_cancelled():
    latch = Latch()

    async def child() -> None:
        await anyio.sleep(0.05)
        raise RuntimeError("boom")

    async def body(latch: Latch, seen: list[str]) -> None:
        latch.spawn(child)
        try:
            await anyio.sleep(10)
        except anyio.get_cancelled_exc_class():
            seen.append(f"cancelled with {latch.terminal}")  # the latch is already set
            raise

    seen = await _session_body(latch, body)
    assert latch.terminal == "internal_error"
    assert seen[0] == "cancelled with internal_error"
    assert "child error reached the session" in seen


async def test_the_deadline_watcher_sets_time_up_before_the_scope_is_cancelled():
    latch = Latch(hard_deadline=time.monotonic() + 0.1)

    async def body(latch: Latch, seen: list[str]) -> None:
        try:
            await anyio.sleep(10)
        except anyio.get_cancelled_exc_class():
            seen.append(f"cancelled with {latch.terminal}")
            raise

    t0 = time.monotonic()
    seen = await _session_body(latch, body)
    assert seen == ["cancelled with time_up_session"]
    assert latch.status() == "time_up_session"
    assert time.monotonic() - t0 < 1.0


async def test_terminate_is_monotonic_and_checkpoint_raises_once_set():
    latch = Latch()
    latch.checkpoint()
    assert latch.terminate("stop") is True
    assert latch.terminate("lease_lost") is False  # the first terminal wins
    with pytest.raises(Terminal) as e:
        latch.checkpoint()
    assert e.value.reason == "stop" and latch.status() == "stopped"
    with pytest.raises(ValueError):
        Latch().terminate("bored")


def test_skips_are_consumed_exactly_once():
    latch = Latch()
    latch.post_skip()
    assert latch.take_skip() is True
    assert latch.take_skip() is False
    latch.post_skip()
    latch.post_skip()
    assert latch.drain_skips() == 2 and latch.take_skip() is False


def test_a_settings_change_reloads_and_bumps_the_epoch_and_a_busy_read_keeps_the_previous():
    versions = iter([(1, 1), (2, 1), RuntimeError("database is locked"), (2, 1)])
    reloads = []

    def read() -> tuple[int, int]:
        v = next(versions)
        if isinstance(v, Exception):
            raise v
        return v

    latch = Latch(versions=read, on_settings_change=lambda: reloads.append(1))
    latch.epoch.learner_settings_version = latch.epoch.household_settings_version = 1
    latch.checkpoint()
    assert latch.epoch.turn_id == 0 and not reloads
    latch.checkpoint()
    assert latch.epoch.turn_id == 1 and reloads == [1]
    latch.checkpoint()  # busy: previous settings kept, no bump
    latch.checkpoint()
    assert latch.epoch.turn_id == 1 and reloads == [1]
