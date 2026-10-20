"""Anki outbox and review answers against a stateful fake AnkiConnect (ADR-0004 as amended)."""

from __future__ import annotations

import pytest

from leafi.core.storage import Store, loads
from leafi.study import anki, knowledge
from tests.fakes.anki import FakeAnki


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "leafi.db")


def _item(store, key="blew"):
    item = knowledge.upsert_item(store, "word", key)
    knowledge.add_encounter(store, item, session_id=None, trigger="explain", explanation_en="moved air",
                            explanation_zh="吹", example="The wind blew.")
    return item


def _client(fake):
    return anki.AnkiClient(transport=fake.transport())


async def test_push_creates_note_with_leafi_id_tag_and_acks(store):
    fake = FakeAnki()
    item = _item(store)
    rep = await anki.sync_outbox(store, _client(fake))
    assert rep.acked == 1
    (nid, note), = fake.notes.items()
    key = store.one("SELECT anki_item_key FROM knowledge_items WHERE id=?", (item,))["anki_item_key"]
    assert f"leafi-id::{key}" in note["tags"] and note["deck"] == "Leafi" and note["model"] == "问答题"
    row = store.one("SELECT * FROM anki_outbox WHERE knowledge_item_id=?", (item,))
    assert row["state"] == "acked" and row["anki_note_id"] == nid and loads(row["card_ids"])
    assert "anki_note_id" not in store.one("SELECT * FROM knowledge_items").keys()


async def test_idempotent_re_push(store):
    fake = FakeAnki()
    _item(store)
    await anki.sync_outbox(store, _client(fake))
    await anki.sync_outbox(store, _client(fake))
    assert len(fake.notes) == 1


async def test_lost_ack_no_duplicate(store):
    fake = FakeAnki()
    item = _item(store)
    fake.lose_next.add("addNote")  # Anki creates the note, the response never arrives
    rep1 = await anki.sync_outbox(store, _client(fake))
    assert rep1.pending == 1
    assert store.one("SELECT state FROM anki_outbox WHERE knowledge_item_id=?", (item,))["state"] == "pending"
    rep2 = await anki.sync_outbox(store, _client(fake))
    assert rep2.deduped == 1 and len(fake.notes) == 1
    assert fake.actions().count("addNote") == 1


async def test_queue_when_anki_is_closed(store):
    fake = FakeAnki()
    fake.down = True
    _item(store)
    rep = await anki.sync_outbox(store, _client(fake))
    assert rep.pending == 1 and fake.notes == {}
    fake.down = False
    assert (await anki.sync_outbox(store, _client(fake))).acked == 1


async def test_parent_edits_win_on_update(store):
    fake = FakeAnki()
    item = _item(store)
    await anki.sync_outbox(store, _client(fake))
    nid = next(iter(fake.notes))
    fake.parent_edit(nid, "背面", "parent's own wording")
    knowledge.add_encounter(store, item, session_id=None, trigger="explain", explanation_en="pushed air",
                            explanation_zh="吹动", example="It blew away.")
    rep = await anki.sync_outbox(store, _client(fake))
    assert fake.notes[nid]["fields"]["背面"] == "parent's own wording"
    assert rep.conflicts and "背面" in rep.conflicts[0]


async def test_update_touches_unedited_fields(store):
    fake = FakeAnki()
    item = knowledge.upsert_item(store, "word", "blew")
    await anki.sync_outbox(store, _client(fake))
    nid = next(iter(fake.notes))
    knowledge.add_encounter(store, item, session_id=None, trigger="explain", explanation_en="moved air")
    await anki.sync_outbox(store, _client(fake))
    assert fake.notes[nid]["fields"]["背面"] == "moved air"


async def test_due_cards_and_answer_ack(store):
    fake = FakeAnki()
    item = _item(store)
    await anki.sync_outbox(store, _client(fake))
    nid = next(iter(fake.notes))
    cid = fake.add_due_card("", note_id=nid)
    due = await anki.due_cards(store, _client(fake))
    assert [(d.card_id, d.knowledge_item_id, d.front) for d in due] == [(cid, item, "blew")]
    assert await anki.answer(store, _client(fake), due[0], 3) == "acked"
    assert store.one("SELECT status FROM knowledge_items WHERE id=?", (item,))["status"] == "learning"


async def test_sent_review_answer_is_never_replayed_and_reconciles(store):
    fake = FakeAnki()
    cid = fake.add_due_card("blew")
    due = await anki.due_cards(store, _client(fake))
    fake.lose_next.add("answerCards")
    assert await anki.answer(store, _client(fake), due[0], 1) == "sent"
    await anki.sync_outbox(store, _client(fake))  # nothing replays answers
    assert fake.actions().count("answerCards") == 1
    assert await anki.reconcile(store, _client(fake)) == []
    assert store.one("SELECT state FROM review_answers WHERE card_id=?", (cid,))["state"] == "acked"


async def test_unreconciled_sent_answer_is_listed_for_the_parent(store):
    fake = FakeAnki()
    cid = fake.add_due_card("blew")
    due = await anki.due_cards(store, _client(fake))
    fake.down = True
    assert await anki.answer(store, _client(fake), due[0], 3) == "sent"
    fake.down = False
    unknown = await anki.reconcile(store, _client(fake))
    assert len(unknown) == 1
    assert store.one("SELECT state FROM review_answers WHERE card_id=?", (cid,))["state"] == "sent"


async def test_lost_add_recovery_does_not_adopt_parent_edits_as_leafi_values(store):
    """Review 1 #4: the parent edits the note between the lost add and the dedupe; the edit must survive."""
    fake = FakeAnki()
    item = _item(store)
    fake.lose_next.add("addNote")
    await anki.sync_outbox(store, _client(fake))
    nid = next(iter(fake.notes))
    fake.parent_edit(nid, "背面", "parent's own wording")
    assert (await anki.sync_outbox(store, _client(fake))).deduped == 1
    knowledge.add_encounter(store, item, session_id=None, trigger="explain", explanation_en="pushed air",
                            explanation_zh="吹动", example="It blew away.")
    rep = await anki.sync_outbox(store, _client(fake))
    assert fake.notes[nid]["fields"]["背面"] == "parent's own wording"
    assert rep.conflicts


async def test_reconciled_review_applies_the_knowledge_status_transition(store):
    """Review 1 #18: a lost first-review response, once reconciled, moves the item new → learning."""
    fake = FakeAnki()
    item = _item(store)
    await anki.sync_outbox(store, _client(fake))
    fake.add_due_card("", note_id=next(iter(fake.notes)))
    (card,) = await anki.due_cards(store, _client(fake))
    fake.lose_next.add("answerCards")
    assert await anki.answer(store, _client(fake), card, 3) == "sent"
    assert store.one("SELECT status FROM knowledge_items WHERE id=?", (item,))["status"] == "new"
    assert await anki.reconcile(store, _client(fake)) == []
    assert store.one("SELECT status FROM knowledge_items WHERE id=?", (item,))["status"] == "learning"
    await anki.reconcile(store, _client(fake))  # idempotent
    assert store.one("SELECT status FROM knowledge_items WHERE id=?", (item,))["status"] == "learning"
