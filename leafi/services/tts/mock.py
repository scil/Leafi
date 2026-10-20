"""Mock TTS: a silent WAV whose length grows with the text. No network, no model."""

from __future__ import annotations

from pathlib import Path

from leafi.core.audio import silence, write_wav
from leafi.core.ports import AudioClip


class MockTts:
    name = "mock"
    cloud = False
    model = "silence-1"

    def __init__(self, lang: str = "en") -> None:
        self.voice = f"mock-{lang}"
        self.calls: list[tuple[str, str, bool]] = []

    async def synthesize(self, text: str, lang: str, slow: bool, out_base: Path) -> AudioClip:
        self.calls.append((text, lang, slow))
        seconds = 0.2 + 0.04 * len(text) * (1.5 if slow else 1.0)
        path = out_base.with_suffix(".wav")
        dur = write_wav(path, silence(seconds), 16000)
        return AudioClip(path, dur, 16000, 1, "wav")


def create(settings, lang: str = "en") -> MockTts:
    return MockTts(lang)
