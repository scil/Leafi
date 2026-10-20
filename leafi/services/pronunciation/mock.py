"""Mock scorer: a fixed score, or one chosen per expected word. No network, no model."""

from __future__ import annotations

from leafi.core.ports import AudioRef
from leafi.services.pronunciation import PronScore


class MockScorer:
    def __init__(self, score: float = 0.9, per_word: dict[str, float] | None = None) -> None:
        self.default = score
        self.per_word = per_word or {}
        self.calls: list[tuple[int, str]] = []

    async def score(self, audio: AudioRef, expected: str) -> PronScore | None:
        self.calls.append((len(audio.pcm), expected))
        return PronScore(self.per_word.get(expected, self.default), expected, None)


def create(settings, score: float = 0.9, per_word: dict[str, float] | None = None) -> MockScorer:
    return MockScorer(score, per_word)
