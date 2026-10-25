"""Anki outbox and review answers against a stateful fake AnkiConnect (ADR-0004 as amended)."""

from __future__ import annotations

import pytest

from leafi.core.storage import Store, loads
from leafi.study import anki, knowledge
from tests import seed
from tests.fakes.anki import FakeAnki


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "leafi.db")


def _item(store, key="blew"):
    item = knowledge.upsert_item(store, seed.learner(store), "word", key)
    knowledge.add_encounter(store, item, session_id=None, trigger="explain", explanation_en="moved air",
                            explanation_zh="吹", example="The wind blew.")
    seed.card(store, item)  # what `add_cards` queues
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
    assert f"leafi-id::{key}" in note["tags"] and note["deck"] == "Leafi Learner #1" and note["model"] == "问答题"
    row = store.one("SELECT * FROM anki_outbox WHERE knowledge_item_id=?", (item,))
    assert row["state"] == "acked" and row["anki_note_id"] == nid and loads(row["card_ids"])
    assert "anki_note_id" not in store.one("SELECT * FROM knowledge_items").keys()


async def test_a_learner_being_forgotten_is_not_synced(store):
    """ADR-0021 E9 (X4): another learner's `deliver` runs the sync; a forgetting learner's rows are skipped."""
    fake = FakeAnki()
    item = _item(store)
    store.execute("UPDATE learners SET forgetting=1")
    rep = await anki.sync_outbox(store, _client(fake))
    assert rep.acked == 0 and fake.notes == {}
    assert store.one("SELECT state FROM anki_outbox WHERE knowledge_item_id=?", (item,))["state"] == "pending"


async def test_a_note_added_while_its_row_was_forgotten_is_listed_for_removal(store, monkeypatch):
    """Y4: `forget` deletes the outbox row while `addNote` is awaited; the note id is listed for the household."""
    from leafi.core import learner_store

    fake = FakeAnki()
    item = _item(store)
    learner = store.one("SELECT learner_id FROM knowledge_items WHERE id=?", (item,))["learner_id"]
    real = anki.AnkiClient.invoke

    async def invoke(self, action, **params):
        out = await real(self, action, **params)
        if action == "addNote":  # forget runs here: marks the learner and deletes the outbox row
            store.execute("UPDATE learners SET forgetting=1 WHERE id=?", (learner,))
            store.execute("DELETE FROM anki_outbox WHERE learner_id=?", (learner,))
        return out

    monkeypatch.setattr(anki.AnkiClient, "invoke", invoke)
    await anki.sync_outbox(store, _client(fake))
    (nid,) = fake.notes
    assert loads(learner_store.get(store, learner)["settings"])["forget.anki_notes"] == [nid]


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
    seed.card(store, item, "update")
    rep = await anki.sync_outbox(store, _client(fake))
    assert fake.notes[nid]["fields"]["背面"] == "parent's own wording"
    assert rep.conflicts and "背面" in rep.conflicts[0]


async def test_update_touches_unedited_fields(store):
    fake = FakeAnki()
    item = knowledge.upsert_item(store, seed.learner(store), "word", "blew")
    seed.card(store, item)
    await anki.sync_outbox(store, _client(fake))
    nid = next(iter(fake.notes))
    knowledge.add_encounter(store, item, session_id=None, trigger="explain", explanation_en="moved air")
    seed.card(store, item, "update")
    await anki.sync_outbox(store, _client(fake))
    assert fake.notes[nid]["fields"]["背面"] == "moved air"


async def test_due_cards_and_answer_ack(store):
    fake = FakeAnki()
    item = _item(store)
    await anki.sync_outbox(store, _client(fake))
    nid = next(iter(fake.notes))
    cid = fake.add_due_card("", note_id=nid)
    due = await anki.due_cards(store, _client(fake), seed.learner(store))
    assert [(d.card_id, d.knowledge_item_id, d.front) for d in due] == [(cid, item, "blew")]
    assert await anki.answer(store, _client(fake), seed.learner(store), due[0], 3) == "acked"
    assert store.one("SELECT status FROM knowledge_items WHERE id=?", (item,))["status"] == "learning"


async def test_sent_review_answer_is_never_replayed_and_reconciles(store):
    fake = FakeAnki()
    cid = fake.add_due_card("blew")
    due = await anki.due_cards(store, _client(fake), seed.learner(store))
    fake.lose_next.add("answerCards")
    assert await anki.answer(store, _client(fake), seed.learner(store), due[0], 1) == "sent"
    await anki.sync_outbox(store, _client(fake))  # nothing replays answers
    assert fake.actions().count("answerCards") == 1
    assert await anki.reconcile(store, _client(fake)) == []
    assert store.one("SELECT state FROM review_answers WHERE card_id=?", (cid,))["state"] == "acked"


async def test_unreconciled_sent_answer_is_listed_for_the_parent(store):
    fake = FakeAnki()
    cid = fake.add_due_card("blew")
    due = await anki.due_cards(store, _client(fake), seed.learner(store))
    fake.down = True
    assert await anki.answer(store, _client(fake), seed.learner(store), due[0], 3) == "sent"
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
    seed.card(store, item, "update")
    rep = await anki.sync_outbox(store, _client(fake))
    assert fake.notes[nid]["fields"]["背面"] == "parent's own wording"
    assert rep.conflicts


def _status(store, item):
    return store.one("SELECT status FROM knowledge_items WHERE id=?", (item,))["status"]


