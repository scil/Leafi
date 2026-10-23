"""`WordInfo`: what alignment may know about a word (ADR-0013 → Definitions), as a port so `align` stays pure.

Answers are precomputed by the caller (page tokens when the revision loads, heard words when the utterance
arrives) through `WordInfo.prepare`, then read from the cache inside `align`. `NullWordInfo` knows nothing,
which gives v1's behaviour: no word is "real" (so `sim ≥ 0.80` stays fuzzy credit), no phones, and every
word is only its own lemma. `TableWordInfo` serves tests. The local backend is
`leafi.services.wordinfo.LocalWordInfo` (word lists, espeak-ng phones, lemminflect).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol


class WordInfo(Protocol):
    versions: Mapping[str, str]

    def prepare(self, words: Iterable[str]) -> None: ...  # compute and cache answers for these normed words

    def is_word(self, w: str) -> bool: ...

    def phones(self, w: str) -> frozenset[str]: ...

    def lemmas(self, w: str) -> frozenset[str]: ...


class NullWordInfo:
    versions: Mapping[str, str] = {"wordinfo": "null"}

    def prepare(self, words: Iterable[str]) -> None:
        return None

    def is_word(self, w: str) -> bool:
        return False

    def phones(self, w: str) -> frozenset[str]:
        return frozenset()

    def lemmas(self, w: str) -> frozenset[str]:
        return frozenset({w})


class TableWordInfo:
    """Fixed answers: `words` are real words; `phones` and `lemmas` map a word to its sets."""

    def __init__(self, words: Iterable[str] = (), phones: Mapping[str, Iterable[str]] | None = None,
                 lemmas: Mapping[str, Iterable[str]] | None = None) -> None:
        self._words = frozenset(words)
        self._phones = {k: frozenset(v) for k, v in (phones or {}).items()}
        self._lemmas = {k: frozenset(v) for k, v in (lemmas or {}).items()}
        self.versions = {"wordinfo": "table"}

    def prepare(self, words: Iterable[str]) -> None:
        return None

    def is_word(self, w: str) -> bool:
        return w in self._words

    def phones(self, w: str) -> frozenset[str]:
        return self._phones.get(w, frozenset())

    def lemmas(self, w: str) -> frozenset[str]:
        return self._lemmas.get(w, frozenset()) | {w}
