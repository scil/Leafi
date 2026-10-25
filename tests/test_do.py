"""`/do <kind>` at safe points (ADR-0017 §2.1 as amended 2026-10-25; session panel design D7, step 2): one want
slot, a payload-free wake, `Jump` only at an activity's owned prompts and listens, `activity_over()` at its natural
steps, and every exit of negotiation. Real Store and Inputs, scripted inputs; nothing speaks."""

from __future__ import annotations

import time

import anyio

from leafi.core.storage import loads
from leafi.core.text import typed_utterance
from leafi.study.brain import kinds
from leafi.study.harness import loop
from leafi.study.harness import negotiate as negotiation
from leafi.study.harness.latch import Terminal, Want
from leafi.study.harness.menu import allowed
from leafi.study.harness.negotiate import Run
from leafi.study.harness.state import Activity, Facts
from tests import harness_session as hsess
from tests.fakes import ScriptedListener
from tests.harness_helpers import ScriptedTalk, make_session
from tests.harness_world import make_world, run

READING = Facts(has_book=True, unread_current=True)
LINES = ["The fox ran home.", "It was late and dark."]


def _want(kind="break", source="panel") -> Want:
    return Want(kind, source, None, time.monotonic())


class WantTalk(ScriptedTalk):
    """Posts a want during the n-th call of one method ("say", "ask" or "listen")."""

    def __init__(self, replies, latch, at: tuple[str, int], kind: str = "break") -> None:
        super().__init__(replies, latch)
        self.at, self.kind, self.calls = at, kind, {"say": 0, "ask": 0, "listen": 0}

    def _tick(self, name: str) -> None:
        self.calls[name] += 1
        if (name, self.calls[name]) == self.at:
            self.latch.post_want(_want(self.kind))

    async def say(self, text, **kw):
        self._tick("say")
        await super().say(text, **kw)

    async def ask(self, owner, text, **kw):
        self._tick("ask")
        await super().ask(owner, text, **kw)

    async def listen(self, timeout_s, owner=None, *, accepts_page=True):
        self._tick("listen")
        return await super().listen(timeout_s, owner, accepts_page=accepts_page)


def _session(tmp_path, replies, at, autonomy, **values):
    s = make_session(tmp_path, facts=READING, replies=replies, values={"autonomy": autonomy, **values})
    s.talk = WantTalk(replies, s.latch, at)
    return s


async def _negotiate(s):
    return await negotiation.negotiate(s, None, allowed(s), s.epoch())


def _is_wanted_break(out) -> bool:
    a = out.activity
    return isinstance(out, Run) and a.kind == "break" and a.params.get("by") == "panel" and \
        (a.decided_by, a.override) == ("learner", "learner_choice")


# ---------------------------------------------------------------- at a boundary


async def test_a_want_during_the_announcement_restarts_the_pass(tmp_path):
    s = _session(tmp_path, [], ("say", 1), autonomy=8)
    out = await _negotiate(s)
    assert _is_wanted_break(out)  # the announced reading never starts
    assert s.latch.want is None


async def test_a_want_during_an_offer_listen_wins_over_no_objection_and_over_yes(tmp_path):
    out = await _negotiate(_session(tmp_path / "a", [None], ("listen", 1), autonomy=5))
    assert _is_wanted_break(out)
    out = await _negotiate(_session(tmp_path / "b", ["yes"], ("listen", 1), autonomy=2))
    assert _is_wanted_break(out)


async def test_a_wake_is_never_counted_as_a_silence(tmp_path):
    s = _session(tmp_path, [None], ("listen", 1), autonomy=1, **{"negotiation.silence_reasks": 0})
    out = await _negotiate(s)
    assert _is_wanted_break(out)  # not the wait of a last silence
    assert s.boundary.silences == 0


async def test_a_want_that_cannot_be_built_is_said_so_and_negotiation_goes_on(tmp_path):
    s = _session(tmp_path, ["no", "no", "no"], ("ask", 1), autonomy=2)
    s.talk.kind = "review_anki"  # not on the menu: no Anki
    out = await _negotiate(s)
    assert "I can't review your cards right now." in s.talk.said
    assert isinstance(out, Run) and "by" not in out.activity.params


async def test_a_newer_want_during_the_wanted_construction_wins(tmp_path, monkeypatch):
    s = _session(tmp_path, [], ("say", 99), autonomy=5)
    s.latch.post_want(_want("break"))
    real = negotiation.first_constructible
    calls = []

    async def construct(s_, specs, m):
        calls.append([sp.kind for sp in specs])
        if len(calls) == 1:
            s.latch.post_want(_want("end"))
        return await real(s_, specs, m)

    monkeypatch.setattr(negotiation, "first_constructible", construct)
    out = await _negotiate(s)
    assert calls[:2] == [["break"], ["end"]]
    assert out.activity.kind == "end" and out.activity.params.get("by") == "panel"


