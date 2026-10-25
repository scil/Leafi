"""ADR-0017 §7.2 card checks: pass / flag / reject."""

from __future__ import annotations

import pytest

from leafi.core.storage import Store
from leafi.study import cards, knowledge
from tests import seed


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "leafi.db")


def _item(store, key, sentence="The fox ran home.", explanation="a wild animal"):
    learner = seed.learner(store)
    item = knowledge.upsert_item(store, learner, "word", key)
    knowledge.add_encounter(store, item, session_id=None, trigger="explain", context_sentence=sentence,
                            explanation_en=explanation)
    return learner, item


def test_a_card_copies_the_explanation_and_the_latest_context_sentence(store):
    """ADR-0021 E9: no source learners are kept with a card; it copies the explanation and the context."""
    learner, item = _item(store, "fox")
    fields, sentence = cards.stored_text(store, item)
    assert sentence == "The fox ran home." and "a wild animal" in fields["背面"]


def test_pass_when_the_item_is_in_the_sentence(store):
    learner, item = _item(store, "fox")
    fields, sentence = cards.stored_text(store, item)
    assert cards.check(store, learner, item, fields, sentence) == ("pass", "")


def test_reject_when_the_item_is_not_in_the_sentence(store):
    learner, item = _item(store, "badger")
    fields, sentence = cards.stored_text(store, item)
    assert cards.check(store, learner, item, fields, sentence)[0] == "reject"


def test_reject_a_long_back(store):
    learner, item = _item(store, "fox", explanation="x" * 250)
    fields, sentence = cards.stored_text(store, item)
    assert cards.check(store, learner, item, fields, sentence) == ("reject", "the back is over 200 characters")


def test_flag_a_second_unknown_word_in_the_sentence(store):
    learner, item = _item(store, "fox")
    knowledge.upsert_item(store, learner, "word", "home")
    fields, sentence = cards.stored_text(store, item)
    assert cards.check(store, learner, item, fields, sentence)[0] == "flag"


def test_reject_a_duplicate_for_this_learner(store):
    learner, item = _item(store, "fox")
    other = knowledge.upsert_item(store, learner, "phrase", "fox")
    store.execute("UPDATE anki_outbox SET front='fox' WHERE id=?", (seed.card(store, other),))
    fields, sentence = cards.stored_text(store, item)
    assert cards.check(store, learner, item, fields, sentence) == ("reject", "a card for this word already exists")
