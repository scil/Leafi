"""A panel line moves the session and never counts as the child's (ADR-0017 §3.4 as amended 2026-10-25; session
panel design D8): every site in D8's table. Real Store and Inputs, a scripted console whose panel lines are
`Utterance(source="panel")`; nothing speaks."""

from __future__ import annotations

import pytest

from leafi.core.ports import Utterance, Word
from leafi.core.storage import now_iso
from leafi.core.text import typed_utterance
from leafi.services.brain.mock import MockModel
from leafi.study import controls, knowledge, phrases
from leafi.study.brain import call as bc
from leafi.study.brain import kinds, scoring
from tests import seed
from tests.harness_world import make_world, run

LINES = ["The fox ran home.", "It was late and dark."]


def panel(text: str) -> Utterance:
    return typed_utterance(text, controls.PANEL)


def _count(w, sql: str) -> int:
    return w.store.one(f"SELECT COUNT(*) AS n FROM {sql}")["n"]


async def _read(settings, script, **kw):
    w = make_world(settings, settings, [*LINES, *script], **kw)
    await run(w, "read_listen", {"page": "current", "range": "rest"})
    return w


def _brain(w, replies) -> MockModel:
    model = MockModel(replies)
    w.s.brain = bc.Brain({"fast": [], "standard": [(model, "mock-model")], "deep": []},
                         locality=lambda backend, m: "local")
    return model


def _teach(w, key: str, expect: str, prompt: str) -> tuple[int, dict]:
    item = knowledge.upsert_item(w.store, w.s.learner_id, "word", key)
    return item, {"items": [{"item_id": item, "key": key, "method": "explain", "explanation": "A word.",
                             "prompt": prompt, "expect": expect, "sentence": "It was late and dark."}]}


# ---------------------------------------------------------------- the one predicate


def test_counts_as_answer_is_false_for_a_panel_line_and_for_a_voice_line_without_words():
    assert scoring.counts_as_answer(typed_utterance("home", "console"))
    assert not scoring.counts_as_answer(panel("home"))
    assert not scoring.counts_as_answer(Utterance("fox", [], typed=False))  # `all([])` no longer counts
    assert scoring.counts_as_answer(Utterance("fox", [Word("fox", conf=0.9)], typed=False))


def test_the_spoken_grammar_never_reads_a_panel_line():
    assert controls.of(panel("stop")) is None and controls.of(panel("good")) is None
    assert controls.of(panel("/stop")).kind == "stop"
    assert controls.of(typed_utterance("stop", "console")).kind == "stop"
    assert controls.parse_typed("/say it was dark").text == "it was dark"


# ---------------------------------------------------------------- scored answers


async def test_a_panel_quiz_answer_is_unavailable_and_a_panel_stop_is_an_answer(settings):
    w = await _read(settings, [panel("/say home"), panel("/say stop")])
    fox = knowledge.upsert_item(w.store, w.s.learner_id, "word", "fox")
    first = kinds.cycle_sentences(w.s)[0].rid
    q = {"type": "wh-", "answers": [["home"]], "item_ids": [fox], "evidence": [first]}
    content = {"questions": [{**q, "text": "Where did the fox run?"}, {**q, "text": "Where did it go?"}]}
    status, outcome, _ = await run(w, "quiz", {}, content=content, content_owner="brain")
    assert status == "completed" and outcome["results"] == ["unavailable", "unavailable"]
    assert w.s.latch.terminal is None  # "stop" typed on the panel as an answer stops nothing
    assert _count(w, "retrieval_events") == 0
    assert _count(w, "encounters WHERE trigger='check'") == 0


@pytest.mark.parametrize(("expect", "prompt", "answer"), [
    ("item_said", "Say the word.", "dark"),
    ("cloze_word", "It was late and ___.", "dark"),
    ("item_used", "Use it in a sentence.", "It was dark at night."),
])
async def test_panel_teach_answers_write_no_evidence_and_make_no_judge_call(settings, expect, prompt, answer):
    w = await _read(settings, [panel(f"/say {answer}")])
    model = _brain(w, {"judge": {"verdict": "yes"}})
    item, content = _teach(w, "dark", expect, prompt)
    status, outcome, _ = await run(w, "teach_items", {"item_ids": [item]}, content=content, content_owner="brain")
    assert status == "completed" and outcome["results"] == ["unavailable"]
    assert _count(w, "retrieval_events") == 0 and _count(w, "encounters WHERE trigger LIKE 'teach%'") == 0
    assert model.requests == []  # `item_used` never sends the owner's text as the child's