# ---------------------------------------------------------------- in an activity


async def run_activity(w, kind, params=None, **activity):
    """`loop.run_activity` on a World, as `_body` calls it: rows, `Jump`, `progress`."""
    s, latch = w.s, w.s.latch
    status = None
    try:
        with anyio.CancelScope() as latch.scope:
            async with anyio.create_task_group() as latch.tg:
                w.inputs.start()
                try:
                    with anyio.fail_after(10):
                        status = await loop.run_activity(s, w, Activity(kind, params or {}, "default", **activity))
                finally:
                    latch.tg.cancel_scope.cancel()
    except* Terminal:
        pass
    row = w.store.one("SELECT status, outcome FROM activities ORDER BY id DESC LIMIT 1")
    return status, row["status"], loads(row["outcome"], {})


class Hooked(ScriptedListener):
    """Runs `hooks[i]()` when it returns its i-th item (0-based)."""

    def __init__(self, script, hooks, *, block_at_end: bool = False):
        super().__init__(script)
        self.hooks, self.n, self.block_at_end = hooks, 0, block_at_end

    async def next_utterance(self, timeout_s):
        if self.block_at_end and not self.script:
            await anyio.sleep_forever()  # nothing more is typed (the default script ends with `/stop`)
        u = await super().next_utterance(timeout_s)
        if (hook := self.hooks.get(self.n)) is not None:
            hook()
        self.n += 1
        return u


def _quiz(w, n: int) -> dict:
    first = kinds.cycle_sentences(w.s)[0].rid
    return {"questions": [{"text": f"Question {i + 1}?", "type": "wh-", "answers": [["home"]], "item_ids": [],
                           "evidence": [first]} for i in range(n)]}


async def test_a_do_at_the_fourth_question_keeps_the_three_answered_for_the_ledger(settings):
    w = make_world(settings, settings, [*LINES, "home", "home", "home", "/do break"])
    await run(w, "read_listen", {"page": "current", "range": "rest"})
    status, stored, outcome = await run_activity(w, "quiz", content=_quiz(w, 4), content_owner="brain")
    assert status == stored == "completed"
    assert outcome == {"questions": 3, "results": ["correct"] * 3, "ended_by": "do"}
    assert w.s.ledger.cycle_quiz_left(w.s.cycle_id) == w.s.ledger.limits.quiz_max - 3
    assert w.s.latch.want.kind == "break"  # left for the boundary


async def test_a_want_during_feedback_ends_the_quiz_before_the_next_question_is_asked(settings):
    hooks = {}
    listener = Hooked([*LINES, "home", "home"], hooks)
    w = make_world(settings, settings, [], listener=listener)
    hooks[len(LINES)] = lambda: w.s.latch.post_want(_want())  # with the first answer: the panel pressed during it
    await run(w, "read_listen", {"page": "current", "range": "rest"})
    status, _, outcome = await run_activity(w, "quiz", content=_quiz(w, 3), content_owner="brain")
    assert status == "completed" and outcome == {"questions": 1, "results": ["correct"], "ended_by": "do"}
    assert not any(t.startswith("Question 2") for t in w.face.texts)  # never asked, then abandoned


async def test_a_do_mid_sentence_ends_reading_without_skipping_or_idling(settings):
    for voice, script in ((False, ["The fox ran", "/do break"]), (True, [None, "/do break"])):
        settings.data_dir = settings.data_dir.parent / f"voice-{voice}"
        w = make_world(settings, settings, [], listener=ScriptedListener(script, voice=voice))
        status, _, outcome = await run_activity(w, "read_listen", {"page": "current", "range": "rest"})
        assert status == "completed" and outcome["ended_by"] == "do" and outcome["sentences"] == 0
        assert w.state.completed == set() and w.s.latch.terminal is None  # no sentence skipped, no idle end


async def test_a_want_during_a_brain_answer_lets_the_call_and_its_answer_finish(settings):
    from leafi.services.brain.mock import MockModel
    from leafi.study.brain import call as bc

    hooks = {}
    listener = Hooked([*LINES, "why was it dark"], hooks, block_at_end=True)
    w = make_world(settings, settings, [], listener=listener)
    hooks[len(LINES)] = lambda: w.s.latch.post_want(_want())  # pressed while the question goes to the Brain
    await run(w, "read_listen", {"page": "current", "range": "rest"})
    model = MockModel({"answer": {"answer": "Because it was late at night.", "grounded": True}})
    w.s.brain = bc.Brain({"fast": [], "standard": [(model, "mock-model")], "deep": []},
                         locality=lambda backend, m: "local")
    status, _, outcome = await run_activity(w, "learner_questions", {"max_turns": 3})
    assert status == "completed" and outcome == {"questions": 1, "answered": 1, "ended_by": "do"}
    assert len(model.requests) == 1 and "Because it was late at night." in w.face.texts  # never cut


