"""Page tracker with mock OCR and PIL fixtures (ADR-0010 §1, reliability.md)."""

from __future__ import annotations

import datetime as dt

import pytest

from leafi.core.storage import Store
from leafi.services.ocr.mock import MockOcr
from leafi.study import books, corrections, lexicon, pages
from leafi.study.page_tracker import PageTracker, frame_diff, purge_page_images, split_number
from tests import seed
from tests.fixtures.pages import PAGES, FakeEye, blank, render


async def _nosleep(_):
    return None


@pytest.fixture
def env(settings, tmp_path):
    store = Store(settings.db_path)
    book = books.find_or_create(store, "Fixture")
    eye = FakeEye([])
    tracker = PageTracker(store, eye, MockOcr(), settings, sleep=_nosleep)
    return store, book, eye, tracker


async def test_tracker_picks_the_right_page_among_five(env):
    store, book, eye, tracker = env
    ids = []
    for text in PAGES:
        eye.show(render(text))
        found = await tracker.find(book)
        assert found.status == "ready"
        ids.append(found.page_id)
    assert len(set(ids)) == 5
    eye.show(render(PAGES[2]))
    again = await tracker.find(book)
    assert again.status == "ready" and again.page_id == ids[2]
    assert pages.current_text(store, ids[2]) == PAGES[2]


async def test_printed_number_identifies_the_page(env):
    store, book, eye, tracker = env
    eye.show(render(PAGES[0], number=12))
    first = await tracker.find(book)
    assert store.one("SELECT printed_number FROM pages WHERE id=?", (first.page_id,))["printed_number"] == 12
    assert pages.current_text(store, first.page_id) == PAGES[0]  # the number is not page text
    eye.show(render(PAGES[0] + "\nA new last line.", number=12))
    assert (await tracker.find(book)).page_id == first.page_id


async def test_two_close_candidates_are_uncertain_until_confirmed(env):
    store, book, eye, tracker = env
    a = pages.create_page(store, book, None, pages.observations_of(PAGES[1]))
    pages.create_page(store, book, None, pages.observations_of(PAGES[1]))
    pages.insert_revision(store, a, PAGES[1], "ocr", [], [])
    eye.show(render(PAGES[1]))
    found = await tracker.find(book)
    assert found.status == "uncertain" and len(found.candidates) == 2 and "Is this page" in found.message
    ok = tracker.confirm(found, a)
    assert ok.status == "ready" and ok.page_id == a


async def test_camera_lost_suspends_assessment(env):
    store, book, eye, tracker = env
    eye.show(None)
    assert (await tracker.find(book)).status == "unavailable"


async def test_frame_diff_settle_waits_for_still_frames(env):
    store, book, eye, tracker = env
    page = render(PAGES[0])
    eye.show(blank(1), blank(2), blank(3), page, page, page)
    frame = await tracker.settle()
    assert frame is not None and frame_diff(frame, page) == 0.0
    eye.show(*[blank(k) for k in range(30)])
    assert await tracker.settle(max_frames=8) is None


async def test_verified_correction_survives_a_later_misread_and_feeds_the_lexicon(env):
    store, book, eye, tracker = env
    text = "The wind blew through the trees.\nThe leaves fell down."
    misread = "The wind blew though the trees.\nThe leaves fell down."
    eye.show(render(text, ocr_text=misread))
    found = await tracker.find(book)
    assert pages.current_text(store, found.page_id) == misread
    span = corrections.locate(misread, "though")
    corrections.apply_correction(store, page_id=found.page_id, revision_id=found.revision_id,
                                 char_start=span[0], char_end=span[1], new_text="through", source="text",
                                 learner_id=seed.learner(store))
    assert "through" in lexicon.entries(store, book)
    eye.show(render(text, ocr_text=misread.replace("leaves", "leeves")))
    again = await tracker.find(book)
    assert again.page_id == found.page_id
    assert pages.current_text(store, found.page_id) == "The wind blew through the trees.\nThe leeves fell down."


