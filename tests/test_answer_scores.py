"""Answer scores (ADR-0017 §3.4 and Confirmation; M7 design D16)."""

from __future__ import annotations

from leafi.core.ports import Utterance, Word
from leafi.core.text import typed_utterance
from leafi.study.brain.scoring import cloze_word, item_said


def _spoken(text: str, conf: float) -> Utterance:
    return Utterance(text, [Word(w, conf=conf) for w in text.split()], typed=False)


def test_the_item_said_alone_or_in_a_frame_succeeds_but_not_inside_a_question():
    assert item_said(typed_utterance("through"), "through") == "success"
    assert item_said(typed_utterance("it's through"), "through") == "success"
    assert item_said(typed_utterance("I don't know what through means"), "through") == "fail"  # ADR-0017's case
    assert item_said(typed_utterance("thought"), "through") == "fail"


def test_a_low_confidence_spoken_answer_is_unavailable_whatever_it_says():
    assert item_said(_spoken("through", 0.6), "through") == "unavailable"  # ADR-0017's case
    assert item_said(_spoken("through", 0.95), "through") == "success"
    assert item_said(None, "through") == "unavailable" and item_said(typed_utterance("  "), "x") == "unavailable"


def test_a_cloze_answer_counts_by_exact_or_the_same_phones():
    assert cloze_word(typed_utterance("the fox"), "fox") == "success"
    assert cloze_word(typed_utterance("dog"), "fox") == "fail"
    assert cloze_word(_spoken("fox", 0.5), "fox") == "unavailable"


def _judged(tmp_path, reply, *, locality="local", mouth="camera"):
    from leafi.services.brain.mock import MockModel
    from leafi.study.brain import call as bc
    from tests.harness_helpers import make_session

    s = make_session(tmp_path)
    s.mouth = mouth  # the camera Mouth's feedback moment fits a `standard` call (PC: see the M7c hand-over)
    model = MockModel({"judge": reply})
    s.brain = bc.Brain({"fast": [], "standard": [(model, "mock-judge")], "deep": []},
                       locality=lambda backend, m: locality)
    return s, model


async def test_item_used_is_one_judge_call_and_cannot_tell_is_unavailable(tmp_path):
    from leafi.study.brain.scoring import item_used

    s, model = _judged(tmp_path, {"verdict": "yes"})
    assert await item_used(s, typed_utterance("The cat ran through the door."), "through", "Use it.") == "success"
    (req,) = model.requests
    assert req.purpose == "judge" and "Examples:" in req.system  # the fixed few-shot examples (D16)
    answer = next(sec for sec in req.turns[0].sections if sec.name == "answer").leaves[0]
    assert answer.prov.cls == "learner"
    s2, _ = _judged(tmp_path / "b", {"verdict": "cannot_tell"})
    assert await item_used(s2, typed_utterance("through it"), "through", "Use it.") == "unavailable"
    s3, _ = _judged(tmp_path / "c", {"verdict": "no"})
    assert await item_used(s3, typed_utterance("I threw it"), "through", "Use it.") == "fail"


async def test_item_used_without_an_eligible_backend_or_a_confident_answer_is_unavailable(tmp_path):
    from leafi.study.brain.scoring import item_used

    s, model = _judged(tmp_path, {"verdict": "yes"}, locality="cloud")  # a guest: cloud text never allowed
    s.learner_id = s.store.insert("learners", kind="guest", display_name="Guest", settings="{}",
                                  created_at="2026-10-24T00:00:00+00:00")
    assert await item_used(s, typed_utterance("The cat ran through the door."), "through", "Use it.") == \
        "unavailable"
    assert model.requests == []
    s2, model2 = _judged(tmp_path / "b", {"verdict": "yes"})
    assert await item_used(s2, _spoken("the cat ran through", 0.5), "through", "Use it.") == "unavailable"
    assert model2.requests == []  # an unconfident spoken answer is never sent


def test_a_multiword_item_needs_each_of_its_words():
    assert item_said(typed_utterance("look out"), "look out") == "success"
    assert item_said(typed_utterance("look"), "look out") == "fail"
