"""ADR-0017 Confirmation `test_cancellation.py`: a stop and a deadline inside `listen` and inside `negotiate` end
the running activity with the mapped status, never `running`; the watcher sets `time_up_session` before the scope
is cancelled; an unexpected exception finalizes as `internal_error`; `deliver` and `extract_notes` run after
`time_up_session` and after `stop`, and a failing `deliver` does not skip extraction. Inside a Brain call (M7 design
D8, D12, D21): a stop typed or spoken during `decide` ends the session with the call recorded `cancelled`; a
`decide` past its deadline is recorded `timeout` and the default chain decides; an audit row a busy store kept back
is written at `finalize`."""

from __future__ import annotations

import random
import sqlite3
import time

import anyio
import pytest

from leafi.services.brain.mock import MockModel
from leafi.study.brain import call as bc
from leafi.study.brain import routing
from leafi.study.harness import activities, loop
from tests.fakes import ScriptedListener
from tests.harness_session import activities as acts
from tests.harness_session import env, run, summary
from tests.test_brain_session import _read

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


# ---------------------------------------------------------------- inside a Brain call (M7)


class HangingModel(MockModel):
    """A `decide` that never answers; `active` while a call is in flight."""

    def __init__(self) -> None:
        super().__init__({})
        self.calls, self.active = 0, False

    async def call(self, req):
        req.attempt.sent, req.attempt.model = {"purpose": req.purpose}, req.model
        self.calls, self.active = self.calls + 1, True
        try:
            await anyio.sleep(3600)
        finally:
            self.active = False


class Gated(ScriptedListener):
    """Answers only when `ready()` holds (during the call, or once it is over)."""

    def __init__(self, script, ready, voice: bool = False) -> None:
        super().__init__(script, voice=voice)
        self.ready = ready

    async def next_utterance(self, timeout_s):
        while not self.ready():  # noqa: ASYNC110 - a predicate over session state, which sets no event
            await anyio.sleep(0.01)
        return await super().next_utterance(timeout_s)


def _brain(model) -> bc.Brain:
    return bc.Brain({"fast": [(model, "mock-decide")], "standard": [], "deep": []})


@pytest.mark.parametrize("voice", [False, True])
async def test_a_stop_during_a_brain_call_ends_the_session_and_records_it_cancelled(settings, voice):
    model = HangingModel()
    e = env(settings, [], learner="Ada", brain=_brain(model), rng=random.Random(1),
            listener=Gated(["/stop" if not voice else "stop"], lambda: model.active, voice=voice))
    sid = await run(e, limit_s=10)
    assert summary(e.store, sid)["end"] == "stop" and acts(e.store, sid) == []
    rows = e.store.all("SELECT purpose, outcome FROM brain_calls WHERE session_id=?", (sid,))
    assert [tuple(r) for r in rows] == [("decide", "cancelled")]


async def test_a_decide_past_its_deadline_is_a_timeout_and_the_default_chain_decides(settings, monkeypatch):
    monkeypatch.setitem(routing.TOTAL_S, "decide", 0.6)
    monkeypatch.setitem(routing.PER_CALL_S["decide"], "fast", 0.4)
    monkeypatch.setitem(routing.MIN_TIER_S, "fast", 0.1)
    model, session = HangingModel(), []
    decided = lambda: bool(session) and session[0].boundary.override == "brain_unavailable"  # noqa: E731
    e = env(settings, [], learner="Ada", brain=_brain(model), rng=random.Random(1),
            listener=Gated([None, "The fox ran home. It was late and dark."], decided))
    e.on_built = lambda s, w: session.append(s)
    sid = await run(e, limit_s=10)
    row = e.store.one("SELECT decided_by, arm, override FROM activities WHERE session_id=? ORDER BY id LIMIT 1",
                      (sid,))
    assert tuple(row) == ("default", "brain", "brain_unavailable")
    outcomes = {r[0] for r in e.store.all("SELECT outcome FROM brain_calls WHERE session_id=?", (sid,))}
    assert outcomes == {"timeout"}


async def test_an_audit_row_a_busy_store_kept_back_is_written_at_finalize(settings, monkeypatch):
    locked, held = [True], []
    insert = bc._insert

    def busy_insert(store, row):
        if locked[0]:
            raise sqlite3.OperationalError("database is locked")
        insert(store, row)

    monkeypatch.setattr(bc, "_insert", busy_insert)
    session = []

    def ready() -> bool:  # the first answer comes after the busy audit gave up; the store frees up then
        if session and session[0].pending_audit_brain:
            held.append(len(session[0].pending_audit_brain))
            locked[0] = False
            return True
        return False

    e = env(settings, [], learner="Ada", brain=_brain(MockModel({"decide": _read})), rng=random.Random(1),
            listener=Gated([None, "/stop"], lambda: not locked[0] or ready()))
    e.on_built = lambda s, w: session.append(s)
    sid = await run(e, limit_s=10)
    assert held and held[0] == 1  # kept back while the store was busy
    rows = e.store.all("SELECT purpose, outcome FROM brain_calls WHERE session_id=?", (sid,))
    assert [tuple(r) for r in rows] == [("decide", "ok")] and not session[0].pending_audit_brain
