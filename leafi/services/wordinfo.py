"""Local `WordInfo` backend (ADR-0013 → Definitions; plan M0.2, M0.3): word lists, espeak-ng phones,
lemminflect lemmas. Everything runs offline; nothing here opens a socket.

- `is_word`: the household lexicon ∪ the word lists under `models/wordlists/` (SCOWL size-60 `en_GB-ise.txt`,
  `en_US.txt`, a CYP-LEX extract `cyplex.txt`; one word per line, fetched by `leafi doctor --download`), or,
  when no list is installed, a word lemminflect's dictionary knows.
- `phones`: espeak-ng through `phonemizer` (the `espeakng-loader` DLL), stress marks removed, plus the second
  pronunciation of a few homographs; empty when the phonemizer cannot load.
- `lemmas`: `{w} ∪ lemminflect.getAllLemmas(w)` over every part of speech (OOV rules off), minus the
  overrides below (plan Decision log, M0.3).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from leafi.core.config import export_for_libraries

log = logging.getLogger("leafi.wordinfo")

OVERRIDES_VERSION = "1"
# Look-alike links lemminflect makes that ADR-0013 must not read as inflections: (word, lemma to drop).
LEMMA_OVERRIDES = frozenset({("number", "numb"), ("liver", "live"), ("feed", "fee"), ("gamer", "game"),
                             ("stranger", "strange")})
HOMOGRAPHS_VERSION = "1"
# A spelling whose phones are a homograph's second pronunciation (read /red/, lead /led/, live /lɪv/ …).
HOMOGRAPHS = {"read": ("red",), "lead": ("led",), "live": ("liv",), "wind": ("wined",), "tear": ("tare",),
              "bow": ("bough", "beau"), "close": ("cloze",), "wound": ("wownd",)}
WORDLIST_FILES = ("en_GB-ise.txt", "en_US.txt", "cyplex.txt")


class LocalWordInfo:
    def __init__(self, models_dir: Path, lexicon: Iterable[str] = ()) -> None:
        self.lexicon = frozenset(lexicon)
        self.words: frozenset[str] | None = None
        found = []
        words: set[str] = set()
        for name in WORDLIST_FILES:
            p = Path(models_dir) / "wordlists" / name
            if p.exists():
                words.update(x.strip().lower() for x in p.read_text(encoding="utf-8").splitlines() if x.strip())
                found.append(name)
        if found:
            self.words = frozenset(words)
        self._phones: dict[str, frozenset[str]] = {}
        self._lemmas: dict[str, frozenset[str]] = {}
        self._phonemize = self._load_phonemizer()
        try:
            import lemminflect  # noqa: F401 - checked here, used lazily

            lem_v = "lemminflect-0.2.3"
            self._lem_ok = True
        except ImportError:
            lem_v, self._lem_ok = "none", False
        self.versions = {"wordlists": ",".join(found) or "none", "lemmas": f"{lem_v}+overrides-{OVERRIDES_VERSION}",
                         "phones": f"espeak+homographs-{HOMOGRAPHS_VERSION}" if self._phonemize else "none"}

    # ---- loading
    @staticmethod
    def _load_phonemizer():
        try:
            import espeakng_loader

            export_for_libraries({"PHONEMIZER_ESPEAK_LIBRARY": str(espeakng_loader.get_library_path()),
                                  "ESPEAK_DATA_PATH": str(espeakng_loader.get_data_path())})
            from phonemizer.backend import EspeakBackend

            backend = EspeakBackend("en-us", with_stress=False)
        except Exception:  # noqa: BLE001 - no phonemizer: the phone test is skipped (ADR-0013)
            log.warning("espeak-ng phonemizer unavailable; WordInfo.phones is empty")
            return None

        def run(words: list[str]) -> list[str]:
            return [p.strip().replace("ˈ", "").replace("ˌ", "") for p in backend.phonemize(words, strip=True)]

        return run

    def _lemmas_of(self, w: str) -> frozenset[str]:
        out = {w}
        if self._lem_ok:
            from lemminflect import getAllLemmas

            for forms in getAllLemmas(w).values():
                out.update(forms)
        out -= {lem for word, lem in LEMMA_OVERRIDES if word == w}
        return frozenset(out)

    # ---- WordInfo
    def prepare(self, words: Iterable[str]) -> None:
        new = sorted({w for w in words if w and w not in self._phones})
        if not new:
            return
        if self._phonemize is not None:
            extra = sorted({alt for w in new for alt in HOMOGRAPHS.get(w, ())})
            ph = dict(zip(new + extra, self._phonemize(new + extra), strict=True))
            for w in new:
                self._phones[w] = frozenset(p for p in [ph[w], *(ph[a] for a in HOMOGRAPHS.get(w, ()))] if p)
        else:
            for w in new:
                self._phones[w] = frozenset()

    def is_word(self, w: str) -> bool:
        if w in self.lexicon:
            return True
        if self.words is not None:
            return w in self.words
        if not self._lem_ok:
            return False
        from lemminflect import getAllLemmas

        return bool(getAllLemmas(w))

    def phones(self, w: str) -> frozenset[str]:
        if w not in self._phones:
            self.prepare([w])
        return self._phones[w]

    def lemmas(self, w: str) -> frozenset[str]:
        if w not in self._lemmas:
            self._lemmas[w] = self._lemmas_of(w)
        return self._lemmas[w]
