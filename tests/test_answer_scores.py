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


def test_a_multiword_item_needs_each_of_its_words():
    assert item_said(typed_utterance("look out"), "look out") == "success"
    assert item_said(typed_utterance("look"), "look out") == "fail"
