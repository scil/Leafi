"""Mock ASR: returns scripted transcripts in order (no timestamps, conf None)."""

from __future__ import annotations

from leafi.core.ports import Word
from leafi.core.text import words


class MockAsr:
    def __init__(self, script: list[str] | None = None) -> None:
        self.script = list(script or [])
        self.calls = 0

    async def transcribe(self, pcm: bytes, sample_rate: int, hotwords: list[str] | None = None) -> list[Word]:
        self.calls += 1
        text = self.script.pop(0) if self.script else ""
        return [Word(w) for w in words(text)]


def create(settings, script: list[str] | None = None) -> MockAsr:
    return MockAsr(script)