def _events(store, item):
    return [(r["event"], r["card_id"], r["ivl_days"], r["lapses"], r["session_id"]) for r in store.all(
        "SELECT * FROM item_status_events WHERE item_id=? ORDER BY id", (item,))]


async def test_reconciled_review_records_the_card_state_once(store):
    """Review 1 #18, as a fold (M7 design D17): the acknowledged card makes the item `learning`; a lost answer,
    once reconciled, records the card's state once, session-less."""
    fake = FakeAnki()
    item = _item(store)
    await anki.sync_outbox(store, _client(fake))
    cid = fake.add_due_card("", note_id=next(iter(fake.notes)), interval=10)
    assert _status(store, item) == "learning" and _events(store, item) == [("card_ack", cid, None, None, None)]
    (card,) = await anki.due_cards(store, _client(fake), seed.learner(store))
    fake.lose_next.add("answerCards")
    assert await anki.answer(store, _client(fake), seed.learner(store), card, 3) == "sent"
    assert len(_events(store, item)) == 1
    assert await anki.reconcile(store, _client(fake)) == []
    assert _events(store, item)[1:] == [("card_state", cid, 25.0, 0, None)]
    assert _status(store, item) == "known"  # 25 days ≥ REVIEW_KNOWN_INTERVAL_DAYS
    await anki.reconcile(store, _client(fake))  # idempotent
    assert len(_events(store, item)) == 2


async def test_an_answer_moves_the_item_with_its_card_known_then_lapsed(store):
    fake = FakeAnki()
    item = _item(store)
    await anki.sync_outbox(store, _client(fake))
    nid = next(iter(fake.notes))
    fake.add_due_card("", note_id=nid, interval=10)
    (card,) = await anki.due_cards(store, _client(fake), seed.learner(store))
    assert await anki.answer(store, _client(fake), seed.learner(store), card, 3) == "acked"
    assert _status(store, item) == "known"
    fake.add_due_card("", note_id=nid)
    (card,) = await anki.due_cards(store, _client(fake), seed.learner(store))
    assert await anki.answer(store, _client(fake), seed.learner(store), card, 1) == "acked"
    assert _status(store, item) == "lapsed"  # the same card was known and its lapses grew


async def test_observe_cards_sees_changes_made_in_anki_a_deleted_and_a_restored_card(store):
    fake = FakeAnki()
    item = _item(store)
    await anki.sync_outbox(store, _client(fake))
    cid = next(iter(fake.cards))
    learner = seed.learner(store)
    assert await anki.observe_cards(store, _client(fake), learner) == 1  # first state of the card
    assert await anki.observe_cards(store, _client(fake), learner) == 0  # unchanged: nothing written
    fake.set_card(cid, interval=30)  # reviewed in Anki itself
    assert await anki.observe_cards(store, _client(fake), learner) == 1 and _status(store, item) == "known"
    saved = fake.delete_card(cid)  # cardsInfo now answers with an empty entry
    assert await anki.observe_cards(store, _client(fake), learner) == 1 and _status(store, item) == "new"
    assert await anki.observe_cards(store, _client(fake), learner) == 0  # already gone
    fake.cards[cid] = saved  # restored in Anki
    assert await anki.observe_cards(store, _client(fake), learner) == 1 and _status(store, item) == "known"
    assert [e[0] for e in _events(store, item)] == ["card_ack", "card_state", "card_state", "card_gone",
                                                    "card_state"]


async def test_observe_cards_writes_nothing_when_anki_is_closed(store):
    fake = FakeAnki()
    item = _item(store)
    await anki.sync_outbox(store, _client(fake))
    fake.down = True
    with pytest.raises(anki.AnkiUnavailable):
        await anki.observe_cards(store, _client(fake), seed.learner(store))
    assert [e[0] for e in _events(store, item)] == ["card_ack"]


async def test_reconcile_skips_a_learner_being_forgotten_and_others_still_reconcile(store):
    """Round 10 #2: a marked learner's `sent` answer is not read, so another learner's boundary never meets a
    refused `card_state`."""
    fake = FakeAnki()
    mia = seed.learner(store)
    leo = store.insert("learners", kind="learner", display_name="Leo", created_at="t")
    for who in (mia, leo):
        cid = fake.add_due_card(f"word {who}")
        card = anki.DueCard(cid, None, "", 3)
        fake.lose_next.add("answerCards")
        assert await anki.answer(store, _client(fake), who, card, 3) == "sent"
    store.execute("UPDATE learners SET forgetting=1 WHERE id=?", (mia,))
    assert await anki.reconcile(store, _client(fake)) == []
    states = dict(store.all("SELECT learner_id, state FROM review_answers"))
    assert states == {mia: "sent", leo: "acked"}


async def test_a_learner_marked_between_the_claim_and_the_ack_keeps_the_note_id(store):
    """Round 10 #3: the `card_ack` is written after the outbox acknowledgement, so its refusal loses nothing."""
    fake = FakeAnki()
    item = _item(store)
    learner = seed.learner(store)
    real = fake.handle

    def mark_during_add(request):
        response = real(request)
        if b'"addNote"' in request.content:
            store.execute("UPDATE learners SET forgetting=1 WHERE id=?", (learner,))
        return response

    fake.handle = mark_during_add
    rep = await anki.sync_outbox(store, _client(fake))
    assert rep.acked == 1
    row = store.one("SELECT state, anki_note_id FROM anki_outbox WHERE knowledge_item_id=?", (item,))
    assert row["state"] == "acked" and row["anki_note_id"] == next(iter(fake.notes))
    assert _events(store, item) == []  # refused and logged, not raised
