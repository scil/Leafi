"""Small WAV helpers shared by TTS backends and Mouth adapters (standard library only)."""

from __future__ import annotations

import wave
from pathlib import Path


def write_wav(path: Path, pcm: bytes, sample_rate: int, channels: int = 1) -> float:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return len(pcm) / (2 * channels * sample_rate)


def read_wav(path: Path) -> tuple[bytes, int, int]:
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate(), w.getnchannels()


def pad_wav(src: Path, dst: Path, head_s: float, tail_s: float) -> float:
    """Copy `src` to `dst` with silence before and after; returns the padded duration."""
    pcm, sr, ch = read_wav(src)
    head = b"\x00\x00" * ch * int(sr * head_s)
    tail = b"\x00\x00" * ch * int(sr * tail_s)
    return write_wav(dst, head + pcm + tail, sr, ch)


def silence(seconds: float, sample_rate: int = 16000) -> bytes:
    return b"\x00\x00" * int(sample_rate * seconds)
