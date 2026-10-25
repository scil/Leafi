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


async def test_low_confidence_on_an_unchanged_frame_asks_the_learner_at_once(settings):
    """Owner 2026-10-25: re-reading the same picture gives the same answer; ask at once, write nothing."""
    store = Store(settings.db_path)
    ocr = MockOcr()
    eye = FakeEye([render(PAGES[0], conf=0.4)])
    tracker = PageTracker(store, eye, ocr, settings, sleep=_nosleep)
    found = await tracker.find(books.find_or_create(store, "Fixture"))
    assert ocr.reads == 1
    assert found.status == "low_confidence" and "first line" in found.message
    assert store.all("SELECT * FROM pages") == []


async def test_low_confidence_recaptures_once_when_the_frame_changed(settings):
    store = Store(settings.db_path)
    ocr = MockOcr()
    first, second = render(PAGES[0], conf=0.4), render(PAGES[1], conf=0.97)
    eye = FakeEye([first, first, first, second, second, second])
    tracker = PageTracker(store, eye, ocr, settings, sleep=_nosleep, diff_threshold=1.0)
    found = await tracker.find(books.find_or_create(store, "Fixture"))
    assert ocr.reads == 2 and found.status == "ready"
    from leafi.study import pages

    assert "Mia found a shell" in pages.current_text(store, found.page_id)


async def test_an_unsure_angle_needs_help_like_low_confidence(settings):
    from leafi.services.ocr import OcrResult

    class Unsure(MockOcr):
        async def read(self, frame, *, purpose="page"):
            res = await super().read(frame, purpose=purpose)
            return OcrResult(res.lines, state="unsure")

    store = Store(settings.db_path)
    tracker = PageTracker(store, FakeEye([render(PAGES[0])]), Unsure(), settings, sleep=_nosleep)
    found = await tracker.find(books.find_or_create(store, "Fixture"))
    assert found.status == "low_confidence" and store.all("SELECT * FROM page_revisions") == []


async def test_an_ocr_read_past_the_timeout_is_a_page_not_seen(settings, monkeypatch):
    import asyncio

    from leafi.study import page_tracker

    class Slow(MockOcr):
        async def read(self, frame, *, purpose="page"):
            await asyncio.sleep(1)

    monkeypatch.setattr(page_tracker, "OCR_TIMEOUT_S", 0.01)
    store = Store(settings.db_path)
    tracker = PageTracker(store, FakeEye([render(PAGES[0])]), Slow(), settings, sleep=_nosleep)
    assert (await tracker.find(books.find_or_create(store, "Fixture"))).status == "unavailable"


def test_a_sideways_page_is_rotated_even_when_background_text_reads_upright(monkeypatch):
    """2026-10-25 rehearsal: the timestamp overlay, a large title and a printed cushion read as 3 confident lines
    at 0° while the page lay sideways; the page's orientation must win, by its wide confident lines."""
    background = ["2026/10/25 00:03:01", "SILVER UNDER", "Hello, my friend!"]
    page = background[:2] + [f"line {k} of the page text" for k in range(10)]
    ocr = _backend(monkeypatch, {0: _wide(background), 270: _wide(page), 90: _tall(page)})
    res = ocr._read(_png())
    assert res.rotation == 270 and res.state == "sure" and res.good_lines == 11  # the clock is not a page line


# ---------------------------------------------------------------- RapidOcr with fake engines (design 2026-10-25)

def _png(w: int = 400, h: int = 300) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, "PNG")
    return buf.getvalue()


def _raw(texts, quads, conf=0.97):
    from types import SimpleNamespace

    confs = conf if isinstance(conf, list) else [conf] * len(texts)
    return SimpleNamespace(txts=list(texts), scores=confs, boxes=[[list(p) for p in q] for q in quads])


def _wide(texts, conf=0.97, x=0, y=0):
    return _raw(texts, [((x, y + 40 * k), (x + 300, y + 40 * k), (x + 300, y + 40 * k + 20), (x, y + 40 * k + 20))
                        for k in range(len(texts))], conf)


def _tall(texts, conf=0.97):
    return _raw(texts, [((40 * k, 0), (40 * k + 20, 0), (40 * k + 20, 300), (40 * k, 300))
                        for k in range(len(texts))], conf)


class _Full:
    """Fake full engine: answers per angle, read from the tag `turned` puts on the image; counts calls."""

    def __init__(self, by_angle):
        self.by_angle, self.calls = by_angle, []

    def __call__(self, img):
        angle = img.info["angle"]
        self.calls.append(angle)
        return self.by_angle.get(angle) or _raw([], [])


