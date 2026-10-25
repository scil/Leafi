"""TTS service: implements the core `Synthesizer` with one backend per language and a content-addressed cache.

Cache key = text + lang + voice + speed + model (device-routing.md), files under `cache/tts/learners/<id>/` for
the learner the session's egress attribution names, or `cache/tts/shared/` with none (ADR-0021 E9: `forget` and
the session-start sweep delete a learner's folder; 90-day retention, security.md). The habit track's files at the
root of `cache/tts/` are never touched here. Backends: `kokoro` (en, local), `edge` (zh, cloud text-to-speech
through `leafi.privacy.egress`), `mock` (silence, tests).

Routing by content (ADR-0021 E7, after M5 design D13), after the per-language backend choice: a line holding a
listed name, or a name the detector finds in a non-book line, goes to a local backend — so edge-tts never speaks a
surrogate; with no local backend the line raises `LocalOnlyUnavailable` and the Hub shows it on Faces only. Where a
text came from no longer matters.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Protocol

from leafi.core.ports import AudioClip
from leafi.services._registry import Registry

log = logging.getLogger("leafi.tts")

REGISTRY = Registry("tts", {
    "kokoro": "leafi.services.tts.kokoro",
    "edge": "leafi.services.tts.edge",
    "mock": "leafi.services.tts.mock",
})


EDGE_MODES = ("library",)  # TTS_EDGE_MODE; `mediated` (ADR-0018 §2) is not built yet


class LocalOnlyUnavailable(RuntimeError):
    """A line that must stay local with only cloud backends configured: no audio."""


class TtsBackend(Protocol):
    name: str
    cloud: bool  # True when synthesis sends the text off the LAN (egress table)
    voice: str
    model: str

    async def synthesize(self, text: str, lang: str, slow: bool, out_base: Path) -> AudioClip: ...
    # a cloud backend also takes `book=` (keyword), for egress's prepare (ADR-0021 E2)


class TtsService:
    def __init__(self, backends: dict[str, TtsBackend], cache_dir: Path, *, names=None) -> None:
        self.backends = backends
        self.cache_dir = Path(cache_dir)
        self._names = names  # (text, book) -> bool: a listed or detected name (egress); None: no cloud backend

    def _backend(self, lang: str) -> TtsBackend:
        return self.backends.get(lang) or self.backends.get("en") or next(iter(self.backends.values()))

    def _must_stay_local(self, text: str, book: bool) -> bool:
        try:
            return bool(self._names and self._names(text, book))
        except Exception:  # the lists or the detector could not be read: fail closed
            log.warning("name check failed; line kept local", exc_info=True)
            return True

    def folder(self) -> Path:
        """The cache folder of the learner the session's attribution names, read before any await (ADR-0021 E9):
        `adopt()` moves the attribution in place, so clips before adoption stay under the guest's folder."""
        from leafi.privacy import runtime

        att = runtime.attribution.get()
        return self.cache_dir / ("learners" if att is not None else "") / (str(att.learner_id) if att else "shared")

    async def synth(self, text: str, lang: str, *, slow: bool = False, book: bool = False) -> AudioClip:
        """`book`: a book line, which the name detector skips; the lists still apply (ADR-0021 E2)."""
        folder = self.folder()
        be = self._backend(lang)
        if getattr(be, "cloud", False) and self._must_stay_local(text, book):
            local = [b for b in self.backends.values() if not getattr(b, "cloud", False)]
            if not local:
                raise LocalOnlyUnavailable("line must stay local and no local TTS backend exists")
            be = local[0]
        speed = "slow" if slow else "normal"
        key = hashlib.sha256(f"{text}|{lang}|{be.voice}|{speed}|{be.name}:{be.model}".encode()).hexdigest()[:32]
        folder.mkdir(parents=True, exist_ok=True)
        meta = folder / f"{key}.json"
        if meta.exists():
            try:
                d = json.loads(meta.read_text(encoding="utf-8"))
                path = Path(d["path"])
                if path.exists():
                    return AudioClip(path, d["duration_s"], d["sample_rate"], d["channels"], d["codec"])
            except (OSError, ValueError, KeyError):
                pass
        kw = {"book": book} if getattr(be, "cloud", False) else {}  # a cloud backend prepares egress
        clip = await be.synthesize(text, lang, slow, folder / key, **kw)
        meta.write_text(json.dumps({"path": str(clip.path), "duration_s": clip.duration_s,
                                    "sample_rate": clip.sample_rate, "channels": clip.channels,
                                    "codec": clip.codec}), encoding="utf-8")
        return clip


def create(settings: Any, *, en: str | None = None, zh: str | None = None) -> TtsService:
    """Build the TtsService from settings (`TTS_BACKEND_EN` / `TTS_BACKEND_ZH`) or explicit names."""
    names = {"en": en or settings.tts_backend_en, "zh": zh or settings.tts_backend_zh}
    built: dict[str, Any] = {}
    cache: dict[str, Any] = {}
    for lang, name in names.items():
        key = f"{name}:{lang}"
        if key not in cache:
            cache[key] = REGISTRY.create(name, settings, lang=lang)
        built[lang] = cache[key]
    names = None
    if any(getattr(b, "cloud", False) for b in built.values()):
        def names(text: str, book: bool, _s=settings) -> bool:
            from leafi.privacy import runtime

            return runtime.get(_s).names_in(text, book=book)
    return TtsService(built, Path(settings.cache_dir) / "tts", names=names)
