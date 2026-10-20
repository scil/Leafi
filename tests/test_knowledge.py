"""Difficulty formulas (ADR-0013 → Difficulties), knowledge items, card builder."""

from __future__ import annotations

import pytest

from leafi.core.storage import Store
from leafi.study import knowledge
from tests import seed

TEXT = "The wind blew through the trees."


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "leafi.db")


def _miscue_in_new_session(store, book_id, page_id, rev, status, reason=None, days_ago=0.0, word="through"):
    s = seed.session(store, book_id, days_ago=days_ago)
    read = seed.page_read(store, s, page_id, rev)
    return seed.miscue(store, read, rev, TEXT, word, status=status, reason=reason)


def _rows(store):
    return {(r["miscue_key"], r["kind"]): r["weight"] for r in store.all("SELECT * FROM difficulties")}


def test_one_confirmed_session_creates_a_confirmed_difficulty(store):
    b, p, r = seed.book_page(store, TEXT)
    _miscue_in_new_session(store, b, p, r, "confirmed")
    knowledge.recompute_difficulties(store)
    assert _rows(store) == {("through", "confirmed"): pytest.approx(1.0, abs=1e-3)}


def test_unsure_needs_three_distinct_sessions_for_a_watch_row(store):
    b, p, r = seed.book_page(store, TEXT)
    for _ in range(2):
        _miscue_in_new_session(store, b, p, r, "unsure", "disagreed")
    knowledge.recompute_difficulties(store)
    assert _rows(store) == {}
    _miscue_in_new_session(store, b, p, r, "unsure", "skipped")
    knowledge.recompute_difficulties(store)
    assert _rows(store) == {("through", "watch"): pytest.approx(0.9, abs=1e-3)}


def test_once_a_row_exists_every_session_contributes_with_decay(store):
    b, p, r = seed.book_page(store, TEXT)
    _miscue_in_new_session(store, b, p, r, "confirmed", days_ago=30)
    _miscue_in_new_session(store, b, p, r, "unsure", "idle")
    knowledge.recompute_difficulties(store)
    assert _rows(store) == {("through", "confirmed"): pytest.approx(0.5 + 0.3, abs=1e-3)}


def test_withdrawn_and_invalidated_never_contribute(store):
    b, p, r = seed.book_page(store, TEXT)
    for status, reason in [("withdrawn", "practice"), ("invalidated", "page_text_corrected")] * 2:
        _miscue_in_new_session(store, b, p, r, status, reason)
    knowledge.recompute_difficulties(store)
    assert _rows(store) == {}


def test_knowledge_item_difficulty_needs_encounters_in_two_sessions(store):
    b, _, _ = seed.book_page(store, TEXT)
    item = knowledge.upsert_item(store, "word", "blew")
    s1 = seed.session(store, b)
    knowledge.add_encounter(store, item, session_id=s1, trigger="explain")
    knowledge.add_encounter(store, item, session_id=s1, trigger="explain")
    knowledge.recompute_difficulties(store)
    assert store.all("SELECT * FROM difficulties") == []
    s2 = seed.session(store, b)
    knowledge.add_encounter(store, item, session_id=s2, trigger="check")
    knowledge.recompute_difficulties(store)
    row = store.one("SELECT * FROM difficulties")
    assert (row["knowledge_item_id"], row["kind"]) == (item, "knowledge")
    assert row["weight"] == pytest.approx(2.0, abs=1e-3)


def test_practice_order_by_weight_then_position(store):
    b, p, r = seed.book_page(store, TEXT)
    _miscue_in_new_session(store, b, p, r, "confirmed", word="trees")
    knowledge.recompute_difficulties(store)
    assert knowledge.practice_order(store, [(1, "wind"), (5, "trees"), (3, "through")]) == [
        (5, "trees"), (1, "wind"), (3, "through")]


def test_items_are_unique_per_kind_language_key_sense_and_queue_an_anki_add(store):
    a = knowledge.upsert_item(store, "word", "bank", sense_hint="river")
    assert knowledge.upsert_item(store, "word", "bank", sense_hint="river") == a
    assert knowledge.upsert_item(store, "word", "bank", sense_hint="money") != a
    ops = store.all("SELECT op, state FROM anki_outbox WHERE knowledge_item_id=?", (a,))
    assert [(o["op"], o["state"]) for o in ops] == [("add", "pending")]


def test_card_fields_are_english_first(store):
    item = knowledge.upsert_item(store, "word", "blew")
    knowledge.add_encounter(store, item, session_id=None, trigger="explain", context_sentence=TEXT,
                            explanation_en="moved air (past of blow)", explanation_zh="吹(blow 的过去式)",
                            example="The wind blew hard.")
    f = knowledge.card_fields(store, item)
    assert f["正面"] == "blew"
    assert f["背面"].index("moved air") < f["背面"].index("吹")


def test_item_and_its_outbox_add_are_created_atomically(store):
    """Review 1 #16: a failure between the two inserts must not leave an unscheduled item."""
    import sqlite3

    def deny_outbox(action, table, *_):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_INSERT and table == "anki_outbox" else sqlite3.SQLITE_OK

    store.conn.set_authorizer(deny_outbox)
    with pytest.raises(sqlite3.DatabaseError):
        knowledge.upsert_item(store, "word", "blew")
    store.conn.set_authorizer(None)
    item = knowledge.upsert_item(store, "word", "blew")
    assert store.one("SELECT COUNT(*) AS n FROM knowledge_items")["n"] == 1
    assert store.one("SELECT COUNT(*) AS n FROM anki_outbox WHERE knowledge_item_id=?", (item,))["n"] == 1


def test_difficulties_follow_the_mutation_that_changed_their_evidence(store):
    """Review 1 #17: no explicit recompute — the status change / encounter write updates Difficulties."""
    b, p, r = seed.book_page(store, TEXT)
    for _ in range(3):
        s = seed.session(store, b)
        read = seed.page_read(store, s, p, r)
        seed.miscue(store, read, r, TEXT, "trees", status="unsure", reason="disagreed")
    assert _rows(store) == {("trees", "watch"): pytest.approx(0.9, abs=1e-3)}
    assert knowledge.practice_order(store, [(1, "wind"), (5, "trees")]) == [(5, "trees"), (1, "wind")]
    item = knowledge.upsert_item(store, "word", "blew")
    for _ in range(2):
        knowledge.add_encounter(store, item, session_id=seed.session(store, b), trigger="explain")
    assert store.one("SELECT kind FROM difficulties WHERE knowledge_item_id=?", (item,))["kind"] == "knowledge"