def _backend(monkeypatch, by_angle, *, rotations="270,90,0", probe=(None, {}, 0.0)):
    from types import SimpleNamespace

    from leafi.services.ocr import rapidocr

    real = rapidocr.turned

    def tagged(img, angle):
        out = real(img, angle)
        out = out.copy() if out is img else out
        out.info["angle"] = angle
        return out

    monkeypatch.setattr(rapidocr, "turned", tagged)
    ocr = rapidocr.RapidOcr(SimpleNamespace(ocr_version="PP-OCRv6", ocr_rotations=rotations,
                                            ocr_min_confidence=0.85))
    ocr._engines["full"] = _Full(by_angle)
    if probe is not None:
        ocr._probe = lambda img: probe
    return ocr


PAGE = [f"line {k} of the page text" for k in range(6)]


def test_parse_rotations_keeps_order_and_refuses_bad_values():
    from leafi.services.ocr.rapidocr import parse_rotations

    assert parse_rotations("270, 90,0") == (270, 90, 0)
    for bad in ("", " , ", "45", "90,90", "90,x"):
        with pytest.raises(ValueError):
            parse_rotations(bad)


def test_a_bad_hand_edited_rotation_setting_logs_and_uses_the_default(caplog):
    from types import SimpleNamespace

    from leafi.services.ocr.rapidocr import RapidOcr

    assert RapidOcr(SimpleNamespace(ocr_rotations="45,90")).rotations == (270, 90, 0)
    assert "OCR_ROTATIONS" in caplog.text and "45" not in caplog.text  # the rule, never the value


def test_the_scan_reads_every_listed_angle_in_order_and_wide_lines_decide(monkeypatch):
    """At 0°/90° the page lines are tall boxes rapidocr still reads; only at 270° are they wide."""
    ocr = _backend(monkeypatch, {270: _wide(PAGE), 90: _tall(PAGE), 0: _tall(PAGE)}, probe=None)
    ocr._probe = lambda img: (None, {}, 0.0)
    res = ocr._read(_png())
    assert ocr._engines["full"].calls == [270, 90, 0]
    assert (res.rotation, res.state) == (270, "sure")
    assert [p.kind for p in res.passes] == ["scan", "scan", "scan"]


def test_a_tie_goes_to_the_earlier_listed_angle_and_is_unsure(monkeypatch):
    ocr = _backend(monkeypatch, {270: _wide(PAGE), 90: _wide(PAGE)})
    res = ocr._read(_png())
    assert res.rotation == 270 and res.state == "unsure"


def test_two_body_lines_are_no_text(monkeypatch):
    ocr = _backend(monkeypatch, {270: _wide(PAGE[:2])})
    assert ocr._read(_png()).state == "no text"


def test_one_listed_angle_has_no_runner_up(monkeypatch):
    """Round 5 V3 / round 6 W4: OCR_ROTATIONS=0 with a page → sure; with a blank frame → no text, no exception."""
    assert _backend(monkeypatch, {0: _wide(PAGE)}, rotations="0")._read(_png()).state == "sure"
    assert _backend(monkeypatch, {}, rotations="0")._read(_png()).state == "no text"


def test_the_probe_nominee_is_read_once_and_kept_when_evident(monkeypatch):
    ocr = _backend(monkeypatch, {270: _wide(PAGE)}, probe=(270, {270: 194.0, 90: 32.0}, 0.8))
    res = ocr._read(_png())
    assert ocr._engines["full"].calls == [270] and res.state == "sure" and res.passes[0].kind == "probe"


def test_a_probe_nominee_that_does_not_read_like_a_page_falls_back_to_the_scan(monkeypatch):
    """Desk text can win the probe; its full pass is not a page, so every listed angle is read."""
    ocr = _backend(monkeypatch, {90: _wide(["ok"]), 270: _wide(PAGE)}, probe=(90, {90: 40.0, 270: 0.0}, 0.8))
    res = ocr._read(_png())
    assert ocr._engines["full"].calls == [90, 270, 0] and res.rotation == 270


def test_the_remembered_angle_is_one_pass_while_the_book_stays(monkeypatch):
    ocr = _backend(monkeypatch, {270: _wide(PAGE)})
    first = ocr._read(_png())
    calls = len(ocr._engines["full"].calls)
    again = ocr._read(_png(), "page", first.rotation, first.region)
    assert ocr._engines["full"].calls[calls:] == [270] and again.state == "sure" and again.passes[0].kind == "remembered"


