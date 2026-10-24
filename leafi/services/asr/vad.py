"""Silero VAD through sherpa-onnx: speech segments from 16 kHz mono int16 chunks (replaces the energy rule).

Model: `models/vad/silero_vad.onnx` (`python -m leafi doctor --download`). The detector consumes fixed
windows of 512 samples (32 ms); a segment is emitted once `min_silence_s` of silence follows speech, or at
`max_speech_s`. `flush()` closes an open segment (end of input). Nothing here touches the network.
"""

from __future__ import annotations

from pathlib import Path

from leafi.services._registry import has_package

MODEL_FILE = "silero_vad.onnx"
DOWNLOAD = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
WINDOW = 512


def model_path(settings) -> Path:
    return Path(settings.models_dir) / "vad" / MODEL_FILE


class SileroVad:
    def __init__(self, model: Path, *, threshold: float = 0.5, min_silence_s: float = 0.6,
                 min_speech_s: float = 0.25, max_speech_s: float = 20.0, sample_rate: int = 16000) -> None:
        import sherpa_onnx  # lazy

        cfg = sherpa_onnx.VadModelConfig(
            silero_vad=sherpa_onnx.SileroVadModelConfig(
                model=str(model), threshold=threshold, min_silence_duration=min_silence_s,
                min_speech_duration=min_speech_s, max_speech_duration=max_speech_s, window_size=WINDOW),
            sample_rate=sample_rate, num_threads=1)
        self._vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=max_speech_s + 10)
        self.sample_rate = sample_rate
        self._keep = int((max_speech_s + 10) * sample_rate)
        self._rest: bytes = b""
        self._fed = 0  # samples given to feed() since the last reset: sherpa's `seg.start` counts from there too
        self._marks: list[tuple[int, float]] = []  # (sample count after a chunk, that chunk's t)

    @property
    def speaking(self) -> bool:
        return bool(self._vad.is_speech_detected())

    def feed(self, pcm: bytes, t: float | None = None) -> list[tuple[bytes, float | None]]:
        """Push int16 PCM that arrived at `t`; return the segments completed so far as (int16 PCM, end_t)."""
        import numpy as np

        self._fed += len(pcm) // 2
        if t is not None:
            self._marks.append((self._fed, t))
            while len(self._marks) > 1 and self._marks[0][0] < self._fed - self._keep:
                self._marks.pop(0)
        data = self._rest + pcm
        usable = len(data) - len(data) % (2 * WINDOW)
        self._rest = data[usable:]
        if usable:
            x = np.frombuffer(data[:usable], dtype="<i2").astype("float32") / 32768.0
            for i in range(0, len(x), WINDOW):
                self._vad.accept_waveform(x[i:i + WINDOW])
        return self._drain()

    def flush(self) -> list[tuple[bytes, float | None]]:
        self._vad.flush()
        return self._drain()

    def reset(self) -> None:
        """sherpa-onnx 1.13.8's `reset()` restarts `seg.start` at 0 (measured 2026-10-24), so the count does too."""
        self._vad.reset()
        self._rest = b""
        self._fed, self._marks = 0, []

    def end_t(self, end_sample: int) -> float | None:
        """The time of sample `end_sample`: the `t` of the chunk holding it, less the samples after it."""
        for count, t in self._marks:
            if count >= end_sample:
                return t - (count - end_sample) / self.sample_rate
        return None

    def _drain(self) -> list[tuple[bytes, float | None]]:
        import numpy as np

        out = []
        while not self._vad.empty():
            seg = self._vad.front
            pcm = (np.clip(np.asarray(seg.samples, dtype="float32"), -1.0, 1.0) * 32767).astype("<i2").tobytes()
            out.append((pcm, self.end_t(seg.start + len(seg.samples))))
            self._vad.pop()
        return out


def create(settings, **kw) -> SileroVad:
    return SileroVad(model_path(settings), **kw)


def status(settings) -> tuple[str, str]:
    if not has_package("sherpa_onnx"):
        return "missing package", "uv pip install --python .venv sherpa-onnx==1.13.8"
    p = model_path(settings)
    if not p.exists():
        return "missing model", f"python -m leafi doctor --download  (fetches {DOWNLOAD} into {p.parent})"
    return "ok", ""
