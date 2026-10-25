"""RapidOCR backend (PP-OCR, ONNX Runtime, CPU). `rapidocr`, `cv2` and `zxingcpp` are imported on first use;
calls run in an executor, one at a time.

`OCR_VERSION` picks the pipeline (prototype P-3): `PP-OCRv6` = the multilingual small det/rec pair that
rapidocr 3.10 ships inside the wheel (no download); `PP-OCRv5` = the mobile Chinese detector with the
English recogniser, fetched once by `python -m leafi doctor --download`. Detector language: v6 accepts a
language code (`en`), v5 only `ch`/`multi`.

Orientation (design `docs/plans/active/2026-10-25-ocr-rotation-and-text-block-design.md`, stage 1): a page read
tries the remembered angle, then the angle probe's nominee, then every angle in `OCR_ROTATIONS`, and keeps the
first pass that reads like a page (`evident`), else the best by a margin. The line classifier is off and only wide
boxes count, because rapidocr turns tall line crops by 90° and reads them anyway: only the line *direction* shows
which way up the frame is.
"""

from __future__ import annotations

import asyncio
import io
import logging
import statistics
import time
from dataclasses import dataclass

from leafi.core.ports import Frame
from leafi.services._registry import has_package
from leafi.services.ocr import (OcrLine, OcrResult, PassInfo, confidence_of, drop_overlay, is_clock,
                                reading_order)

log = logging.getLogger("leafi.ocr")

VERSIONS = ("PP-OCRv6", "PP-OCRv5")
DEFAULT_VERSION = "PP-OCRv6"
ROTATION_ANGLES = ("0", "90", "180", "270")  # degrees the frame is turned counter-clockwise before reading
DEFAULT_ROTATIONS = "270,90,0"  # owner 2026-10-25: the desk book lies sideways; upside down is rare
PROBE_K = 6  # line crops the probe reads; with 2 the camera clock was the longest box and won (2026-10-25)
MARGIN = 0.5  # sure when the runner-up scores at most half the best (adapted from Tesseract OSD's best − second)
MIN_SCORE = 20.0  # confident characters below which a pass shows no page
MIN_BODY = 3


def parse_rotations(text: str) -> tuple[int, ...]:
    """`OCR_ROTATIONS`: comma-separated angles in try order, each one of ROTATION_ANGLES, no repeats, at least one.
    The error names the rule, never the value."""
    items = [i.strip() for i in str(text).split(",") if i.strip()]
    if not items:
        raise ValueError("at least one angle is required")
    if len(set(items)) != len(items):
        raise ValueError("an angle is repeated")
    if any(i not in ROTATION_ANGLES for i in items):
        raise ValueError("each angle must be one of " + ", ".join(ROTATION_ANGLES))
    return tuple(int(i) for i in items)


def engine(version: str = DEFAULT_VERSION, *, stages: str = "full", use_cls: bool = False,
           log_level: str = "warning"):
    """A configured `rapidocr.RapidOCR` for the English page pipeline of `version`. `stages`: `full`, `det`
    (detection only) or `rec` (recognition only); a stage that is off loads no model. Each configuration is its own
    instance: rapidocr keeps per-call overrides (`update_params`), so nothing here passes any."""
    from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR

    if version not in VERSIONS:
        raise ValueError(f"OCR_VERSION {version!r} not in {VERSIONS}")
    v6 = version == "PP-OCRv6"
    params = {
        "Det.engine_type": EngineType.ONNXRUNTIME, "Rec.engine_type": EngineType.ONNXRUNTIME,
        "Det.ocr_version": OCRVersion.PPOCRV6 if v6 else OCRVersion.PPOCRV5,
        "Rec.ocr_version": OCRVersion.PPOCRV6 if v6 else OCRVersion.PPOCRV5,
        "Det.model_type": ModelType.SMALL if v6 else ModelType.MOBILE,
        "Rec.model_type": ModelType.SMALL if v6 else ModelType.MOBILE,
        "Det.lang_type": LangDet.EN if v6 else LangDet.MULTI,
        "Rec.lang_type": LangRec.EN,
        "Global.log_level": log_level,
        "Global.use_cls": use_cls,
        "Global.use_det": stages in ("full", "det"),
        "Global.use_rec": stages in ("full", "rec"),
    }
    return RapidOCR(params=params)


