"""TTS service: implements the core `Synthesizer` with one backend per language and a content-addressed cache.

Cache key = text + lang + voice + speed + model (device-routing.md), files under `cache/tts/` (90-day
retention, security.md); each entry's sidecar records the line's provenance (ADR-0018 §3), on hits and misses.
Backends: `kokoro` (en, local), `edge` (zh, cloud text-to-speech through `leafi.privacy.egress`), `mock`
(silence, tests).

Routing by provenance (M5 design D13), after the per-language backend choice: while
`PRIVACY_TTS_LEARNER_LINES` is `local` (the default), a learner's own words, or any line holding a protected name,
go to a local backend — so edge-tts never speaks a surrogate; with no local backend the line raises
`LocalOnlyUnavailable` and the Hub shows it on Faces only.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Protocol

from leafi.core.ports import SYSTEM, AudioClip, Provenance
from leafi.services._registry import Registry

log = logging.getLogger("leafi.tts")

REGISTRY = Registry("tts", {
    "kokoro": "leafi.services.tts.kokoro",
    "edge": "leafi.services.tts.edge",
    "mock": "leafi.services.tts.mock",
})


class LocalOnlyUnavailable(RuntimeError):
    """A line that must stay local with only cloud backends configured: no audio."""


class TtsBackend(Protocol):
    name: str
    cloud: bool  # True when synthesis sends the text off the LAN (egress table)
    voice: str
    model: str

    async def synthesize(self, text: str, lang: str, slow: bool, out_base: Path) -> AudioClip: ...
    # a cloud backend also takes `provenance=` (keyword), for egress's prepare


class TtsService:
    def __init__(self, backends: dict[str, TtsBackend], cache_dir: Path, *, learner_lines: str = "local",
                 protected=None) -> None:
        self.backends = backends
        self.cache_dir = Path(cache_dir)
        self.learner_lines = learner_lines
        self._protected = protected  # text -> bool: holds a listed name (egress's lists); None: no lists

    def _backend(self, lang: str) -> TtsBackend:
        return self.backends.get(lang) or self.backends.get("en") or next(iter(self.backends.values()))

    def _must_stay_local(self, text: str, provenance: Provenance) -> bool:
        if self.learner_lines != "local":
            return False
        if provenance.learners_own:
            return True
        try:
            return bool(self._protected and self._protected(text))
        except Exception:  # the lists could not be read: fail closed
            log.warning("protected-name check failed; line kept local", exc_info=True)
            return True

    async def synth(self, text: str, lang: str, *, slow: bool = False, provenance: Provenance = SYSTEM) -> AudioClip:
        be = self._backend(lang)
        if getattr(be, "cloud", False) and self._must_stay_local(text, provenance):
            local = [b for b in self.backends.values() if not getattr(b, "cloud", False)]
            if not local:
                raise LocalOnlyUnavailable("line must stay local and no local TTS backend exists")
            be = local[0]
        speed = "slow" if slow else "normal"
        key = hashlib.sha256(f"{text}|{lang}|{be.voice}|{speed}|{be.name}:{be.model}".encode()).hexdigest()[:32]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        meta = self.cache_dir / f"{key}.json"
        sidecar = {"provenance_class": provenance.cls, "source_learners": sorted(provenance.sources)}
        if meta.exists():
            try:
                d = json.loads(meta.read_text(encoding="utf-8"))
                path = Path(d["path"])
                if path.exists():
                    if d.get("source_learners") != sidecar["source_learners"] or "provenance_class" not in d:
                        merged = sorted(set(d.get("source_learners", [])) | set(provenance.sources))
                        d.update(provenance_class=d.get("provenance_class", provenance.cls), source_learners=merged)
                        meta.write_text(json.dumps(d), encoding="utf-8")
                    return AudioClip(path, d["duration_s"], d["sample_rate"], d["channels"], d["codec"])
            except (OSError, ValueError, KeyError):
                pass
        kw = {"provenance": provenance} if getattr(be, "cloud", False) else {}  # a cloud backend prepares egress
        clip = await be.synthesize(text, lang, slow, self.cache_dir / key, **kw)
        meta.write_text(json.dumps({"path": str(clip.path), "duration_s": clip.duration_s,
                                    "sample_rate": clip.sample_rate, "channels": clip.channels,
                                    "codec": clip.codec, **sidecar}), encoding="utf-8")
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
    protected = None
    if any(getattr(b, "cloud", False) for b in built.values()):
        def protected(text: str, _s=settings) -> bool:
            from leafi.privacy import runtime

            return runtime.get(_s).contains_protected(text)
    return TtsService(built, Path(settings.cache_dir) / "tts",
                      learner_lines=getattr(settings, "privacy_tts_learner_lines", "local"), protected=protected)
