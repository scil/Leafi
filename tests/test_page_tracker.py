"""Page tracker with mock OCR and PIL fixtures (ADR-0010 §1, reliability.md)."""

from __future__ import annotations

import datetime as dt

import pytest

from leafi.core.storage import Store
from leafi.services.ocr.mock import MockOcr
from leafi.study import books, corrections, lexicon, pages
from leafi.study.page_tracker import PageTracker, frame_diff, purge_page_images, split_number
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
                                 char_start=span[0], char_end=span[1], new_text="through", source="text")
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


def test_split_number():
    assert split_number(["12", "Tom had a kite."]) == (12, ["Tom had a kite."])
    assert split_number(["Tom had a kite.", "Page 7"]) == (7, ["Tom had a kite."])
    assert split_number(["Tom had 3 kites."]) == (None, ["Tom had 3 kites."])


async def test_session_identifies_the_book_and_page_from_the_camera(settings):
    from leafi.core.hub import Hub
    from leafi.services.brain.mock import MockBrain
    from leafi.services.catalog.mock import MockCatalog
    from leafi.study.session import StudySession
    from tests.fakes import RecordingFace, ScriptedListener

    store = Store(settings.db_path)
    page = render(PAGES[0], number=3)
    eye = FakeEye([render("Cover", isbn="9780140328721"), page])
    ocr = MockOcr()
    face = RecordingFace()
    hub = Hub(faces={"f": face}, eyes={"desk_cam": eye}, policy="none", study_eye="desk_cam")
    s = StudySession(store=store, hub=hub, settings=settings, brain=MockBrain(),
                     listener=ScriptedListener(["yes", "Tom had a red kite.", "/stop"]),
                     page_tracker=PageTracker(store, eye, ocr, settings, sleep=_nosleep), ocr=ocr,
                     catalog=MockCatalog({"9780140328721": "Kite Day"}))
    await s.run()
    assert store.one("SELECT title, isbn FROM books")[:] == ("Kite Day", "9780140328721")
    assert store.one("SELECT printed_number FROM pages")["printed_number"] == 3
    assert any("Kite Day" in t for t in face.texts)
    assert store.one("SELECT COUNT(*) AS n FROM observations")["n"] == 5
