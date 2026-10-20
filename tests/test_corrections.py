"""Corrections and page revisions (ADR-0010, ADR-0013 → Correction interaction). Never mocked."""

from __future__ import annotations

import pytest

from leafi.core.storage import Store, loads
from leafi.study import corrections, lexicon, pages
from leafi.study.alignment import ReadingState, align, complete_sentence
from tests import seed

TEXT = "The wind blew though the trees. The boy ran home."


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "leafi.db")


def _correct(store, page_id, rev, old="though", new="through", state=None):
    text = pages.current_text(store, page_id)
    span = corrections.locate(text, old, near=0)
    return corrections.apply_correction(store, page_id=page_id, revision_id=rev, char_start=span[0],
                                        char_end=span[1], new_text=new, source="text", state=state)


def test_correction_creates_a_revision_chain_with_edit_map_and_verified_span(store):
    _, page_id, rev1 = seed.book_page(store, TEXT)
    res = _correct(store, page_id, rev1)
    assert pages.current_text(store, page_id) == "The wind blew through the trees. The boy ran home."
    chain = pages.chain(store, page_id)
    assert [r.rev for r in chain] == [1, 2]
    assert [r.source for r in chain] == ["ocr", "correction"]
    assert chain[1].edit_map == [[14, 20, 14, 21]]
    assert chain[1].spans_verified == [[14, 21]]
    assert chain[1].tokenizer_version == "1"
    corr = store.one("SELECT * FROM corrections WHERE id=?", (res.correction_id,))
    assert (corr["page_revision_id"], corr["char_start"], corr["char_end"]) == (rev1, 14, 20)
    assert (corr["old_text"], corr["new_text"]) == ("though", "through")


def test_corrected_text_wins_and_verified_spans_survive_re_ocr(store):
    _, page_id, rev1 = seed.book_page(store, TEXT)
    _correct(store, page_id, rev1)
    # a later OCR misreads the corrected word again and fixes "boy" → "bay" elsewhere
    rev3 = pages.add_ocr_revision(store, page_id, "The wind blew though the trees. The bay ran home.", "mock", 0.8)
    assert rev3 is not None
    text = pages.current_text(store, page_id)
    assert "through" in text and "though " not in text
    assert "bay" in text  # unverified span took the new OCR
    assert pages.add_ocr_revision(store, page_id, text, "mock", 0.8) is None  # nothing changed


def test_manual_revision_is_fully_verified_and_reused_when_identical(store):
    _, page_id, rev = seed.book_page(store, TEXT, source="manual")
    r = pages.revision(store, rev)
    assert r.source == "manual" and r.spans_verified == [[0, len(TEXT)]]
    assert pages.add_manual_revision(store, page_id, TEXT) == rev
    assert pages.add_ocr_revision(store, page_id, TEXT.replace("boy", "bay"), "mock", 0.5) is None


def test_overlapping_miscues_of_any_revision_are_invalidated_with_reason(store):
    book_id, page_id, rev1 = seed.book_page(store, TEXT)
    s = seed.session(store, book_id)
    read = seed.page_read(store, s, page_id, rev1)
    cand = seed.miscue(store, read, rev1, TEXT, "though")
    unsure = seed.miscue(store, read, rev1, TEXT, "though", status="unsure", reason="disagreed")
    withdrawn = seed.miscue(store, read, rev1, TEXT, "though", status="withdrawn", reason="practice")
    other = seed.miscue(store, read, rev1, TEXT, "boy")
    # a first correction elsewhere shifts offsets (rev 2), then the second one hits rev-1 miscues via the chain
    span = corrections.locate(TEXT, "wind", near=0)
    corrections.apply_correction(store, page_id=page_id, revision_id=rev1, char_start=span[0], char_end=span[1],
                                 new_text="cold wind", source="text")
    rev2 = pages.current_revision(store, page_id).id
    res = _correct(store, page_id, rev2)
    assert sorted(res.invalidated) == sorted([cand, unsure])
    assert seed.status_of(store, cand) == ("invalidated", "page_text_corrected")
    assert seed.status_of(store, unsure) == ("invalidated", "page_text_corrected")
    assert seed.status_of(store, withdrawn) == ("withdrawn", "practice")
    assert seed.status_of(store, other) == ("candidate", None)
    # older assessments keep their original coordinates
    row = store.one("SELECT expected_char_span, page_revision_id FROM miscues WHERE id=?", (cand,))
    assert loads(row["expected_char_span"]) == [14, 20] and row["page_revision_id"] == rev1


def test_rollback_when_the_revision_insert_fails(store, monkeypatch):
    _, page_id, rev1 = seed.book_page(store, TEXT)

    def boom(*a, **k):
        raise RuntimeError("crash between correction insert and revision insert")

    monkeypatch.setattr(pages, "insert_revision", boom)
    with pytest.raises(RuntimeError):
        _correct(store, page_id, rev1)
    assert store.one("SELECT COUNT(*) AS n FROM corrections")["n"] == 0
    assert [r.rev for r in pages.chain(store, page_id)] == [1]
    assert pages.current_text(store, page_id) == TEXT


def test_stale_revision_is_refused(store):
    _, page_id, rev1 = seed.book_page(store, TEXT)
    _correct(store, page_id, rev1)
    with pytest.raises(corrections.StaleRevision):
        _correct(store, page_id, rev1, old="boy", new="girl")


def test_reading_state_is_retokenised_and_cursors_clamped(store):
    _, page_id, rev1 = seed.book_page(store, TEXT)
    st = ReadingState.from_text(TEXT, revision_id=rev1)
    st, _, ev = align(st, "The wind blew though the trees".split(), 1)
    st, _ = complete_sentence(st, 1)
    st, _, _ = align(st, "The boy".split(), 2)
    assert st.statuses() == "C C C C C C P P U U" and st.completed == {1}
    res = _correct(store, page_id, rev1, state=st)
    new = res.state
    assert new.revision_id == res.revision_id
    assert new.statuses() == "C C C U C C P P U U"
    assert (new.pcur, new.ccur) == (3, 3)  # clamped to the first edited token
    assert new.completed == set()  # sentence 1 contains the edited token
    assert new.turn_id == st.turn_id + 1


def test_correction_updates_the_lexicon(store):
    book_id, page_id, rev1 = seed.book_page(store, TEXT)
    _correct(store, page_id, rev1)
    row = store.one("SELECT * FROM lexicon WHERE word='through' AND source='correction'")
    assert row is not None and row["book_id"] == book_id
    assert "through" in lexicon.entries(store, book_id)


def test_locate_picks_the_nearest_whole_word_occurrence():
    text = "the cat and the hat and the bat"
    assert corrections.locate(text, "the", near=13) == (12, 15)
    assert corrections.locate(text, "at", near=0) is None
    assert corrections.locate(text, "THE", near=30) == (24, 27)
    assert corrections.locate(text, "hat", near=0, window=(0, 10)) is None
