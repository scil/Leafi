"""RapidOCR backend (PP-OCR, ONNX Runtime, CPU). `rapidocr` and `zxingcpp` are imported on first use;
calls run in an executor. PP-OCRv5 vs v6 and capture width are prototype P-3.
"""

from __future__ import annotations

import asyncio
import io

from leafi.core.ports import Frame
from leafi.services._registry import has_package
from leafi.services.ocr import OcrLine, OcrResult, reading_order


class RapidOcr:
    def __init__(self, settings) -> None:
        self._engine = None

    def _load(self):
        if self._engine is None:
            from rapidocr import RapidOCR  # lazy: onnxruntime + models

            self._engine = RapidOCR()
        return self._engine

    async def read(self, frame: Frame) -> OcrResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._read, frame.data)

    def _read(self, data: bytes) -> OcrResult:
        res = self._load()(data)
        boxes = getattr(res, "boxes", None)
        txts = getattr(res, "txts", None) or ()
        scores = getattr(res, "scores", None) or ()
        lines = []
        for k, text in enumerate(txts):
            box = boxes[k] if boxes is not None else [[0, 0], [0, 0], [0, 0], [0, 0]]
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            lines.append(OcrLine(str(text), float(scores[k]) if k < len(scores) else 0.0,
                                 (min(xs), min(ys), max(xs), max(ys))))
        return OcrResult(reading_order(lines))

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
        return "missing package", "uv pip install --python .venv rapidocr==3.10.0 onnxruntime==1.31.0"
    return "ok", "models are fetched by rapidocr on first use; pre-provision them before LEAFI_NO_NETWORK runs"
