"""OCR pipeline (mock backend) and book identification; real RapidOCR accuracy is hardware-marked."""

from __future__ import annotations

import pytest

from leafi.core.storage import Store
from leafi.core.text import norm, words
from leafi.services.catalog.mock import MockCatalog
from leafi.services.ocr import OcrLine, reading_order
from leafi.services.ocr.mock import MockOcr
from leafi.study import books
from leafi.study.page_tracker import PageTracker
from tests.fixtures.pages import PAGES, FakeEye, render


async def _nosleep(_):
    return None


async def test_good_confidence_reads_once(settings):
    store = Store(settings.db_path)
    ocr = MockOcr()
    tracker = PageTracker(store, FakeEye([render(PAGES[0], conf=0.97)]), ocr, settings, sleep=_nosleep)
    frame, result = await tracker.read()
    assert result.text == PAGES[0] and ocr.reads == 1


async def test_low_confidence_recaptures_once_then_asks_the_learner(settings):
    store = Store(settings.db_path)
    ocr = MockOcr()
    eye = FakeEye([render(PAGES[0], conf=0.4)])
    tracker = PageTracker(store, eye, ocr, settings, sleep=_nosleep)
    found = await tracker.find(books.find_or_create(store, "Fixture"))
    assert ocr.reads == 2
    assert found.status == "low_confidence" and "first line" in found.message
    assert store.all("SELECT * FROM pages") == []


def test_reading_order_is_top_to_bottom_then_left_to_right():
    lines = [OcrLine("second", 1, (0, 50, 100, 70)), OcrLine("right", 1, (200, 10, 300, 30)),
             OcrLine("left", 1, (0, 12, 100, 32))]
    assert [ln.text for ln in reading_order(lines)] == ["left", "right", "second"]


async def test_book_identified_by_barcode_then_catalog_title():
    eye = FakeEye([render("Cover", isbn="978-0-14-032872-1")])
    cat = MockCatalog({"9780140328721": "Charlie and the Chocolate Factory"})
    guess = await books.identify(eye, MockOcr(), cat)
    assert (guess.source, guess.isbn, guess.title) == ("barcode", "9780140328721", "Charlie and the Chocolate Factory")
    assert cat.asked == ["9780140328721"]  # ISBN digits only


async def test_book_identified_by_cover_title_or_not_at_all():
    guess = await books.identify(FakeEye([render("THE BIG STORM\nby A. Writer")]), MockOcr(), None)
    assert guess.source == "cover" and guess.title in ("THE BIG STORM", "by A. Writer")
    assert (await books.identify(FakeEye([None]), MockOcr(), None)).source == "none"
    assert (await books.identify(None, MockOcr(), None)).source == "none"


@pytest.mark.hardware
async def test_rapidocr_reads_pil_fixture_pages_at_98_percent_words(settings):
    from leafi.services.ocr.rapidocr import RapidOcr

    ocr = RapidOcr(settings)
    total = correct = 0
    for text in PAGES:
        result = await ocr.read(render(text))
        truth = [norm(w) for w in words(text)]
        got = set(norm(w) for w in words(result.text))
        total += len(truth)
        correct += sum(1 for w in truth if w in got)
    assert correct / total >= 0.98
