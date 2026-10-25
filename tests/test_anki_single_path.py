"""ADR-0017 §7.2: only `add_cards` writes the outbox; `push` sends the stored fields."""

from __future__ import annotations

from leafi.study import anki, knowledge
from tests.fakes.anki import FakeAnki
from tests.harness_world import make_world, run


def _explained(w, key: str, sentence: str) -> int:
    item = knowledge.upsert_item(w.store, w.s.learner_id, "word", key)
    knowledge.add_encounter(w.store, item, session_id=w.s.session_id, trigger="explain", context_sentence=sentence,
                            explanation_en=f"meaning of {key}")
    return item


async def test_add_cards_stores_the_card_text_and_push_sends_exactly_it(settings):
    w = make_world(settings, settings, [])
    item = _explained(w, "fox", "The fox ran home.")
    assert w.facts().cardable_items == (item,)
    status, outcome, _ = await run(w, "add_cards", {"item_ids": [item]})
    assert status == "completed" and outcome["cards"] == 1
    row = w.store.one("SELECT op, state, front, back, sentence FROM anki_outbox WHERE knowledge_item_id=?", (item,))
    assert (row["op"], row["state"], row["front"], row["sentence"]) == ("add", "pending", "fox", "The fox ran home.")
    knowledge.add_encounter(w.store, item, session_id=w.s.session_id, trigger="explain",
                            context_sentence="The fox ran home.", explanation_en="CHANGED LATER")
    fake = FakeAnki()
    await anki.sync_outbox(w.store, anki.AnkiClient(transport=fake.transport()), "Leafi")
    (note,) = fake.notes.values()
    assert note["fields"]["正面"] == "fox" and "CHANGED LATER" not in note["fields"]["背面"]  # the stored text
    assert "leafi-check" not in note["tags"]
    assert w.facts().cardable_items == ()


async def test_a_brain_owned_card_is_stored_once_and_push_sends_exactly_it(settings):
    """M7 design D15: Brain content reaches Anki only through `add_cards` and its checks, as stored."""
    w = make_world(settings, settings, [])
    item = _explained(w, "fox", "The fox ran home.")
    content = {"cards": {item: {"front": "fox", "back": "a small <b>wild</b> dog", "sentence": "The fox ran home."}}}
    status, outcome, _ = await run(w, "add_cards", {"item_ids": [item]}, content=content, content_owner="brain")
    assert outcome["cards"] == 1
    fake = FakeAnki()
    await anki.sync_outbox(w.store, anki.AnkiClient(transport=fake.transport()), "Leafi")
    (note,) = fake.notes.values()
    assert note["fields"]["背面"] == "a small &lt;b&gt;wild&lt;/b&gt; dog"  # escaped, never rendered as HTML
    long = {"cards": {item: {"front": "fox", "back": "x" * 199 + "&", "sentence": "The fox ran home."}}}
    w2 = make_world(settings, settings, [])
    item2 = _explained(w2, "fox", "The fox ran home.")
    long["cards"] = {item2: long["cards"][item]}
    _, out2, _ = await run(w2, "add_cards", {"item_ids": [item2]}, content=long, content_owner="brain")
    assert out2["rejected"] == {item2: "the back is over 200 characters"}  # checked after escaping


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


def test_an_item_or_an_explanation_queues_no_card_by_itself(settings):
    w = make_world(settings, settings, [])
    _explained(w, "fox", "The fox ran home.")
    assert w.store.one("SELECT COUNT(*) AS n FROM anki_outbox")["n"] == 0


async def test_a_rejected_card_writes_nothing(settings):
    w = make_world(settings, settings, [])
    item = _explained(w, "badger", "The fox ran home.")
    status, outcome, _ = await run(w, "add_cards", {"item_ids": [item]})
    assert outcome == {"cards": 0, "flagged": [], "rejected": {item: "the item is not in the sentence"}}
    assert w.store.one("SELECT COUNT(*) AS n FROM anki_outbox WHERE front IS NOT NULL")["n"] == 0
