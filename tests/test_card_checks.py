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


def test_a_card_copying_an_explanation_keeps_every_learner_it_quoted(store):
    """M7 design D15 (rev 7 review #6): a `code`-built card copies the encounter's explanation; when that was
    written from another learner's text, the card names that learner too, so the fence and `forget` reach it."""
    from leafi.core import learner_store

    learner, item = _item(store, "fox")
    other = learner_store.create(store, "Ben")
    store.execute("UPDATE encounters SET explanation_source_learners=? WHERE knowledge_item_id=?",
                  (f"[{learner}, {other}]", item))
    _, _, prov = cards.stored_text(store, item)
    assert prov.cls == "derived_from_learner" and prov.sources == tuple(sorted((learner, other)))


def test_pass_when_the_item_is_in_the_sentence(store):
    learner, item = _item(store, "fox")
    fields, sentence, _ = cards.stored_text(store, item)
    assert cards.check(store, learner, item, fields, sentence) == ("pass", "")


def test_reject_when_the_item_is_not_in_the_sentence(store):
    learner, item = _item(store, "badger")
    fields, sentence, _ = cards.stored_text(store, item)
    assert cards.check(store, learner, item, fields, sentence)[0] == "reject"


def test_reject_a_long_back(store):
    learner, item = _item(store, "fox", explanation="x" * 250)
    fields, sentence, _ = cards.stored_text(store, item)
    assert cards.check(store, learner, item, fields, sentence) == ("reject", "the back is over 200 characters")


def test_flag_a_second_unknown_word_in_the_sentence(store):
    learner, item = _item(store, "fox")
    knowledge.upsert_item(store, learner, "word", "home")
    fields, sentence, _ = cards.stored_text(store, item)
    assert cards.check(store, learner, item, fields, sentence)[0] == "flag"


def test_reject_a_duplicate_for_this_learner(store):
    learner, item = _item(store, "fox")
    other = knowledge.upsert_item(store, learner, "phrase", "fox")
    store.execute("UPDATE anki_outbox SET front='fox' WHERE id=?", (seed.card(store, other),))
    fields, sentence, _ = cards.stored_text(store, item)
    assert cards.check(store, learner, item, fields, sentence) == ("reject", "a card for this word already exists")
