"""TTS service: implements the core `Synthesizer` with one backend per language and a content-addressed cache.

Cache key = text + lang + voice + speed + model (device-routing.md), files under `cache/tts/` (90-day
retention, security.md). Backends: `kokoro` (en, local), `edge` (zh, cloud text-to-speech, egress table),
`mock` (silence, tests).
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


class LocalOnlyUnavailable(RuntimeError):
    """A local-only line (learner-originated text) with only cloud backends configured: no audio."""


class TtsBackend(Protocol):
    name: str
    cloud: bool  # True when synthesis sends the text off the LAN (egress table)
    voice: str
    model: str

    async def synthesize(self, text: str, lang: str, slow: bool, out_base: Path) -> AudioClip: ...


class TtsService:
    def __init__(self, backends: dict[str, TtsBackend], cache_dir: Path) -> None:
        self.backends = backends
        self.cache_dir = Path(cache_dir)

    def _backend(self, lang: str) -> TtsBackend:
        return self.backends.get(lang) or self.backends.get("en") or next(iter(self.backends.values()))

    async def synth(self, text: str, lang: str, *, slow: bool = False, local_only: bool = False) -> AudioClip:
        be = self._backend(lang)
        if local_only and getattr(be, "cloud", False):
            local = [b for b in self.backends.values() if not getattr(b, "cloud", False)]
            if not local:
                raise LocalOnlyUnavailable("line embeds learner text and no local TTS backend exists")
            be = local[0]
        speed = "slow" if slow else "normal"
        key = hashlib.sha256(f"{text}|{lang}|{be.voice}|{speed}|{be.name}:{be.model}".encode()).hexdigest()[:32]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        meta = self.cache_dir / f"{key}.json"
        if meta.exists():
            try:
                d = json.loads(meta.read_text(encoding="utf-8"))
                path = Path(d["path"])
                if path.exists():
                    return AudioClip(path, d["duration_s"], d["sample_rate"], d["channels"], d["codec"])
            except (OSError, ValueError, KeyError):
                pass
        clip = await be.synthesize(text, lang, slow, self.cache_dir / key)
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
    return TtsService(built, Path(settings.cache_dir) / "tts")
