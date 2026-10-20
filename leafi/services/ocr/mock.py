"""Mock OCR for PIL-rendered fixtures: the PNG carries its ground truth in text chunks.

`leafi:ocr` (what OCR "sees", default `leafi:text`), `leafi:conf` (per-line confidence, default 0.95),
`leafi:isbn` (barcode payload). A frame without chunks reads as empty text with confidence 0.
"""

from __future__ import annotations

import io

from leafi.core.ports import Frame
from leafi.services.ocr import OcrLine, OcrResult


def _info(frame: Frame) -> dict[str, str]:
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(frame.data))
        return dict(getattr(img, "text", {}) or {})
    except Exception:
        return {}


class MockOcr:
    def __init__(self) -> None:
        self.reads = 0

    async def read(self, frame: Frame) -> OcrResult:
        self.reads += 1
        info = _info(frame)
        text = info.get("leafi:ocr", info.get("leafi:text", ""))
        conf = float(info.get("leafi:conf", 0.95))
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return OcrResult([OcrLine(ln, conf, (10.0, 30.0 * k, 600.0, 30.0 * k + 24)) for k, ln in enumerate(lines)])

    async def barcodes(self, frame: Frame) -> list[str]:
        isbn = _info(frame).get("leafi:isbn")
        return [isbn] if isbn else []


def create(settings) -> MockOcr:
    return MockOcr()