async def test_page_images_are_saved_and_purged_after_retention(env, settings):
    store, book, eye, tracker = env
    eye.show(render(PAGES[0]))
    await tracker.find(book)
    (row,) = store.all("SELECT * FROM page_images")
    assert row["path"].startswith(str(settings.cache_dir))
    assert purge_page_images(store, 7) == 0
    later = dt.datetime.now(dt.UTC) + dt.timedelta(days=8)
    assert purge_page_images(store, 7, now=later) == 1
    assert store.all("SELECT * FROM page_images") == []


def _lines(*texts, conf=0.97):
    from leafi.services.ocr import OcrLine

    return [OcrLine(t, c) for t, c in zip(texts, conf if isinstance(conf, tuple) else (conf,) * len(texts),
                                          strict=True)]


def test_split_number():
    assert split_number(_lines("12", "Tom had a kite."), 0.85) == (12, ["Tom had a kite."])
    assert split_number(_lines("Tom had a kite.", "Page 7"), 0.85) == (7, ["Tom had a kite."])
    assert split_number(_lines("Tom had 3 kites."), 0.85) == (None, ["Tom had 3 kites."])


def test_a_page_number_read_without_confidence_gives_no_number_and_is_not_text():
    """Round 3 S8: a footer misread as "18" at 0.2 must not pick stored page 18 (ADR-0010: a confidently read
    number), and a number-only line is never reading text."""
    assert split_number(_lines("Tom had a kite.", "18", conf=(0.97, 0.2)), 0.85) == (None, ["Tom had a kite."])
    assert split_number(_lines("3", "Tom had a kite.", "18", conf=(0.3, 0.97, 0.95)), 0.85) == (
        18, ["Tom had a kite."])


@pytest.mark.parametrize("old,new,partial", [
    ("one two three four five six seven eight nine ten eleven twelve " * 4,
     "one two three four five six seven eight nine ten eleven twelve " * 2, True),  # half gone
    ("one two three four five six seven eight nine ten eleven twelve " * 4,
     "one two three four five six seven eight nine ten eleven twelve " * 2 + "power bank", True),  # plus desk words
    ("The wind blew though the treez. The leeves fell dwn.", "The wind blew through the trees. The leaves fell down.",
     False),  # a page stored with OCR errors, read correctly (round 5 V1)
    ("Suddenly, my sister pointed to a big\ncompass in the middle of the room.\nDo you know",
     "compass in the middle of the room.\nSuddenly, my sister pointed to a big\nDo you know", False),  # moved line (W1)
    ("the the the the the the", "tha the tha the tha the", False),  # SequenceMatcher shifts on repeats (W2)
    ("run run run jump run run run", "run ran run jump ran run ran", False),  # a refrain with misreads
    ("Tom had a kite.", "Tom hada kite", False),  # a short page with one merged word (W3)
    ("Tom had a red kite.\nHe ran up the hill.", "Tom had a red kite. He ran up the hill.", False),  # reformatted
    ("", "anything at all", False),  # a stored revision with no words: guard skipped (W6)
])
def test_the_missing_words_guard(old, new, partial):
    from leafi.study.page_tracker import is_partial

    assert is_partial(old, new) is partial


async def test_a_partial_read_of_a_stored_page_adds_no_revision(env):
    """Round 4 U3: a hand over half a numbered page must not replace its text with the visible half."""
    store, book, eye, tracker = env
    full = "\n".join(f"Line {k} of the story goes on here." for k in range(8))
    eye.show(render(full, number=12))
    first = await tracker.find(book)
    revs = store.all("SELECT * FROM page_revisions WHERE page_id=?", (first.page_id,))
    eye.show(render("\n".join(full.splitlines()[:3]), number=12))
    found = await tracker.find(book)
    assert found.status == "low_confidence" and "/page" in found.message
    assert store.all("SELECT * FROM page_revisions WHERE page_id=?", (first.page_id,)) == revs
    assert pages.current_text(store, first.page_id) == full


async def test_a_better_read_of_a_stored_page_with_ocr_errors_is_added(env):
    store, book, eye, tracker = env
    text = "The wind blew through the trees.\nThe leaves fell down.\nWe ran home."
    eye.show(render(text, number=4, ocr_text=text.replace("through", "though").replace("leaves", "leeves")))
    first = await tracker.find(book)
    eye.show(render(text, number=4))
    again = await tracker.find(book)
    assert again.status == "ready" and again.page_id == first.page_id
    assert pages.current_text(store, first.page_id) == text

