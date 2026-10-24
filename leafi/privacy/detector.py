"""The name detector (ADR-0018 §3, M5 design D11): names nobody listed, found in a learner's own words.

Presidio's `AnalyzerEngine` over spaCy `en_core_web_sm` 3.8.0, built so nothing can reach the network: Leafi loads
the model from `models/spacy/` itself (Presidio's own loader downloads a model by name when it is not installed),
and the registry holds only the spaCy recognizer for PERSON, ORGANIZATION and LOCATION, so the URL and e-mail
recognizers that call `tldextract` never run. It runs on `learner` / `derived_from_learner` text only, when
`PRIVACY_NAME_DETECTOR` is on (the default). Owner decision 2026-10-23: with the model missing the detector is
off and replacement falls back to the lists, with a warning here and a `leafi doctor` line; that mode is not the
detector guarantee and is never reported as it.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from leafi.core.config import Settings

log = logging.getLogger("leafi.privacy.detector")

MODEL = "en_core_web_sm-3.8.0"
ENTITIES = {"PERSON": "[name]", "ORGANIZATION": "[organisation]", "LOCATION": "[place]"}
MIN_SCORE = 0.5


def model_dir(settings: Settings) -> Path:
    return Path(settings.models_dir) / "spacy" / MODEL


def wanted(settings: Settings) -> bool:
    return bool(getattr(settings, "privacy_name_detector", True))


def state(settings: Settings) -> str:
    """The effective state, shown apart from the configured value (design D11)."""
    if not wanted(settings):
        return "off"
    if not (model_dir(settings) / "meta.json").exists():
        return "on, model missing: list only"
    return "on"


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    replacement: str


class Detector:
    def __init__(self, path: Path) -> None:
        import spacy
        from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
        from presidio_analyzer.nlp_engine import SpacyNlpEngine
        from presidio_analyzer.predefined_recognizers.nlp_engine_recognizers.spacy_recognizer import (
            SpacyRecognizer,
        )

        class _Loaded(SpacyNlpEngine):
            """Presidio's spaCy engine around a pipeline Leafi loaded from a path: no download, no GPU probe."""

            def __init__(self, nlp) -> None:
                super().__init__(models=[{"lang_code": "en", "model_name": str(path)}])
                self.nlp = {"en": nlp}

            def load(self) -> None:  # never called: already loaded
                pass

        nlp = spacy.load(path, exclude=["parser", "lemmatizer"])
        engine = _Loaded(nlp)
        registry = RecognizerRegistry(recognizers=[SpacyRecognizer(supported_entities=list(ENTITIES))],
                                      supported_languages=["en"])
        self._engine = AnalyzerEngine(registry=registry, nlp_engine=engine, supported_languages=["en"])
        self._lock = threading.Lock()  # spaCy pipelines are not documented as thread-safe

    def spans(self, text: str) -> list[Span]:
        if not text.strip():
            return []
        with self._lock:
            found = self._engine.analyze(text=text, language="en", entities=list(ENTITIES),
                                         score_threshold=MIN_SCORE)
        return sorted((Span(r.start, r.end, ENTITIES[r.entity_type]) for r in found), key=lambda s: s.start)


_cache: dict[Path, Detector | None] = {}
_cache_lock = threading.Lock()


def load(settings: Settings) -> Detector | None:
    """The process's detector, or None (off, or the model missing: list-only, warned once)."""
    if not wanted(settings):
        return None
    path = model_dir(settings).resolve()
    with _cache_lock:
        if path in _cache:
            return _cache[path]
        if not (path / "meta.json").exists():
            log.warning("name detector on but %s is missing: only listed names are replaced (python -m leafi "
                        "doctor --download --only names)", path)
            _cache[path] = None
        else:
            _cache[path] = Detector(path)
        return _cache[path]
