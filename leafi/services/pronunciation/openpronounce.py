"""OpenPronounce 0.3.0 backend (prototype P-4, 2026-10-20). Imported lazily; everything runs offline.

How the library is held to ADR-0011 (reference voice Kokoro, gTTS off, checkpoints pre-provisioned):
- Checkpoints: `facebook/wav2vec2-large-960h` (word CTC + embeddings) and `facebook/wav2vec2-lv-60-espeak-cv-ft`
  (phone recognizer) live in the Hugging Face cache under `models/pronunciation/hf` (`doctor --download`);
  `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1` are set before the first load, so inference never fetches.
- Reference voice: the library picks its TTS from `OPENPRONOUNCE_TTS` and a registry dict; a `leafi` entry is
  registered that synthesises with Leafi's own Kokoro-onnx engine (24 kHz float32), so gTTS is never called.
- Phonemizer: espeak-ng comes from `espeakng-loader` (a kokoro-onnx dependency); its DLL and data paths are
  exported as `PHONEMIZER_ESPEAK_LIBRARY` / `ESPEAK_DATA_PATH` when the owner has no system espeak.
- Device: torch picks CUDA when available (`OPENPRONOUNCE_DEVICE` overrides).
The score is the library's 0–100 composite (acoustic DTW 30 %, phones 40 %, words 30 %) mapped to 0–1.
`PRON_AUTO_JUDGE` stays false until the parent-labelled evaluation (docs/engineering/pronunciation-evaluation.md).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from leafi.core.config import export_for_libraries
from leafi.core.ports import AudioRef
from leafi.services._registry import has_package
from leafi.services.pronunciation import PronScore

log = logging.getLogger("leafi.pron")

HF_REPOS = ("facebook/wav2vec2-large-960h", "facebook/wav2vec2-lv-60-espeak-cv-ft")
HF_SUBDIR = "hf"
BACKEND_NAME = "leafi"


def hf_dir(settings) -> Path:
    return Path(settings.models_dir) / "pronunciation" / HF_SUBDIR


def snapshot_dirs(settings) -> list[Path]:
    return [hf_dir(settings) / ("models--" + repo.replace("/", "--")) / "snapshots" for repo in HF_REPOS]


def _weights_present(snap: Path) -> bool:
    return snap.exists() and any(p.suffix in (".safetensors", ".bin") for p in snap.rglob("*") if p.is_file())


class OpenPronounceScorer:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.hf_dir = hf_dir(settings)
        self.cache_dir = Path(settings.cache_dir) / "pron"
        self._ready = False
        self._tts = None

    def _prepare(self) -> None:
        """Process environment for the library (written through `config.export_for_libraries`, the one
        sanctioned writer): offline hubs, our reference voice, bundled espeak."""
        if self._ready:
            return
        env = {"HF_HUB_CACHE": str(self.hf_dir), "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
               "OPENPRONOUNCE_CACHE_DIR": str(self.cache_dir), "OPENPRONOUNCE_TTS": BACKEND_NAME}
        try:
            import espeakng_loader

            env["PHONEMIZER_ESPEAK_LIBRARY"] = str(espeakng_loader.get_library_path())
            env["ESPEAK_DATA_PATH"] = str(espeakng_loader.get_data_path())
        except ImportError:
            log.warning("espeakng-loader missing; phonemizer needs a system espeak-ng")
        export_for_libraries(env, force={"HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "OPENPRONOUNCE_TTS"})
        from openpronounce import tts as op_tts

        op_tts.BACKENDS[BACKEND_NAME] = (self._synth_reference, lambda lang: self.settings.tts_voice_en_kokoro)
        self._ready = True

    def _synth_reference(self, text: str, lang: str, voice: str):
        """OpenPronounce TTS backend contract: (mono float32 waveform, sample_rate)."""
        import numpy as np

        if self._tts is None:
            from leafi.services.tts.kokoro import KokoroTts

            self._tts = KokoroTts(self.settings)._load()
        samples, sr = self._tts.create(text, voice=voice, speed=1.0, lang="en-us")
        return np.asarray(samples, dtype="float32"), int(sr)

    async def score(self, audio: AudioRef, expected: str) -> PronScore | None:
        if not audio.pcm or not expected.strip():
            return None
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._score, audio, expected)

    def _score(self, audio: AudioRef, expected: str) -> PronScore:
        import numpy as np

        self._prepare()
        import openpronounce

        x = np.frombuffer(audio.pcm, dtype="<i2").astype("float32") / 32768.0
        if audio.sample_rate != 16000:
            import soxr

            x = soxr.resample(x, audio.sample_rate, 16000).astype("float32")
        res = openpronounce.compare_audio_with_text(x, expected, 16000, lang="en")
        diff = res.get("differences", {})
        heard = diff.get("heard_phones") or diff.get("transcribed_phonemes") or []
        exp = diff.get("expected_phones") or diff.get("expected_phonemes") or []
        return PronScore(float(res["score"]) / 100.0, " ".join(map(str, exp)) or None, " ".join(map(str, heard)) or None)


def create(settings) -> OpenPronounceScorer:
    return OpenPronounceScorer(settings)


def status(settings) -> tuple[str, str]:
    if not has_package("openpronounce"):
        return "missing package", "uv pip install --python .venv openpronounce==0.3.0"
    if not has_package("torch"):
        return "missing package", "torch (installed with openpronounce; reinstall requirements-study.txt)"
    missing = [repo for repo, snap in zip(HF_REPOS, snapshot_dirs(settings), strict=True) if not _weights_present(snap)]
    if missing:
        return "missing model", f"python -m leafi doctor --download  (fetches {', '.join(missing)} into {hf_dir(settings)})"
    note = "auto judgement off unless PRON_AUTO_JUDGE=true"
    if not has_package("espeakng_loader"):
        note += "; WARNING: espeakng-loader missing (phonemizer then needs a system espeak-ng)"
    return "ok", note
