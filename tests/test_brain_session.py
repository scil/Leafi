"""The Brain sequences a whole session (ADR-0017 §3.3, §9; M7 design D10, D13): a mock Brain on the port proposes
each activity; without an answer the default chain decides and the session stays in the Brain arm. Real Store,
scripted console, nothing speaks."""

from __future__ import annotations

import random

from leafi.services.brain.mock import MockModel
from leafi.study.brain import call as bc
from tests.harness_session import env, run, summary


def _turn(req) -> str:
    return next(leaf.value for s in req.turns[0].sections if s.name == "turn" for leaf in s.leaves)


def _read(req) -> dict:
    """Read on: the current page when the observation shows one, else the next page."""
    shown = any(s.name == "page" for s in req.turns[0].sections)
    return {"activity": {"kind": "read_listen", "page": "current" if shown else "next", "from_sentence": 0,
                         "to_sentence": 0},
            "has_alternative": False, "alternative": {"kind": "end"}, "say_before": "",
            "rationale": {"evidence": "a new page", "strategy": "Reading first keeps the story going.",
                          "intention": "fluency"}, "records": [], "turn": _turn(req)}


def _brain(replies) -> bc.Brain:
    model = MockModel(replies)
    return bc.Brain({"fast": [(model, "mock-decide")], "standard": [], "deep": []}), model


# random.Random(1).random() = 0.13 ≥ policy.explore_share 0.1, so these sessions are in the Brain arm (§9)


async def test_the_brain_proposes_the_activity_and_its_reason_is_offered(settings):
    brain, model = _brain({"decide": _read})
    e = env(settings, [None, "The fox ran home. It was late and dark.", "/stop"], learner="Ada", brain=brain,
            rng=random.Random(1))
    sid = await run(e)
    row = e.store.one("SELECT kind, decided_by, arm FROM activities WHERE session_id=? ORDER BY id LIMIT 1", (sid,))
    assert tuple(row) == ("read_listen", "brain", "brain")
    assert any("Reading first keeps the story going." in t for t in e.face.texts)  # D13: its own reason
    assert model.requests and model.requests[0].purpose == "decide"
    calls = e.store.all("SELECT purpose, outcome FROM brain_calls WHERE session_id=? AND purpose='decide'", (sid,))
    assert calls and all(tuple(c) == ("decide", "ok") for c in calls)
    assert summary(e.store, sid)["arm"] == "brain"
    # D18: after the session one `generate` for notes; this mock has no reply for it, so none are written
    notes = e.store.all("SELECT purpose FROM brain_calls WHERE session_id=? AND purpose='generate'", (sid,))
    assert notes and e.store.one("SELECT COUNT(*) AS n FROM learner_notes")["n"] == 0


async def test_without_an_answer_the_default_chain_decides_and_the_session_stays_in_the_brain_arm(settings):
    brain, _ = _brain({})  # no scripted reply: every decide fails
    e = env(settings, [None, "The fox ran home. It was late and dark.", "/stop"], learner="Ada", brain=brain,
            rng=random.Random(1))
    sid = await run(e)
    row = e.store.one("SELECT kind, decided_by, arm, override FROM activities WHERE session_id=? ORDER BY id LIMIT 1",
                      (sid,))
    assert tuple(row) == ("read_listen", "default", "brain", "brain_unavailable")  # §9: counts against the Brain
    assert e.store.one("SELECT COUNT(*) FROM brain_calls WHERE outcome='failed'")[0] >= 1


async def test_a_decision_echoing_another_turn_is_dropped(settings):
    def stale(req):
        return {**_read(req), "turn": "t-999"}

    brain, _ = _brain({"decide": stale})
    e = env(settings, [None, "The fox ran home. It was late and dark.", "/stop"], learner="Ada", brain=brain,
            rng=random.Random(1))
    sid = await run(e)
    row = e.store.one("SELECT decided_by, override FROM activities WHERE session_id=? ORDER BY id LIMIT 1", (sid,))
    assert tuple(row) == ("default", "brain_unavailable")
