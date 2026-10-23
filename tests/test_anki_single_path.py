"""ADR-0017 §7.2: `add_cards` writes the card text into `anki_outbox`; `push` sends the stored fields. (The v1
writers `upsert_item`'s queued add and `_queue_update_if_pushed` go with the v1 session in M6f.)"""

from __future__ import annotations

from leafi.study import anki, knowledge
from tests.fakes.anki import FakeAnki
from tests.harness_world import make_world, run


def _explained(w, key: str, sentence: str) -> int:
    item = knowledge.upsert_item(w.store, w.s.learner_id, "word", key)
    w.store.execute("DELETE FROM anki_outbox WHERE knowledge_item_id=?", (item,))  # the v1 queued add (M6f)
    knowledge.add_encounter(w.store, item, session_id=w.s.session_id, trigger="explain", context_sentence=sentence,
                            explanation_en=f"meaning of {key}")
    return item


async def test_add_cards_stores_the_card_text_and_push_sends_exactly_it(settings):
    w = make_world(settings, settings, [])
    item = _explained(w, "fox", "The fox ran home.")
    assert w.facts().cardable_items == (item,)
    status, outcome, _ = await run(w, "add_cards", {"item_ids": [item]})
    assert status == "completed" and outcome["cards"] == 1
    row = w.store.one("SELECT op, state, front, back, sentence, card_provenance_class FROM anki_outbox "
                      "WHERE knowledge_item_id=?", (item,))
    assert (row["op"], row["state"], row["front"], row["sentence"]) == ("add", "pending", "fox", "The fox ran home.")
    assert row["card_provenance_class"] == "derived_from_learner"
    knowledge.add_encounter(w.store, item, session_id=w.s.session_id, trigger="explain",
                            context_sentence="The fox ran home.", explanation_en="CHANGED LATER")
    fake = FakeAnki()
    await anki.sync_outbox(w.store, anki.AnkiClient(transport=fake.transport()), "Leafi")
    (note,) = fake.notes.values()
    assert note["fields"]["正面"] == "fox" and "CHANGED LATER" not in note["fields"]["背面"]  # the stored text
    assert "leafi-check" not in note["tags"]
    assert w.facts().cardable_items == ()


async def test_a_flagged_card_is_sent_with_a_tag_the_learner_sees(settings):
    w = make_world(settings, settings, [])
    item = _explained(w, "fox", "The fox ran home.")
    knowledge.upsert_item(w.store, w.s.learner_id, "word", "home")  # a second unknown word in the sentence
    status, outcome, _ = await run(w, "add_cards", {"item_ids": [item]})
    assert outcome["flagged"] == [item]
    fake = FakeAnki()
    await anki.sync_outbox(w.store, anki.AnkiClient(transport=fake.transport()), "Leafi")
    tagged = [n for n in fake.notes.values() if n["fields"]["正面"] == "fox"]
    assert tagged and "leafi-check" in tagged[0]["tags"]


async def test_a_rejected_card_writes_nothing(settings):
    w = make_world(settings, settings, [])
    item = _explained(w, "badger", "The fox ran home.")
    status, outcome, _ = await run(w, "add_cards", {"item_ids": [item]})
    assert outcome == {"cards": 0, "flagged": [], "rejected": {item: "the item is not in the sentence"}}
    assert w.store.one("SELECT COUNT(*) AS n FROM anki_outbox WHERE front IS NOT NULL")["n"] == 0
