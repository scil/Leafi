"""Page identity (ADR-0010 §1): by printed number, by observations, uncertain → confirm."""

from __future__ import annotations

from leafi.core.storage import Store
from leafi.study import books, pages

P1 = "Tom had a red kite.\nHe ran up the hill.\nThe wind was strong."
P2 = "Mia found a shell.\nShe took it home.\nIt was pink inside."


def _book(tmp_path):
    store = Store(tmp_path / "leafi.db")
    return store, books.find_or_create(store, "Fixture")


def test_identity_by_printed_number(tmp_path):
    store, b = _book(tmp_path)
    pid = pages.create_page(store, b, 12, pages.observations_of(P1))
    assert pages.match_page(store, b, pages.observations_of(P2), printed_number=12).page_id == pid
    assert pages.match_page(store, b, pages.observations_of(P2), printed_number=13).status == "new"


def test_identity_by_observations_and_new_page(tmp_path):
    store, b = _book(tmp_path)
    p1 = pages.create_page(store, b, None, pages.observations_of(P1))
    pages.create_page(store, b, None, pages.observations_of(P2))
    m = pages.match_page(store, b, pages.observations_of(P1))
    assert (m.status, m.page_id) == ("matched", p1)
    other = "A totally different page.\nWith other words in it.\nAnd more lines here.\nFour."
    assert pages.match_page(store, b, pages.observations_of(other)).status == "new"


def test_two_close_candidates_are_uncertain(tmp_path):
    store, b = _book(tmp_path)
    p1 = pages.create_page(store, b, None, pages.observations_of(P1))
    p1b = pages.create_page(store, b, None, pages.observations_of(P1))
    m = pages.match_page(store, b, pages.observations_of(P1))
    assert m.status == "uncertain" and set(m.candidates) == {p1, p1b}


def test_page_identity_is_never_derived_from_text(tmp_path):
    store, b = _book(tmp_path)
    pid = pages.create_page(store, b, 3, pages.observations_of(P1))
    pages.insert_revision(store, pid, P1, "ocr", [], [])
    pages.insert_revision(store, pid, P2, "ocr", [], [[0, len(P1), 0, len(P2)]])
    assert pages.current_text(store, pid) == P2
    assert store.one("SELECT id FROM pages WHERE id=?", (pid,))["id"] == pid


def test_map_point_and_span_through_edits():
    edits = [[14, 20, 14, 21]]
    assert pages.map_point(10, edits) == 10
    assert pages.map_point(25, edits) == 26
    assert pages.map_span((14, 20), edits) == (14, 21)
    assert pages.map_span((15, 17), edits) == (14, 21)
    assert pages.overlaps((14, 20), (14, 20)) and not pages.overlaps((0, 14), (14, 20))