def test_text_outside_the_remembered_region_does_not_keep_the_angle(monkeypatch):
    """A desk label at the old angle, away from where the book was: the read goes on to the probe and the scan."""
    ocr = _backend(monkeypatch, {270: _wide(["a label on the desk"] * 3, x=2000, y=2000), 90: _wide(PAGE)})
    res = ocr._read(_png(), "page", 270, (0.0, 0.0, 300.0, 220.0))
    assert res.rotation == 90 and ocr._engines["full"].calls == [270, 90, 0]


def test_a_moved_book_confirmed_by_the_probe_needs_no_scan(monkeypatch):
    """Round 5 V5: the remembered pass is a page but elsewhere; the probe names the same angle → keep that pass."""
    ocr = _backend(monkeypatch, {270: _wide(PAGE, x=900, y=900)}, probe=(270, {270: 150.0, 90: 0.0}, 0.8))
    res = ocr._read(_png(), "page", 270, (0.0, 0.0, 300.0, 220.0))
    assert ocr._engines["full"].calls == [270] and res.state == "sure" and res.region[0] == 900


def test_the_probe_reads_only_the_two_candidate_angles_and_ignores_the_clock(monkeypatch):
    """Five of six line boxes are tall → only 90°/270° are recognised; a clock crop never counts."""
    from types import SimpleNamespace

    import numpy as np

    ocr = _backend(monkeypatch, {}, probe=None)
    tall = [np.float32([[20 + 30 * k, 10], [40 + 30 * k, 10], [40 + 30 * k, 210], [20 + 30 * k, 210]])
            for k in range(5)]
    wide = [np.float32([[200, 250], [390, 250], [390, 270], [200, 270]])]
    ocr._engines["det"] = lambda img: SimpleNamespace(boxes=np.stack(tall + wide))
    seen = []

    def rec(crop):
        a = crop.info["angle"]
        seen.append(a)
        if a == 270 and seen.count(270) == 1:
            return SimpleNamespace(txts=["2026/10/25 09:43:44"], scores=[0.99])
        return SimpleNamespace(txts=["the page reads here"] if a == 270 else ["e o e"], scores=[0.97])

    ocr._engines["rec"] = rec
    from PIL import Image

    nominee, scores, _ = ocr._probe(Image.new("RGB", (400, 300), "white"))
    assert set(seen) == {90, 270} and nominee == 270
    assert scores[270] == pytest.approx(4 * 19 * 0.97)  # four crops; the clock excluded
    monkeypatch.setattr(ocr, "rotations", (90, 0))
    assert ocr._probe(Image.new("RGB", (400, 300), "white"))[1].keys() == {90}  # 270 is not listed: skipped


def test_a_cover_scans_every_angle_keeps_upright_lines_and_never_sets_the_angle(monkeypatch):
    """Round 5 V2: at 270° the title is wide and the desk text a tall box; `identify` must return the title."""
    import asyncio

    ocr = _backend(monkeypatch, {270: _raw(["THE BIG STORM", "MEMBERSHIP"],
                                           [((0, 0), (300, 0), (300, 40), (0, 40)),
                                            ((350, 0), (380, 0), (380, 300), (350, 300))]),
                                 0: _raw(["MEMBERSHIP"], [((0, 0), (300, 0), (300, 30), (0, 30))], 0.6)})
    guess = asyncio.run(books.identify(FakeEye([render("cover")]), ocr, None))
    assert guess.source == "cover" and guess.title == "THE BIG STORM"
    assert ocr._engines["full"].calls == [270, 90, 0] and ocr._angle is None


def test_a_short_stylised_cover_title_is_still_found(monkeypatch):
    """Round 6 W5: "Zog" at 0.7 scores 0 under the page rules; covers count it."""
    import asyncio

    ocr = _backend(monkeypatch, {0: _raw(["Zog"], [((0, 0), (200, 0), (200, 60), (0, 60))], 0.7)})
    assert asyncio.run(books.identify(FakeEye([render("cover")]), ocr, None)).title == "Zog"


def test_engines_are_built_with_the_line_classifier_off(monkeypatch):
    import rapidocr as rapidocr_pkg

    from leafi.services.ocr import rapidocr

    built = []
    monkeypatch.setattr(rapidocr_pkg, "RapidOCR", lambda params: built.append(params) or object())
    for stages in ("full", "det", "rec"):
        rapidocr.engine(stages=stages)
    assert [p["Global.use_cls"] for p in built] == [False, False, False]
    assert [(p["Global.use_det"], p["Global.use_rec"]) for p in built] == [(True, True), (True, False), (False, True)]


