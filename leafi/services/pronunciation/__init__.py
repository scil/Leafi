"""Pronunciation service (S3 shell). Scores one practised word from in-memory learner audio.

Used only in Practice and only when `PRON_AUTO_JUDGE` is on (default off until the ADR-0011 evaluation).
Backends: `openpronounce` (wav2vec2 phonemes, offline reference voice, lazy) and `mock`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from leafi.core.ports import AudioRef
from leafi.services._registry import Registry

REGISTRY = Registry("pronunciation", {
    "openpronounce": "leafi.services.pronunciation.openpronounce",
    "mock": "leafi.services.pronunciation.mock",
})


@dataclass(frozen=True)
class PronScore:
    score: float  # 0..1, higher = closer to the reference
    phonemes_expected: str | None = None
    phonemes_heard: str | None = None


class Scorer(Protocol):
    async def score(self, audio: AudioRef, expected: str) -> PronScore | None: ...
