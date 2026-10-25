"""OCR service (S2): page text and barcodes from a still Frame. Local only — images never leave the LAN.

Backends: `rapidocr` (PP-OCR ONNX, CPU, lazy), `mock` (reads ground truth embedded in PNG fixtures),
`qwen_vl` (second opinion, deferred in v1 by ADR-0011).
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field
from typing import Protocol

from leafi.core.ports import Frame
from leafi.services._registry import Registry

REGISTRY = Registry("ocr", {"rapidocr": "leafi.services.ocr.rapidocr", "mock": "leafi.services.ocr.mock"},
                    deferred={"qwen_vl"})

Quad = tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]


@dataclass(frozen=True)
class OcrLine:
    text: str
    conf: float
    box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # x0, y0, x1, y1
    # The detector's four points (top-left, top-right, bottom-right, bottom-left in the image that was read), as
    # tuples so frozen equality still works; None for the mock and fixtures (design 2026-10-25 O6).
    quad: Quad | None = None

    @property
    def height(self) -> float:
        """The line's thickness: the quad's left edge when there is one (a skewed line's bounding box is far taller
        than the line, design round 6 W8), else the box height."""
        if self.quad is not None:
            (x0, y0), _, _, (x3, y3) = self.quad
            return math.hypot(x3 - x0, y3 - y0)
        return self.box[3] - self.box[1]

    @property
    def wide(self) -> bool:
        """Read upright at this frame rotation: rapidocr turns tall crops by 90° and still reads them, so only a wide
        box shows that the frame itself is the right way up (design O2)."""
        return self.box[2] - self.box[0] > self.box[3] - self.box[1]

    @property
    def body(self) -> bool:
        """Confident, upright and longer than a page number or a stray glyph: what page evidence is counted from."""
        return self.conf >= 0.85 and len(self.text) > 3 and self.wide


@dataclass(frozen=True)
class PassInfo:
    """One full OCR pass, for the console: which angle, why it was tried, what it scored."""
    angle: int
    kind: str  # remembered | probe | scan
    score: float
    wide: int
    total: int
    seconds: float


@dataclass
class OcrResult:
    lines: list[OcrLine] = field(default_factory=list)
    rotation: int = 0  # degrees the frame was turned counter-clockwise before reading (0/90/180/270)
    # sure | unsure | no text; the default keeps mock and hand-built results as they were (design O8)
    state: str = "sure"
    region: tuple[float, float, float, float] | None = None  # bounding box of the body lines, at `rotation`
    passes: tuple[PassInfo, ...] = ()
    probe: tuple[int | None, dict[int, float], float] | None = None  # nominated angle, crop scores, seconds

    @property
    def good_lines(self) -> int:
        """Lines a page could be built from: confident and longer than a page number or a stray glyph."""
        return sum(1 for ln in self.lines if ln.conf >= 0.85 and len(ln.text) > 3)

    @property
    def confidence(self) -> float:
        return confidence_of(self.lines)

    @property
    def text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)

    def needs_help(self, min_conf: float) -> bool:
        """The one acceptance predicate: the angle was not sure, or the text is not confident (design O8)."""
        return self.state != "sure" or self.confidence < min_conf


def confidence_of(lines: list[OcrLine]) -> float:
    """Character-weighted mean confidence."""
    if not lines:
        return 0.0
    total = sum(len(ln.text) for ln in lines) or 1
    return sum(ln.conf * len(ln.text) for ln in lines) / total


# A camera burns its clock into every frame ("2026/10/25 00:03:01", hardware/xiaomi-camera-069a01.md → Overlay);
# OCR reads it as a confident line, so it would count toward a page and become page text to be read aloud.
_CLOCK = re.compile(r"^\s*\d{4}[/.-]\d{1,2}[/.-]\d{1,2}\s*\d{1,2}:\d{2}(:\d{2})?\s*$")


def is_clock(text: str) -> bool:
    return bool(_CLOCK.match(text))


def drop_overlay(lines: list[OcrLine]) -> list[OcrLine]:
    """Without the camera's clock line and the logo beside it (a line of ≤ 3 characters on the clock's row,
    left of it, such as Xiaomi's "mi"). A clock-only line is never book text."""
    clocks = [ln for ln in lines if _CLOCK.match(ln.text)]

    def logo(ln: OcrLine) -> bool:
        return len(ln.text.strip()) <= 3 and any(
            abs((ln.box[1] + ln.box[3]) / 2 - (c.box[1] + c.box[3]) / 2) < max(ln.height, c.height)
            and ln.box[2] <= c.box[0] + c.height for c in clocks)

    return [ln for ln in lines if ln not in clocks and not logo(ln)]


MAX_SKEW_DEG = 15.0


def skew_of(lines: list[OcrLine]) -> float:
    """Median angle (radians) of the body lines' top edges, clamped to ±15°; 0 without quads (design O6)."""
    angles = [math.atan2(ln.quad[1][1] - ln.quad[0][1], ln.quad[1][0] - ln.quad[0][0])
              for ln in lines if ln.quad is not None and ln.body]
    if not angles:
        return 0.0
    limit = math.radians(MAX_SKEW_DEG)
    return max(-limit, min(limit, statistics.median(angles)))


def reading_order(lines: list[OcrLine]) -> list[OcrLine]:
    """Top-to-bottom, then left-to-right for lines whose centres are within half a line height — both measured in
    the lines' own direction: centres are turned by −skew first (adapted from docTR `_sort_boxes`), so a slightly
    tilted page keeps its line order. Without quads the skew is 0 and this is the plain axis-aligned order."""
    skew = skew_of(lines)
    cos, sin = math.cos(-skew), math.sin(-skew)

    def centre(ln: OcrLine) -> tuple[float, float]:
        x, y = (ln.box[0] + ln.box[2]) / 2, (ln.box[1] + ln.box[3]) / 2
        return x * cos - y * sin, x * sin + y * cos

    centres = {id(ln): centre(ln) for ln in lines}
    ordered = sorted(lines, key=lambda ln: (centres[id(ln)][1], centres[id(ln)][0]))
    rows: list[list[OcrLine]] = []
    for ln in ordered:
        c = centres[id(ln)][1]
        if rows:
            last = rows[-1][0]
            if abs(c - centres[id(last)][1]) < max(ln.height, last.height) / 2:
                rows[-1].append(ln)
                continue
        rows.append([ln])
    return [ln for row in rows for ln in sorted(row, key=lambda x: centres[id(x)][0])]


class Ocr(Protocol):
    async def read(self, frame: Frame, *, purpose: str = "page") -> OcrResult: ...

    async def barcodes(self, frame: Frame) -> list[str]: ...