async def test_reads_are_serialised_and_a_timed_out_read_still_publishes_first(monkeypatch):
    """Design O5: a caller's timeout stops only its wait; the worker keeps the lock until it returns and publishes;
    the next read waits and sees what the first published. Never two workers at once."""
    import asyncio
    import threading

    from leafi.core.ports import Frame
    from leafi.services.ocr import OcrResult

    ocr = _backend(monkeypatch, {})
    release, active, peak, seen = threading.Event(), [0], [0], []

    def worker(data, purpose, angle, region):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        seen.append((data, angle))
        if data == b"A":
            release.wait(5)
        active[0] -= 1
        return OcrResult(state="sure", rotation=270 if data == b"A" else 90, region=(0, 0, 1, 1))

    ocr._read = worker
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(ocr.read(Frame(b"A")), 0.05)
    b = asyncio.create_task(ocr.read(Frame(b"B")))
    await asyncio.sleep(0.05)
    assert seen == [(b"A", None)]  # B waits for the lock while A's worker runs
    release.set()
    res = await b
    assert seen == [(b"A", None), (b"B", 270)] and res.rotation == 90 and peak[0] == 1
    assert ocr._angle == 90
    await ocr.aclose()
    with pytest.raises(RuntimeError):
        await ocr.read(Frame(b"C"))


async def test_a_failing_worker_is_reported_to_the_caller_and_logged(monkeypatch, caplog):
    from leafi.core.ports import Frame

    ocr = _backend(monkeypatch, {})

    def boom(*a):
        raise ValueError("engine broke")

    ocr._read = boom
    with pytest.raises(ValueError):
        await ocr.read(Frame(b"A"))
    await ocr.aclose()
    assert "ocr read failed" in caplog.text


def test_reading_order_follows_a_skewed_page():
    """Round 6 W8: at 5° a 400 px line's bounding box is ~50 px tall, more than the 20 px pitch; rows must come
    from the quad's thickness and centres turned by −skew, or long and short lines swap."""
    import math

    from leafi.services.ocr import OcrLine

    a = math.radians(5)

    def line(k: int, length: float) -> OcrLine:
        pts = [(0, 20 * k), (length, 20 * k), (length, 20 * k + 15), (0, 20 * k + 15)]
        q = tuple((x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)) for x, y in pts)
        xs, ys = [p[0] for p in q], [p[1] for p in q]
        return OcrLine(f"line {k} text", 0.97, (min(xs), min(ys), max(xs), max(ys)), q)

    lines = [line(k, 400 if k % 2 == 0 else 100) for k in range(6)]
    assert [ln.text for ln in reading_order(list(reversed(lines)))] == [ln.text for ln in lines]


def test_the_camera_clock_and_logo_are_not_page_text():
    """2026-10-25 evaluation window: the camera's burnt-in clock read as a confident line, counted toward a
    page and would have become text for the child to read; the "mi" logo beside it likewise."""
    from types import SimpleNamespace

    from leafi.services.ocr import drop_overlay
    from leafi.services.ocr.rapidocr import to_result

    lines = [OcrLine("MI", 0.95, (0, 0, 40, 40)), OcrLine("2026/10/25 00:03:01", 0.99, (50, 0, 460, 40)),
             OcrLine("Chapter 3", 0.97, (100, 200, 400, 240)), OcrLine("Yes", 0.97, (0, 300, 60, 340)),
             OcrLine("At 10:30 the bus left.", 0.97, (100, 400, 600, 440))]
    assert [ln.text for ln in drop_overlay(lines)] == ["Chapter 3", "Yes", "At 10:30 the bus left."]
    raw = SimpleNamespace(txts=[ln.text for ln in lines], scores=[ln.conf for ln in lines],
                          boxes=[[[x0, y0], [x1, y0], [x1, y1], [x0, y1]] for x0, y0, x1, y1 in
                                 (ln.box for ln in lines)])
    res = to_result(raw)
    assert "2026" not in res.text and "MI" not in res.text and res.good_lines == 2


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


async def test_rapidocr_finds_a_sideways_page_through_read_and_remembers_its_angle(monkeypatch, settings):
    """P-3: the desk book lay sideways; 0° read only the overlay, 270° read the page; the next read is one pass."""
    ocr = _backend(monkeypatch, {0: _wide(["mi"]), 270: _wide(["Tom had a red kite.", "He ran up the hill.",
                                                                "The wind was strong.", "1"])})
    frame = render(PAGES[0], number=1, width=1200)
    res = await ocr.read(frame)
    assert res.rotation == 270 and res.good_lines == 3 and "red kite" in res.text and ocr._angle == 270
    before = len(ocr._engines["full"].calls)
    await ocr.read(frame)
    assert ocr._engines["full"].calls[before:] == [270]
    await ocr.aclose()
