"""Reading-evaluation scoring (plan M4.4a): false alarms on correct words, hits and misses on labelled errors."""

from __future__ import annotations

from leafi.core.wordinfo import TableWordInfo
from leafi.study.evaluation import Tally, score_utterance

INFO = TableWordInfo(words="the dog ran red cat sat on mat big".split())


def test_a_correct_reading_has_no_false_alarm():
    t = score_utterance("The dog ran.", ["correct"] * 3, ["the", "dog", "ran"], [0.9] * 3, INFO)
    assert (t.correct, t.false_alarms, t.errors) == (3, 0, 0)
    assert t.correct_content == 2  # "the" is a function word


def test_an_asr_slip_on_a_correct_word_is_a_false_alarm():
    t = score_utterance("The dog ran.", ["correct"] * 3, ["the", "dog", "red"], [0.9, 0.9, 0.95], INFO)
    assert (t.false_alarms, t.false_alarms_content) == (1, 1) and t.conf_false == [0.95]


def test_a_slip_heard_below_low_conf_is_observed_not_a_false_alarm():
    """LOW_CONF 0.9 (owner decision 2026-10-22): a substitution heard at 0.85 makes no candidate."""
    t = score_utterance("The dog ran.", ["correct"] * 3, ["the", "dog", "red"], [0.9, 0.9, 0.85], INFO)
    assert t.false_alarms == 0


def test_a_labelled_error_caught_is_a_hit_and_one_missed_is_a_miss():
    t = score_utterance("The big dog ran.", ["correct", "error", "correct", "correct"],
                        ["the", "bag", "dog", "ran"], [0.9] * 4, INFO)
    assert (t.errors, t.hits) == (1, 1)
    t2 = score_utterance("The big dog ran.", ["correct", "error", "correct", "correct"],
                         ["the", "big", "dog", "ran"], [0.9] * 4, INFO)
    assert (t2.errors, t2.hits, t2.miss_rate) == (1, 0, 1.0)


def test_excluded_words_count_nowhere_and_mismatched_labels_skip():
    t = score_utterance("The dog ran.", ["correct", "excluded", "correct"], ["the", "dig", "ran"], [0.9] * 3, INFO)
    assert (t.correct, t.false_alarms, t.errors) == (2, 0, 0)
    assert score_utterance("The dog ran.", ["correct"] * 2, ["the"], [0.9], INFO).skipped == 1


def test_tallies_add_and_rates():
    a = score_utterance("The dog ran.", ["correct"] * 3, ["the", "dog", "red"], [0.9] * 3, INFO)
    b = score_utterance("The cat sat.", ["correct"] * 3, ["the", "cat", "sat"], [0.9] * 3, INFO)
    total = Tally()
    total.add(a)
    total.add(b)
    assert total.utterances == 2 and total.false_alarm_rate == 1 / 4
