"""ADR-0017 Confirmation `test_cancellation.py`: a stop and a deadline inside `listen` and inside `negotiate` end
the running activity with the mapped status, never `running`; the watcher sets `time_up_session` before the scope
is cancelled; an unexpected exception finalizes as `internal_error`; `deliver` and `extract_notes` run after
`time_up_session` and after `stop`, and a failing `deliver` does not skip extraction. (Inside a Brain call: M7.)"""

from __future__ import annotations

import time

from leafi.study.harness import activities, loop
from tests.harness_session import activities as acts
from tests.harness_session import env, run, summary

START = ["Ada", "yes", "no school", None]  # identified, the default chain's read_listen starts


class Clock:
    """Moves the session's deadlines into the past at a chosen moment (no real 20-minute wait)."""

    def __init__(self) -> None:
        self.s = None

    def built(self, s, w) -> None:
        self.s = s

    def expire(self) -> None:
        self.s.latch.hard_deadline = time.monotonic() - 1


async def test_a_stop_inside_listen_ends_the_reading_activity_stopped(settings):
    sid = await run(env(settings, START + ["The fox ran home.", "/stop"]))
    e_store = env(settings, []).store
    assert acts(e_store, sid) == [("read_listen", "stopped", False)]
    assert summary(e_store, sid)["end"] == "stop"


async def test_a_deadline_inside_listen_ends_time_up_and_deliver_and_extraction_still_run(settings, monkeypatch):
    clock = Clock()
    seen = []

    class Hang(type(env(settings, []).listener)):
        async def next_utterance(self, timeout_s):
            if not self.script:
                seen.append(clock.s.latch.terminal)  # the watcher had not fired yet
                clock.expire()
                import anyio

                await anyio.sleep(3600)
            return await super().next_utterance(timeout_s)

    e = env(settings, [], listener=Hang(START + ["The fox ran home."]))
    e.on_built = clock.built
    sid = await run(e)
    assert acts(e.store, sid) == [("read_listen", "time_up_session", False)]
    s = summary(e.store, sid)
    assert s["end"] == "time_up_session" and s["closing_line"] == "done" and s["notes"] == "skipped"
    assert seen == [None]


async def test_a_stop_inside_negotiate_writes_no_running_row(settings):
    sid = await run(env(settings, ["Ada", "yes", "/stop"], learner=None))
    store = env(settings, []).store
    assert acts(store, sid) == []  # nothing had started; nothing is left running
    assert store.one("SELECT COUNT(*) AS n FROM activities WHERE status='running'")["n"] == 0


async def test_an_unexpected_exception_in_an_activity_finalizes_internal_error(settings, monkeypatch):
    async def broken(w, act, aid):
        raise ValueError("bug")

    monkeypatch.setitem(activities.KINDS, "read_listen", broken)
    monkeypatch.setitem(loop.KINDS, "read_listen", broken)
    e = env(settings, START)
    sid = await run(e)
    assert acts(e.store, sid) == [("read_listen", "internal_error", False)]
    s = summary(e.store, sid)
    assert s["end"] == "internal_error" and s["closing_line"] == "done"


async def test_a_failing_deliver_does_not_skip_extraction(settings, monkeypatch):
    ran = []

    async def bad_deliver(s, w, env_, summ):
        raise RuntimeError("tts down")

    async def note(s, w, env_, summ):
        ran.append("extract")

    monkeypatch.setattr(loop, "deliver", bad_deliver)
    monkeypatch.setattr(loop, "extract_notes", note)
    await run(env(settings, ["Ada", "yes", "/stop"]))
    assert ran == ["extract"]
