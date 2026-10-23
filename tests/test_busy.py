"""ADR-0017 §7.3 busy store: no step blocks the loop for more than 300 ms; a step still busy at its limit ends the
activity `store_busy` (its row written with the next successful write); a busy `finalize` leaves the work to
startup recovery. (`apply_records` / `record_boundary` drops arrive with M7; a busy settings read keeping the
previous settings is `test_spawn`; a busy `adopt` retrying identification is `identify.adopt`.)"""

from __future__ import annotations

import sqlite3
import time

import anyio
import pytest

from leafi.core.storage import Store
from leafi.study.harness import busy, loop, rows
from leafi.study.harness.state import Activity
from tests.harness_session import env, run
from tests.harness_world import make_world


def _lock(path):
    other = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    other.execute("BEGIN IMMEDIATE")  # the supervisor (or anyone) holding the write lock
    return other


async def _max_gap(stop: anyio.Event, gaps: list[float]) -> None:
    last = time.monotonic()
    while not stop.is_set():
        await anyio.sleep(0.01)
        now = time.monotonic()
        gaps.append(now - last)
        last = now


async def test_a_busy_write_retries_without_blocking_the_loop_and_succeeds_once_free(tmp_path):
    store = Store(tmp_path / "leafi.db", busy_timeout_ms=busy.STUDY_BUSY_TIMEOUT_MS)
    other = _lock(store.path)
    gaps: list[float] = []
    stop = anyio.Event()

    async def release() -> None:
        await anyio.sleep(0.8)
        other.execute("COMMIT")

    async with anyio.create_task_group() as tg:
        tg.start_soon(_max_gap, stop, gaps)
        tg.start_soon(release)
        n = await busy.retry(lambda: store.insert("household_terms", term="fox", kind="name",
                                                  created_at="2026-10-23T00:00:00+00:00"))
        stop.set()
    assert n > 0
    assert max(gaps) < 0.3, max(gaps)  # one attempt blocks about busy_timeout (150 ms) plus Windows timer ticks


async def test_a_write_busy_past_its_limit_raises_store_busy(tmp_path):
    store = Store(tmp_path / "leafi.db", busy_timeout_ms=busy.STUDY_BUSY_TIMEOUT_MS)
    other = _lock(store.path)
    with pytest.raises(busy.StoreBusy):
        await busy.retry(lambda: store.insert("household_terms", term="fox", kind="name",
                                              created_at="2026-10-23T00:00:00+00:00"), limit_s=0.6)
    other.execute("ROLLBACK")


async def test_an_activity_whose_writes_stay_busy_ends_store_busy_and_its_row_is_written_later(settings,
                                                                                                monkeypatch):
    w = make_world(settings, settings, [])
    w.store.conn.execute(f"PRAGMA busy_timeout = {busy.STUDY_BUSY_TIMEOUT_MS}")
    monkeypatch.setattr(busy, "STEP_S", 0.5)
    holder = {}

    async def writes(world, act, aid):
        holder["other"] = _lock(world.store.path)  # taken after the start row, kept through the finish
        world.store.execute("UPDATE learners SET settings='{}' WHERE id=?", (world.s.learner_id,))
        return "completed", {}

    monkeypatch.setitem(loop.KINDS, "break", writes)
    status = await loop.run_activity(w.s, w, Activity("break", {"seconds": 5}, "default"))
    assert status == "store_busy" and w.s.pending_rows  # kept in memory
    holder["other"].execute("ROLLBACK")
    monkeypatch.setitem(loop.KINDS, "end", lambda world, act, aid: _done())
    await loop.run_activity(w.s, w, Activity("end", {}, "default"))
    assert not w.s.pending_rows
    assert [r["status"] for r in w.store.all("SELECT status FROM activities ORDER BY id")] == ["store_busy",
                                                                                              "completed"]


async def _done():
    return "completed", {}


async def test_a_busy_finalize_leaves_the_session_to_startup_recovery(settings, monkeypatch):
    held = {}

    class LockAtStop:
        is_voice = False

        def __init__(self):
            self.script = [None, "/stop"]

        async def next_utterance(self, timeout_s):
            item = self.script.pop(0) if self.script else "/stop"
            if item == "/stop":
                held["other"] = _lock(settings.db_path)
            from leafi.core.text import typed_utterance

            return None if item is None else typed_utterance(item)

        async def pause(self): ...

        async def resume(self, after_s=0.0): ...

    e = env(settings, [], listener=LockAtStop(), learner="Ada")
    e.store.conn.execute(f"PRAGMA busy_timeout = {busy.STUDY_BUSY_TIMEOUT_MS}")
    monkeypatch.setattr(busy, "STEP_S", 0.3)
    sid = await run(e)  # no exception escapes; the lease is released
    held["other"].execute("ROLLBACK")
    store = Store(settings.db_path)
    assert store.one("SELECT ended_at FROM reading_sessions WHERE id=?", (sid,))["ended_at"] is None
    assert rows.recover(store) == [sid]  # the next start does the work
