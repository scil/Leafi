"""OCR service (S2): page text and barcodes from a still Frame. Local only — images never leave the LAN.

Backends: `rapidocr` (PP-OCR ONNX, CPU, lazy), `mock` (reads ground truth embedded in PNG fixtures),
`qwen_vl` (second opinion, deferred in v1 by ADR-0011).
"""

from __future__ import annotations

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
