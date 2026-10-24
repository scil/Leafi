"""Quiz answerability and reference binding (ADR-0017 §3.1; M7 design D15): a question is kept only when its
evidence is a sentence read in this cycle and every keyword set is supported by what it cites."""

from __future__ import annotations

from leafi.study import knowledge
from leafi.study.brain import kinds
from leafi.study.brain.schemas import QuizContent
from leafi.study.harness.state import Rejected
from tests.harness_world import make_world, run


async def _read(settings):
    w = make_world(settings, settings, ["The fox ran home.", "It was late and dark.", "/stop"])
    await run(w, "read_listen", {"page": "current", "range": "rest"})
    return w


def _q(text="Where did the fox run?", type_="wh-", answers=(("home",),), evidence=None, items=()):
    return {"text": text, "type": type_, "answers": [list(a) for a in answers], "item_ids": list(items),
            "evidence": list(evidence or [])}


def _check(w, *questions):
    return kinds.quiz_check(w.s, {}, QuizContent.model_validate({"questions": list(questions)}))


async def test_only_sentences_read_in_this_cycle_are_rendered_and_citable(settings):
    w = await _read(settings)
    sent = kinds.cycle_sentences(w.s)
    assert [x.text for x in sent] == ["The fox ran home.", "It was late and dark."]
    first = sent[0].rid
    ok = _check(w, _q(evidence=[first, first]))  # a duplicate citation counts once
    assert ok["questions"][0]["evidence"] == ["The fox ran home."]
    assert _check(w, _q(evidence=["s999.1"])) == Rejected("no answerable question")  # never rendered


async def test_every_keyword_set_must_be_supported_by_the_cited_sentences(settings):
    w = await _read(settings)
    first, second = (x.rid for x in kinds.cycle_sentences(w.s))
    assert _check(w, _q(answers=[["home"], ["house"]], evidence=[first])) == Rejected("no answerable question")
    assert _check(w, _q(answers=[["dark"]], evidence=[first])) == Rejected("no answerable question")  # other line
    assert _check(w, _q(answers=[["dark"]], evidence=[second]))["questions"]
    assert _check(w, _q(answers=[["the"]], evidence=[first])) == Rejected("no answerable question")  # function word
    assert _check(w, _q(answers=[], evidence=[first])) == Rejected("no answerable question")  # wh- needs answers


async def test_open_questions_carry_no_answers_and_a_crowd_type(settings):
    w = await _read(settings)
    first = kinds.cycle_sentences(w.s)[0].rid
    assert _check(w, _q("Would you like a fox?", "distancing", answers=[], evidence=[first]))["questions"]
    assert _check(w, _q("Why?", "open-ended", answers=[["home"]], evidence=[first])) == \
        Rejected("no answerable question")


async def test_an_item_is_cited_only_when_its_key_is_in_the_question(settings):
    w = await _read(settings)
    first = kinds.cycle_sentences(w.s)[0].rid
    fox = knowledge.upsert_item(w.store, w.s.learner_id, "word", "fox")
    dark = knowledge.upsert_item(w.store, w.s.learner_id, "word", "dark")
    q = _check(w, _q(evidence=[first], items=[f"i{fox}", f"i{dark}", "i99999"]))["questions"][0]
    assert q["item_ids"] == [fox]  # dark is not in this question or its sentence; i99999 was never rendered


async def test_the_quiz_is_trimmed_to_the_cycles_allowance(settings):
    w = await _read(settings)
    first = kinds.cycle_sentences(w.s)[0].rid
    out = _check(w, *[_q(evidence=[first]) for _ in range(6)])
    assert len(out["questions"]) == w.s.ledger.cycle_quiz_left(w.s.cycle_id) == 4


async def test_a_corrected_page_read_is_no_longer_citable(settings):
    w = await _read(settings)
    from leafi.study import pages

    pages.add_manual_revision(w.store, w.page_id, "The fox ran home. It was late.")
    assert kinds.cycle_sentences(w.s) == []