def _quad(points) -> tuple:
    return tuple((float(p[0]), float(p[1])) for p in points)


def lines_of(res) -> list[OcrLine]:
    """rapidocr output → OcrLine with box and quad, unordered."""
    boxes = getattr(res, "boxes", None)
    txts = getattr(res, "txts", None) or ()
    scores = getattr(res, "scores", None) or ()
    lines = []
    for k, text in enumerate(txts):
        pts = boxes[k] if boxes is not None else [[0, 0], [0, 0], [0, 0], [0, 0]]
        xs = [float(p[0]) for p in pts]
        ys = [float(p[1]) for p in pts]
        lines.append(OcrLine(str(text), float(scores[k]) if k < len(scores) else 0.0,
                             (min(xs), min(ys), max(xs), max(ys)), _quad(pts) if boxes is not None else None))
    return lines


def to_result(res) -> OcrResult:
    """One engine output as a result in reading order (the probes' entry point)."""
    return OcrResult(reading_order(drop_overlay(lines_of(res))))


_TRANSPOSE = {90: "ROTATE_90", 180: "ROTATE_180", 270: "ROTATE_270"}


def turned(img, angle: int):
    """The frame turned counter-clockwise by `angle`, losslessly (every pass gets the same encoding)."""
    if angle == 0:
        return img
    from PIL import Image

    return img.transpose(getattr(Image.Transpose, _TRANSPOSE[angle]))


@dataclass
class Pass:
    angle: int
    kind: str
    lines: list[OcrLine]
    seconds: float

    @property
    def body(self) -> list[OcrLine]:
        return [ln for ln in self.lines if ln.body]

    @property
    def score(self) -> float:
        return sum(len(ln.text) * ln.conf for ln in self.body)

    @property
    def region(self) -> tuple[float, float, float, float] | None:
        b = self.body
        if not b:
            return None
        return (min(ln.box[0] for ln in b), min(ln.box[1] for ln in b),
                max(ln.box[2] for ln in b), max(ln.box[3] for ln in b))

    def info(self) -> PassInfo:
        return PassInfo(self.angle, self.kind, round(self.score, 1), sum(1 for ln in self.lines if ln.wide),
                        len(self.lines), round(self.seconds, 2))


def evident(p: Pass | None, min_conf: float) -> bool:
    """The one predicate for 'this pass reads like a page', on every path (design O2, round 2 R5)."""
    return (p is not None and len(p.body) >= MIN_BODY and p.score >= MIN_SCORE
            and confidence_of(p.lines) >= min_conf)


def in_region(p: Pass, region) -> bool:
    """At least half of the body lines' centres lie in the last sure read's region grown by 2 line heights."""
    body = p.body
    if region is None or not body:
        return False
    h = statistics.median(ln.height for ln in body)
    x0, y0, x1, y1 = region[0] - 2 * h, region[1] - 2 * h, region[2] + 2 * h, region[3] + 2 * h
    inside = sum(1 for ln in body
                 if x0 <= (ln.box[0] + ln.box[2]) / 2 <= x1 and y0 <= (ln.box[1] + ln.box[3]) / 2 <= y1)
    return inside * 2 >= len(body)


def cover_score(p: Pass) -> float:
    """Covers: wide lines at conf ≥ 0.5, no length bar, so a short or stylised title ("Zog") still counts."""
    return sum(len(ln.text) * ln.conf for ln in p.lines if ln.wide and ln.conf >= 0.5)


