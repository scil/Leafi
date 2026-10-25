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


def test_a_sideways_page_is_rotated_even_when_background_text_reads_upright(monkeypatch):
    """2026-10-25 rehearsal: the timestamp overlay, a large title and a printed cushion read as 3 confident lines
    at 0° while the page lay sideways; rotation must still be tried and the page's orientation kept."""
    from types import SimpleNamespace

    from leafi.services.ocr import rapidocr

    def lines(texts):
        boxes = [[[0, 40 * k], [300, 40 * k], [300, 40 * k + 30], [0, 40 * k + 30]] for k in range(len(texts))]
        return SimpleNamespace(txts=texts, scores=[0.97] * len(texts), boxes=boxes)

    background = ["2026/10/25 00:03:01", "SILVER UNDER", "Hello, my friend!"]
    page = background[:2] + [f"line {k} of the page text" for k in range(10)]
    monkeypatch.setattr(rapidocr, "rotated", lambda data, angle: f"{angle}".encode())
    ocr = rapidocr.RapidOcr(SimpleNamespace(ocr_version="PP-OCRv6", ocr_auto_rotate=True))
    ocr._engine = lambda data: lines(page if data == b"270" else background)
    res = ocr._read(b"frame")
    assert res.rotation == 270 and res.good_lines == 12


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


class _OrientationEngine:
    """Fake rapidocr engine: a landscape frame (the sideways desk book) yields one stray glyph; once the frame is
    portrait (rotated 90/270) it yields the page lines. Mirrors P-3 on the real captures."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def __call__(self, data: bytes):
        import io
        from types import SimpleNamespace

        from PIL import Image

        w, h = Image.open(io.BytesIO(data)).size
        self.calls.append((w, h))
        box = [[0, 0], [10, 0], [10, 10], [0, 10]]
        if w > h:
            return SimpleNamespace(boxes=[box], txts=["mi"], scores=[0.9])
        return SimpleNamespace(boxes=[box] * 4, txts=["Tom had a red kite.", "He ran up the hill.",
                                                       "The wind was strong.", "1"], scores=[0.98, 0.97, 0.99, 1.0])


async def test_rapidocr_tries_rotations_when_the_upright_read_is_poor(settings):
    """P-3: the desk book lay sideways; 0° read only the overlay, 270° read the page."""
    from leafi.services.ocr.rapidocr import RapidOcr

    engine = _OrientationEngine()
    backend = RapidOcr(settings)
    backend._engine = engine
    res = await backend.read(render(PAGES[0], number=1, width=1200))  # landscape render
    assert res.rotation == 90 and res.good_lines == 3 and "red kite" in res.text
    # 0° read poorly; 90° read the page's 3 lines, below MIN_GOOD_LINES, so the other two were tried and lost
    assert len(engine.calls) == 4
