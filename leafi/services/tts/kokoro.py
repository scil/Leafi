"""Kokoro-onnx TTS (English, local, Apache-2.0 model). `kokoro_onnx` is imported on first synthesis.

Model files: `models/tts/kokoro-v1.0.onnx` and `models/tts/voices-v1.0.bin` (`python -m leafi doctor`).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from leafi.core.audio import write_wav
from leafi.core.ports import AudioClip
from leafi.services._registry import has_package

MODEL_FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")


def _paths(settings) -> tuple[Path, Path]:
    base = Path(settings.models_dir) / "tts"
    return base / MODEL_FILES[0], base / MODEL_FILES[1]


class KokoroTts:
    name = "kokoro"
    cloud = False
    model = "kokoro-v1.0"

    def __init__(self, settings, lang: str = "en") -> None:
        self.voice = settings.tts_voice_en_kokoro
        self._model_path, self._voices_path = _paths(settings)
        self._engine = None

    def _load(self):
        if self._engine is None:
            from kokoro_onnx import Kokoro  # lazy: onnxruntime + model load

            self._engine = Kokoro(str(self._model_path), str(self._voices_path))
        return self._engine

    async def synthesize(self, text: str, lang: str, slow: bool, out_base: Path) -> AudioClip:
        loop = asyncio.get_running_loop()

        def run() -> AudioClip:
            import numpy as np

            samples, sr = self._load().create(text, voice=self.voice, speed=0.8 if slow else 1.0, lang="en-us")
            pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
            path = out_base.with_suffix(".wav")
            dur = write_wav(path, pcm, int(sr))
            return AudioClip(path, dur, int(sr), 1, "wav")

        return await loop.run_in_executor(None, run)


def create(settings, lang: str = "en") -> KokoroTts:
    return KokoroTts(settings, lang)


def status(settings) -> tuple[str, str]:
    if not has_package("kokoro_onnx"):
        return "missing package", "uv pip install --python .venv kokoro-onnx==0.6.1"
    missing = [p.name for p in _paths(settings) if not p.exists()]
    if missing:
        return "missing model", ("download kokoro-v1.0.onnx and voices-v1.0.bin from "
                                 "https://github.com/thewh1teagle/kokoro-onnx/releases into models/tts/")
    return "ok", ""
