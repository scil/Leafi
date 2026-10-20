"""RapidOCR backend (PP-OCR, ONNX Runtime, CPU). `rapidocr` and `zxingcpp` are imported on first use;
calls run in an executor.

`OCR_VERSION` picks the pipeline (prototype P-3): `PP-OCRv6` = the multilingual small det/rec pair that
rapidocr 3.10 ships inside the wheel (no download); `PP-OCRv5` = the mobile Chinese detector with the
English recogniser, fetched once by `python -m leafi doctor --download`. Detector language: v6 accepts a
language code (`en`), v5 only `ch`/`multi`.
"""

from __future__ import annotations

import asyncio
import io

from leafi.core.ports import Frame
from leafi.services._registry import has_package
from leafi.services.ocr import OcrLine, OcrResult, reading_order

VERSIONS = ("PP-OCRv6", "PP-OCRv5")
DEFAULT_VERSION = "PP-OCRv6"


def engine(version: str = DEFAULT_VERSION, *, log_level: str = "warning"):
    """A configured `rapidocr.RapidOCR` for the English page pipeline of `version`."""
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
    }
    return RapidOCR(params=params)


def to_result(res) -> OcrResult:
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


class RapidOcr:
    def __init__(self, settings) -> None:
        self.version = str(getattr(settings, "ocr_version", DEFAULT_VERSION) or DEFAULT_VERSION)
        self._engine = None

    def _load(self):
        if self._engine is None:
            self._engine = engine(self.version)
        return self._engine

    async def read(self, frame: Frame) -> OcrResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._read, frame.data)

    def _read(self, data: bytes) -> OcrResult:
        return to_result(self._load()(data))

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
    version = str(getattr(settings, "ocr_version", DEFAULT_VERSION) or DEFAULT_VERSION)
    if version not in VERSIONS:
        return "error", f"OCR_VERSION {version!r} not in {VERSIONS}"
    return "ok", f"{version}; PP-OCRv5 files are fetched by `doctor --download` (v6 ships in the wheel)"