def _warp(arr, quad):
    import cv2
    import numpy as np

    q = np.asarray(quad, dtype=np.float32)
    w = int(max(np.linalg.norm(q[0] - q[1]), np.linalg.norm(q[2] - q[3])))
    h = int(max(np.linalg.norm(q[0] - q[3]), np.linalg.norm(q[1] - q[2])))
    if w < 2 or h < 2:
        return None
    m = cv2.getPerspectiveTransform(q, np.float32([[0, 0], [w, 0], [w, h], [0, h]]))
    return cv2.warpPerspective(arr, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


class RapidOcr:
    def __init__(self, settings) -> None:
        self.version = str(getattr(settings, "ocr_version", DEFAULT_VERSION) or DEFAULT_VERSION)
        self.min_conf = float(getattr(settings, "ocr_min_confidence", 0.85))
        try:
            self.rotations = parse_rotations(getattr(settings, "ocr_rotations", DEFAULT_ROTATIONS))
        except ValueError as e:
            log.warning("OCR_ROTATIONS: %s; using %s", e, DEFAULT_ROTATIONS)
            self.rotations = parse_rotations(DEFAULT_ROTATIONS)
        self._engines: dict[str, object] = {}
        # Published only by `_run` on the event loop, never by the worker (design O4/O5).
        self._angle: int | None = None
        self._region: tuple[float, float, float, float] | None = None
        self._busy = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    def _engine(self, stages: str):
        if stages not in self._engines:
            self._engines[stages] = engine(self.version, stages=stages)
        return self._engines[stages]

    # ---- one pass, the probe, the choice (pure: run in the executor, write no state)
    def _pass(self, img, angle: int, kind: str) -> Pass:
        t = time.perf_counter()
        lines = drop_overlay(lines_of(self._engine("full")(turned(img, angle))))
        return Pass(angle, kind, lines, time.perf_counter() - t)

    def _probe(self, img) -> tuple[int | None, dict[int, float], float]:
        """Detection once at 0°, then recognition of PROBE_K line crops at the two candidate angles (owner's idea,
        2026-10-25). Only nominates: the nominee's full pass must still be evident."""
        import numpy as np
        from PIL import Image

        t = time.perf_counter()
        boxes = getattr(self._engine("det")(img), "boxes", None)
        if boxes is None or len(boxes) == 0:
            return None, {}, time.perf_counter() - t

        def sides(q):
            return float(np.linalg.norm(q[0] - q[1])), float(np.linalg.norm(q[0] - q[3]))

        line_like = [q for q in (np.asarray(b, dtype=np.float32) for b in boxes)
                     if min(sides(q)) > 0 and max(sides(q)) >= 4 * min(sides(q))]
        take = sorted(line_like, key=lambda q: max(sides(q)), reverse=True)[:PROBE_K]
        if not take:
            return None, {}, time.perf_counter() - t
        tall = sum(1 for q in take if sides(q)[1] > sides(q)[0])
        pair = (90, 270) if tall * 2 > len(take) else (0, 180)
        cand = [a for a in pair if a in self.rotations]
        arr = np.asarray(img.convert("RGB"))
        crops = [c for c in (_warp(arr, q) for q in take) if c is not None]
        scores: dict[int, float] = {}
        rec = self._engine("rec")
        for a in cand:
            s = 0.0
            for c in crops:
                crop = turned(Image.fromarray(c), a)
                if crop.height >= crop.width:
                    continue
                r = rec(crop)
                txts, confs = getattr(r, "txts", None) or (), getattr(r, "scores", None) or ()
                for text, conf in zip(txts, confs, strict=False):
                    if float(conf) >= 0.85 and len(str(text)) > 3 and not is_clock(str(text)):
                        s += len(str(text)) * float(conf)
            scores[a] = s
        nominee = None
        if scores:
            best = max(scores, key=lambda a: (scores[a], -cand.index(a)))
            other = max((v for a, v in scores.items() if a != best), default=0.0)
            if scores[best] >= MIN_SCORE and other <= MARGIN * scores[best]:
                nominee = best
        return nominee, scores, time.perf_counter() - t

    def _result(self, p: Pass, state: str, tried: list[Pass], probe) -> OcrResult:
        return OcrResult(reading_order(p.lines), rotation=p.angle, state=state, region=p.region,
                         passes=tuple(x.info() for x in tried), probe=probe)

    def _choose(self, tried: list[Pass], probe, score=lambda p: p.score) -> tuple[Pass, str]:
        order = {a: k for k, a in enumerate(self.rotations)}
        ranked = sorted(tried, key=lambda p: (-score(p), order.get(p.angle, len(order))))
        best = ranked[0]
        second = score(ranked[1]) if len(ranked) > 1 else 0.0  # one pass: no runner-up (round 5 V3)
        if not evident(best, self.min_conf):
            return best, "no text"
        return best, "sure" if second <= MARGIN * score(best) else "unsure"

    def _read(self, data: bytes, purpose: str = "page", angle: int | None = None, region=None) -> OcrResult:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        img.load()
        if purpose == "cover":
            # every listed angle, own score, no probe, no remembered state (design O4, round 4 U9, round 6 W5)
            tried = [self._pass(img, a, "scan") for a in self.rotations]
            order = {a: k for k, a in enumerate(self.rotations)}
            best = sorted(tried, key=lambda p: (-cover_score(p), order[p.angle]))[0]
            wide = [ln for ln in best.lines if ln.wide] if cover_score(best) > 0 else []
            return OcrResult(reading_order(wide), rotation=best.angle, state="sure" if wide else "no text",
                             passes=tuple(x.info() for x in tried))
        tried: list[Pass] = []
        if angle is not None:
            p = self._pass(img, angle, "remembered")
            tried.append(p)
            if evident(p, self.min_conf) and in_region(p, region):
                return self._result(p, "sure", tried, None)
        probe = self._probe(img)
        nominee = probe[0]
        if angle is not None and nominee == angle and evident(tried[0], self.min_conf):
            return self._result(tried[0], "sure", tried, probe)  # the book moved; the probe confirms (round 5 V5)
        if nominee is not None and nominee != angle:
            p = self._pass(img, nominee, "probe")
            tried.append(p)
            if evident(p, self.min_conf):
                return self._result(p, "sure", tried, probe)
        done = {p.angle for p in tried}
        tried += [self._pass(img, a, "scan") for a in self.rotations if a not in done]
        best, state = self._choose(tried, probe)
        return self._result(best, state, tried, probe)

    # ---- serialised reads (design O5): one worker at a time; a caller's cancel stops only its wait
    async def read(self, frame: Frame, *, purpose: str = "page") -> OcrResult:
        if self._closed:
            raise RuntimeError("ocr closed")
        t = asyncio.create_task(self._run(frame.data, purpose))
        self._tasks.add(t)
        t.add_done_callback(self._done)
        return await asyncio.shield(t)

    async def _run(self, data: bytes, purpose: str) -> OcrResult:
        async with self._busy:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(None, self._read, data, purpose, self._angle, self._region)
            if purpose == "page" and res.state == "sure":
                self._angle, self._region = res.rotation, res.region
            return res

    def _done(self, t: asyncio.Task) -> None:
        self._tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            log.error("ocr read failed: %s", type(t.exception()).__name__, exc_info=t.exception())

    async def aclose(self) -> None:
        """Stop new reads and wait for queued and running ones (runner teardown, before the loop ends)."""
        self._closed = True
        await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def barcodes(self, frame: Frame) -> list[str]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._barcodes, frame.data)

    def _barcodes(self, data: bytes) -> list[str]:
        if not has_package("zxingcpp"):
            return []
        import zxingcpp  # lazy
        from PIL import Image

        return [r.text for r in zxingcpp.read_barcodes(Image.open(io.BytesIO(data)))]


def create(settings) -> RapidOcr:
    return RapidOcr(settings)


def status(settings) -> tuple[str, str]:
    if not has_package("rapidocr"):
        # Pinned: the orientation score relies on 3.10's crop rule (tall crops turned 90°) and on `update_params`
        # keeping per-call overrides; an upgrade re-runs the design's O8 captures first.
        return "missing package", "uv pip install --python .venv rapidocr==3.10.0 onnxruntime==1.31.0"
    version = str(getattr(settings, "ocr_version", DEFAULT_VERSION) or DEFAULT_VERSION)
    if version not in VERSIONS:
        return "error", f"OCR_VERSION {version!r} not in {VERSIONS}"
    try:
        parse_rotations(getattr(settings, "ocr_rotations", DEFAULT_ROTATIONS))
    except ValueError as e:
        return "error", f"OCR_ROTATIONS: {e}"
    return "ok", f"{version}; PP-OCRv5 files are fetched by `doctor --download` (v6 ships in the wheel)"
