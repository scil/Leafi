"""sherpa-onnx offline transducer (Parakeet TDT 0.6B v2 int8). Imported lazily; S3 shell.

Contract questions (token→word reconstruction, timing, confidence, silence, hotwords) belong to prototype
P-1; until it is recorded, words carry start times from token timestamps and `conf=None`, and hotwords
raise NotImplementedError.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from leafi.core.ports import Word
from leafi.services._registry import has_package

FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")


class SherpaAsr:
    def __init__(self, settings) -> None:
        self.model_dir = Path(settings.asr_model_dir)
        self._rec = None

    def _load(self):
        if self._rec is None:
            import sherpa_onnx  # lazy

            d = self.model_dir
            self._rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(d / FILES[0]), decoder=str(d / FILES[1]), joiner=str(d / FILES[2]),
                tokens=str(d / FILES[3]), model_type="nemo_transducer", num_threads=2)
        return self._rec

    async def transcribe(self, pcm: bytes, sample_rate: int, hotwords: list[str] | None = None) -> list[Word]:
        if hotwords:
            raise NotImplementedError("ASR hotwords wait for prototype P-1 (ASR_HOTWORDS=off, ADR-0011)")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._run, pcm, sample_rate)

    def _run(self, pcm: bytes, sample_rate: int) -> list[Word]:
        import numpy as np

        rec = self._load()
        stream = rec.create_stream()
        stream.accept_waveform(sample_rate, np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768.0)
        rec.decode_stream(stream)
        res = stream.result
        out: list[Word] = []
        stamps = list(getattr(res, "timestamps", []) or [])
        for k, tok in enumerate(res.tokens):
            t = stamps[k] if k < len(stamps) else None
            if tok.startswith(("▁", " ")) or not out:
                out.append(Word(tok.lstrip("▁ "), t, None, None))
            else:
                w = out[-1]
                out[-1] = Word(w.text + tok, w.start_s, t, None)
        return [w for w in out if w.text]


def create(settings) -> SherpaAsr:
    return SherpaAsr(settings)


def status(settings) -> tuple[str, str]:
    if not has_package("sherpa_onnx"):
        return "missing package", "uv pip install --python .venv sherpa-onnx==1.13.8"
    d = Path(settings.asr_model_dir)
    if not all((d / f).exists() for f in FILES):
        return "missing model", ("download sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8 from "
                                 "https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models into " + str(d))
    return "ok", ""
