"""Lexicon: rebuild keeps manual rows; corrections feed it; OCR snap is advisory (ADR-0011)."""

from __future__ import annotations

from leafi.core.storage import Store
from leafi.study import corrections, lexicon, pages
from tests import seed


def test_rebuild_keeps_manual_rows_and_counts_book_and_correction_words(tmp_path):
    store = Store(tmp_path / "leafi.db")
    book_id, page_id, rev = seed.book_page(store, "The wind blew though the trees.")
    lexicon.add_manual(store, "Hogwarts")
    span = corrections.locate("The wind blew though the trees.", "though")
    corrections.apply_correction(store, page_id=page_id, revision_id=rev, char_start=span[0], char_end=span[1],
                                 new_text="through", source="voice", learner_id=seed.learner(store))
    lexicon.rebuild(store, book_id)
    rows = {(r["word"], r["source"]): r["weight"] for r in store.all("SELECT * FROM lexicon")}
    assert rows[("hogwarts", "manual")] == 1.0
    assert rows[("the", "book")] == 2.0
    assert ("though", "book") not in rows  # the current revision no longer has it
    assert rows[("through", "correction")] == lexicon.CORRECTION_WEIGHT
    lexicon.rebuild(store, book_id)  # idempotent
    assert {(r["word"], r["source"]) for r in store.all("SELECT * FROM lexicon")} == set(rows)


def test_snap_candidates_are_advisory_and_only_for_low_confidence(tmp_path):
    store = Store(tmp_path / "leafi.db")
    book_id, _, _ = seed.book_page(store, "The wind blew through the trees.")
    lexicon.rebuild(store, book_id)
    assert lexicon.snap_candidates(store, "throigh", 0.4, 0.85, book_id) == ["through"]
    assert lexicon.snap_candidates(store, "throigh", 0.95, 0.85, book_id) == []
    assert lexicon.snap_candidates(store, "throigh", 0.4, 0.85, book_id, mode="off") == []
    assert lexicon.snap_candidates(store, "wind", 0.4, 0.85, book_id) == []
    assert pages.current_text(store, 1) == "The wind blew through the trees."  # never rewritten


def test_hotwords_stay_off_until_measured(tmp_path):
    store = Store(tmp_path / "leafi.db")
    book_id, _, _ = seed.book_page(store, "The wind blew.")
    lexicon.rebuild(store, book_id)
    assert lexicon.hotwords(store, book_id, "off") is None
    assert "wind" in lexicon.hotwords(store, book_id, "lexicon")