async def test_a_want_during_practice_scoring_keeps_the_attempt(settings):
    hooks = {}
    listener = Hooked(["The fax ran home.", "It was late and dark.", "box", "/stop"], hooks)
    w = make_world(settings, settings, [], listener=listener)
    hooks[2] = lambda: w.s.latch.post_want(_want())  # with the attempt "box"
    await run(w, "read_listen", {"page": "next"})
    mid = w.store.one("SELECT id FROM miscues WHERE expected='fox'")["id"]
    status, _, outcome = await run_activity(w, "practise_errors", {"candidate_ids": [mid]})
    assert status == "completed" and outcome["ended_by"] == "do"
    tries = [(r["attempt"], r["outcome"]) for r in w.store.all("SELECT attempt, outcome FROM practices")]
    assert tries == [(1, "disagreed")]  # the attempt is written; the retry prompt never came


async def test_an_unknown_kind_is_refused_and_the_reader_reads_on(settings):
    w = make_world(settings, settings, ["/do flying", *LINES])
    status, _, outcome = await run_activity(w, "read_listen", {"page": "current", "range": "rest"})
    assert status == "completed" and "ended_by" not in outcome and outcome["sentences"] == 2
    assert w.s.latch.want is None


# ---------------------------------------------------------------- Inputs


async def _inputs_case(settings, script, body):
    w = make_world(settings, settings, script)
    async with anyio.create_task_group() as tg:
        w.s.latch.tg = tg
        w.inputs.start()
        with anyio.fail_after(5):
            await body(w)
        tg.cancel_scope.cancel()
    return w


async def test_a_want_at_a_setup_prompt_waits_and_two_wakes_make_one_jump(settings):
    async def body(w):
        io = w.inputs
        await io._deliver(typed_utterance("/do quiz"), "main", time.monotonic())
        await io._deliver(typed_utterance("/do break"), "main", time.monotonic())
        u = await io.listen(None, ("setup", "name"))  # setup: the wakes are ignored, the want kept
        assert u.text == "Ada" and w.s.latch.want.kind == "break"
        w.s.latch.take_want()
        io.activity_started_at = time.monotonic()
        u = await io.listen(None, ("act", 1, "q0"))  # no want left: nothing jumps
        assert u.text == "home"

    await _inputs_case(settings, ["Ada", "home"], body)


async def test_lines_after_the_session_body_are_dropped(settings):
    async def body(w):
        w.inputs.accepting = False
        await w.inputs._deliver(typed_utterance("/do break"), "main", time.monotonic())
        await w.inputs._deliver(typed_utterance("home"), "main", time.monotonic())
        assert w.s.latch.want is None and w.inputs._recv.statistics().current_buffer_used == 0

    await _inputs_case(settings, [], body)


# ---------------------------------------------------------------- whole sessions


async def test_a_do_mid_reading_runs_the_break_and_its_row_says_who_chose_it(settings):
    e = hsess.env(settings, [None, "The fox ran", "/do break", "/stop"], learner="Ada")
    sid = await hsess.run(e)
    acts = e.store.all("SELECT kind, status, params, outcome FROM activities WHERE session_id=? ORDER BY id", (sid,))
    assert [(r["kind"], r["status"]) for r in acts] == [("read_listen", "completed"), ("break", "stopped")]
    assert loads(acts[0]["outcome"], {})["ended_by"] == "do"
    assert loads(acts[1]["params"], {})["by"] == "script"


async def test_a_want_skips_the_page_turn_continuation(settings):
    hooks = {}
    listener = Hooked([None, "The fox ran home.", "/next", "/stop"], hooks)
    e = hsess.env(settings, [], listener=listener, learner="Ada")
    e.on_built = lambda s, w: hooks.setdefault(2, lambda: s.latch.post_want(_want()))  # with "/next"
    sid = await hsess.run(e)
    kinds_run = [r["kind"] for r in e.store.all("SELECT kind FROM activities WHERE session_id=? ORDER BY id", (sid,))]
    assert kinds_run == ["read_listen", "break"]  # no continuation read of the next page
    assert e.store.one("SELECT COUNT(*) AS n FROM page_reads")["n"] == 1
