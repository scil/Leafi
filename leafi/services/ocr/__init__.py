"""OCR service (S2): page text and barcodes from a still Frame. Local only — images never leave the LAN.

Backends: `rapidocr` (PP-OCR ONNX, CPU, lazy), `mock` (reads ground truth embedded in PNG fixtures),
`qwen_vl` (second opinion, deferred in v1 by ADR-0011).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from leafi.core.ports import Frame
from leafi.services._registry import Registry

REGISTRY = Registry("ocr", {"rapidocr": "leafi.services.ocr.rapidocr", "mock": "leafi.services.ocr.mock"},
                    deferred={"qwen_vl"})


@dataclass(frozen=True)
class OcrLine:
    text: str
    conf: float
    box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # x0, y0, x1, y1

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]


@dataclass
class OcrResult:
    lines: list[OcrLine] = field(default_factory=list)
    rotation: int = 0  # degrees the frame was rotated before reading (0/90/180/270; P-3 auto-rotation)

    @property
    def good_lines(self) -> int:
        """Lines a page could be built from: confident and longer than a page number or a stray glyph."""
        return sum(1 for ln in self.lines if ln.conf >= 0.85 and len(ln.text) > 3)

    @property
    def confidence(self) -> float:
        if not self.lines:
            return 0.0
        total = sum(len(ln.text) for ln in self.lines) or 1
        return sum(ln.conf * len(ln.text) for ln in self.lines) / total

    @property
    def text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)


# A camera burns its clock into every frame ("2026/10/25 00:03:01", hardware/xiaomi-camera-069a01.md → Overlay);
# OCR reads it as a confident line, so it would count toward a page and become page text to be read aloud.
_CLOCK = re.compile(r"^\s*\d{4}[/.-]\d{1,2}[/.-]\d{1,2}\s*\d{1,2}:\d{2}(:\d{2})?\s*$")


def drop_overlay(lines: list[OcrLine]) -> list[OcrLine]:
    """Without the camera's clock line and the logo beside it (a line of ≤ 3 characters on the clock's row,
    left of it, such as Xiaomi's "mi"). A clock-only line is never book text."""
    clocks = [ln for ln in lines if _CLOCK.match(ln.text)]

    def logo(ln: OcrLine) -> bool:
        return len(ln.text.strip()) <= 3 and any(
            abs((ln.box[1] + ln.box[3]) / 2 - (c.box[1] + c.box[3]) / 2) < max(ln.height, c.height)
            and ln.box[2] <= c.box[0] + c.height for c in clocks)

    return [ln for ln in lines if ln not in clocks and not logo(ln)]


def reading_order(lines: list[OcrLine]) -> list[OcrLine]:
    """Top-to-bottom, then left-to-right for lines whose vertical centres are within half a line height."""
    def key(ln: OcrLine):
        return ((ln.box[1] + ln.box[3]) / 2, ln.box[0])

    ordered = sorted(lines, key=key)
    rows: list[list[OcrLine]] = []
    for ln in ordered:
        c = (ln.box[1] + ln.box[3]) / 2
        if rows:
            last = rows[-1][0]
            lc = (last.box[1] + last.box[3]) / 2
            if abs(c - lc) < max(ln.height, last.height) / 2:
                rows[-1].append(ln)
                continue
        rows.append([ln])
    return [ln for row in rows for ln in sorted(row, key=lambda x: x.box[0])]


class Ocr(Protocol):
    async def read(self, frame: Frame) -> OcrResult: ...

    async def barcodes(self, frame: Frame) -> list[str]: ...