async def test_a_console_answer_still_counts_in_teaching(settings):
    w = await _read(settings, ["dark"])
    item, content = _teach(w, "dark", "item_said", "Say the word.")
    _, outcome, _ = await run(w, "teach_items", {"item_ids": [item]}, content=content, content_owner="brain")
    assert outcome["results"] == ["success"] and _count(w, "retrieval_events") == 1


async def test_a_panel_ease_goes_to_anki_with_no_retrieval_event(settings):
    from leafi.study import anki
    from tests.fakes.anki import FakeAnki

    fake = FakeAnki()
    w = make_world(settings, settings, [panel("/good"), "/say good", "/skip"],
                   anki=anki.AnkiClient(transport=fake.transport()))
    items = []
    for key in ("fox", "moon"):
        item = knowledge.upsert_item(w.store, w.s.learner_id, "word", key)
        seed.card(w.store, item)
        nid = fake.cards[fake.add_due_card(key)]["note"]
        w.store.execute("UPDATE anki_outbox SET state='acked', anki_note_id=?, updated_at=? WHERE knowledge_item_id=?",
                        (nid, now_iso(), item))
        items.append(item)
    await w.refresh()
    status, outcome, _ = await run(w, "review_anki", {"max_cards": 2})
    assert status == "completed" and outcome["cards"] == 2
    assert [r["ease"] for r in w.store.all("SELECT ease FROM review_answers ORDER BY id")] == [3, 3]
    # the panel's ease is the owner's judgement (owner, 2026-10-25): Anki has it, the evidence does not;
    # the console's `/say good` is the same as typing "good" and counts
    ev = [(r["item_id"], r["evidence"]) for r in w.store.all("SELECT item_id, evidence FROM retrieval_events")]
    assert ev == [(items[1], "typed")]


# ---------------------------------------------------------------- what is never the child's


async def test_learner_questions_refuses_a_panel_question_without_using_a_turn(settings):
    w = await _read(settings, [panel("/say why was it dark"), "why was it dark", "done"])
    model = _brain(w, {"answer": {"answer": "Because it was late at night.", "grounded": True}})
    status, outcome, _ = await run(w, "learner_questions", {"max_turns": 1})
    assert status == "completed" and outcome == {"questions": 1, "answered": 1}  # the child's, in the one turn
    (req,) = model.requests
    question = next(sec for sec in req.turns[0].sections if sec.name == "question")
    assert question.leaves[0].value == "why was it dark"
    shown = [(d.kind, d.text) for d in w.face.shown]
    assert ("status", phrases.say("questions_child_only")) in shown  # on Faces only, never spoken


async def test_a_panel_line_is_not_read_and_is_no_practice_attempt(settings):
    w = make_world(settings, settings, [panel("/say The fax ran home."), "The fax ran home.", "It was late and dark.",
                                        panel("/say fox"), "/skip"])
    await run(w, "read_listen", {"page": "next"})
    reading = [r["text"] for r in w.store.all("SELECT text FROM utterances WHERE kind='reading' ORDER BY id")]
    assert reading == ["The fax ran home.", "It was late and dark."]  # the panel line was never aligned
    mid = w.store.one("SELECT id FROM miscues WHERE expected='fox'")["id"]
    await run(w, "practise_errors", {"candidate_ids": [mid]})
    tries = [(r["attempt"], r["outcome"]) for r in w.store.all(
        "SELECT attempt, outcome FROM practices WHERE miscue_id=? ORDER BY attempt", (mid,))]
    assert tries == [(1, "skipped")]  # the panel "fox" was no attempt; the skip was


async def test_a_panel_explain_creates_no_item(settings):
    w = make_world(settings, settings, [panel("/explain fox"), *LINES])
    await run(w, "read_listen", {"page": "current", "range": "rest"})
    assert _count(w, "encounters WHERE trigger='explain'") == 0


async def test_a_panel_know_is_recorded_as_the_owners(settings):
    w = await _read(settings, [panel("/know")])
    item, content = _teach(w, "dark", "item_said", "Say the word.")
    _, outcome, _ = await run(w, "teach_items", {"item_ids": [item]}, content=content, content_owner="brain")
    assert outcome["results"] == ["known"]
    assert w.store.one("SELECT source FROM item_status_events")["source"] == "owner"


async def test_a_panel_fix_is_recorded_as_the_parents(settings):
    w = make_world(settings, settings, [panel("/fix fox box")])
    await run(w, "read_listen", {"page": "current", "range": "rest"})
    assert w.store.one("SELECT source FROM corrections")["source"] == "parent"
