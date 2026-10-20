"""The Hub (ADR-0002): parses `config/devices.yml`, holds constructed adapters, routes `say()`.

Core never imports devices or services: the composition root (`leafi/app.py`) builds the adapters and the
`Synthesizer` and hands them to `Hub(...)`. `say()` shows text on every Face first, then plays on Mouths
per the voice policy, bounded by `say_timeout_s`; it never raises for a device error (device-routing.md).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .ports import Display, Eye, Face, Listener, Mouth, Notifier, Synthesizer

log = logging.getLogger("leafi.hub")

CAPABILITIES = {"eye", "ear", "mouth", "face", "presence", "notifier", "listener"}
VOICE_POLICIES = {"all", "primary", "none"}
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-([^}]*))?\}")


class DevicesConfigError(ValueError):
    pass


# ---------------------------------------------------------------- devices.yml


@dataclass
class DeviceSpec:
    name: str
    adapter: str
    capabilities: list[str]
    options: dict[str, Any] = field(default_factory=dict)
    disabled: str | None = None  # reason, when a required ${VAR} is missing


@dataclass
class DevicesConfig:
    version: int = 1
    voice_policy: str = "all"
    primary_mouth: str | None = None
    devices: list[DeviceSpec] = field(default_factory=list)
    study_eye: str | None = None
    study_listener: str | None = None
    warnings: list[str] = field(default_factory=list)

    def enabled(self) -> list[DeviceSpec]:
        return [d for d in self.devices if not d.disabled]


def _expand(value: Any, lookup: Callable[[str], str | None], missing: list[str]) -> Any:
    if isinstance(value, str):
        def repl(m: re.Match) -> str:
            name, has_default, default = m.group(1), m.group(2), m.group(3)
            got = lookup(name)
            if got is None or got == "":
                if has_default is not None:
                    return default or ""
                missing.append(name)
                return ""
            return got

        return _VAR_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand(v, lookup, missing) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v, lookup, missing) for v in value]
    return value


def parse_devices_config(
    data: dict, lookup: Callable[[str], str | None], known_adapters: set[str] | None = None
) -> DevicesConfig:
    if not isinstance(data, dict):
        raise DevicesConfigError("devices.yml must be a mapping")
    cfg = DevicesConfig(version=int(data.get("version", 1)))
    if cfg.version != 1:
        raise DevicesConfigError(f"devices.yml version {cfg.version} is not supported (expected 1)")
    cfg.voice_policy = str(data.get("voice_policy", "all"))
    if cfg.voice_policy not in VOICE_POLICIES:
        raise DevicesConfigError(f"voice_policy {cfg.voice_policy!r} not in {sorted(VOICE_POLICIES)}")
    cfg.primary_mouth = data.get("primary_mouth")
    seen: set[str] = set()
    for raw in data.get("devices") or []:
        name = raw.get("name")
        if not name:
            raise DevicesConfigError("every device needs a name")
        if name in seen:
            raise DevicesConfigError(f"device {name!r} declared twice")
        seen.add(name)
        adapter = raw.get("adapter")
        if not adapter or (known_adapters is not None and adapter not in known_adapters):
            raise DevicesConfigError(f"device {name!r}: unknown adapter {adapter!r}")
        caps = list(raw.get("capabilities") or [])
        bad = [c for c in caps if c not in CAPABILITIES]
        if bad:
            raise DevicesConfigError(f"device {name!r}: unknown capability {bad}")
        missing: list[str] = []
        options = _expand(raw.get("options") or {}, lookup, missing)
        spec = DeviceSpec(name, adapter, caps, options)
        if missing:
            spec.disabled = "missing " + ", ".join(f"${{{m}}}" for m in missing)
            cfg.warnings.append(f"device {name!r} disabled: {spec.disabled}")
        cfg.devices.append(spec)
    study = data.get("study") or {}
    cfg.study_eye = study.get("eye")
    cfg.study_listener = study.get("listener")
    return cfg


def load_devices_config(
    path: Path, lookup: Callable[[str], str | None], known_adapters: set[str] | None = None
) -> DevicesConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return parse_devices_config(data, lookup, known_adapters)


# ---------------------------------------------------------------- Hub


class Hub:
    def __init__(
        self,
        *,
        mouths: dict[str, Mouth] | None = None,
        faces: dict[str, Face] | None = None,
        eyes: dict[str, Eye] | None = None,
        listeners: dict[str, Listener] | None = None,
        notifiers: dict[str, Notifier] | None = None,
        synthesizer: Synthesizer | None = None,
        policy: str = "all",
        primary_mouth: str | None = None,
        study_eye: str | None = None,
        study_listener: str | None = None,
        say_timeout_s: float = 20.0,
        face_timeout_s: float = 2.0,
    ) -> None:
        if policy not in VOICE_POLICIES:
            raise ValueError(f"voice policy {policy!r}")
        self.mouths = dict(mouths or {})
        self.faces = dict(faces or {})
        self.eyes = dict(eyes or {})
        self.listeners = dict(listeners or {})
        self.notifiers = dict(notifiers or {})
        self.synthesizer = synthesizer
        self.policy = policy
        self.primary_mouth = primary_mouth
        self.study_eye = study_eye
        self.study_listener = study_listener
        self.say_timeout_s = say_timeout_s
        self.face_timeout_s = face_timeout_s
        self._lock = asyncio.Lock()
        self._generation = 0
        self._playing: dict[str, Mouth] = {}
        self._play_tasks: list[asyncio.Task] = []

    # ---- selection
    def listener(self) -> Listener:
        if self.study_listener and self.study_listener in self.listeners:
            return self.listeners[self.study_listener]
        for lis in self.listeners.values():
            if not getattr(lis, "is_voice", False):
                return lis
        if self.listeners:
            return next(iter(self.listeners.values()))
        raise LookupError("no Listener configured (the console device provides one)")

    def eye(self) -> Eye | None:
        if self.study_eye:
            return self.eyes.get(self.study_eye)
        return next(iter(self.eyes.values()), None)

    def _target_mouths(self) -> dict[str, Mouth]:
        if self.policy == "none" or not self.mouths:
            return {}
        if self.policy == "primary":
            if self.primary_mouth in self.mouths:
                return {self.primary_mouth: self.mouths[self.primary_mouth]}
            name = next(iter(self.mouths))
            log.warning("primary mouth %r missing; using %r", self.primary_mouth, name)
            return {name: self.mouths[name]}
        return dict(self.mouths)

    # ---- output
    async def show(self, msg: Display) -> None:
        async def one(name: str, face: Face) -> None:
            try:
                await asyncio.wait_for(face.show(msg), self.face_timeout_s)
            except Exception:
                log.warning("face %s failed or hung", name, exc_info=True)

        await asyncio.gather(*(one(n, f) for n, f in self.faces.items()))

    async def say(self, text: str, lang: str = "en", *, slow: bool = False, local_only: bool = False) -> float:
        """Faces first, then TTS → Mouths per policy. Returns the max drain_s of the Mouths that played."""
        generation = self._generation
        async with self._lock:
            if generation != self._generation:  # cleared by stop_speaking() while queued
                return 0.0
            await self.show(Display("say", text, lang))
            targets = self._target_mouths()
            if not targets or self.synthesizer is None:
                if not targets:
                    log.info("say (no mouth): %d chars", len(text))
                return 0.0
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.say_timeout_s
            try:
                clip = await asyncio.wait_for(self.synthesizer.synth(text, lang, slow=slow, local_only=local_only),
                                              self.say_timeout_s)
            except Exception:
                log.error("TTS failed; text shown on Faces only", exc_info=True)
                return 0.0
            if generation != self._generation:
                return 0.0
            self._playing = dict(targets)
            tasks = {name: asyncio.create_task(self._play(name, m, clip)) for name, m in targets.items()}
            self._play_tasks = list(tasks.values())
            remaining = max(0.0, deadline - loop.time())
            done, pending = await asyncio.wait(tasks.values(), timeout=remaining)
            for name, task in tasks.items():
                if task in pending:
                    log.warning("mouth %s exceeded say timeout; cancelling", name)
                    task.cancel()
                    await self._stop_mouth(name, targets[name])
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self._playing = {}
            self._play_tasks = []
            return max((float(getattr(m, "drain_s", 0.0)) for m in targets.values()), default=0.0)

    async def _play(self, name: str, mouth: Mouth, clip) -> None:
        try:
            await mouth.play(clip)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.error("mouth %s failed", name, exc_info=True)

    async def _stop_mouth(self, name: str, mouth: Mouth) -> None:
        try:
            await asyncio.wait_for(mouth.stop(), 2.0)
        except Exception:
            log.warning("mouth %s stop failed", name, exc_info=True)

    async def stop_speaking(self) -> None:
        """Clear queued say() calls and cancel the current clip on every Mouth."""
        self._generation += 1
        for task in list(self._play_tasks):
            task.cancel()
        for name, mouth in list(self._playing.items()):
            await self._stop_mouth(name, mouth)

    async def notify(self, title: str, body: str) -> None:
        for name, n in self.notifiers.items():
            try:
                await n.notify(title, body)
            except Exception:
                log.error("notifier %s failed", name, exc_info=True)


class ListeningGate:
    """Session-owned half-duplex switch: the Listener is paused while any Mouth plays (device-routing.md)."""

    def __init__(self, listener: Listener) -> None:
        self.listener = listener
        self.is_open = True

    async def speak(self, hub: Hub, text: str, lang: str = "en", *, slow: bool = False,
                    local_only: bool = False) -> None:
        await self.listener.pause()
        self.is_open = False
        drain = 0.0
        try:
            drain = await hub.say(text, lang, slow=slow, local_only=local_only)
        finally:
            await self.listener.resume(after_s=drain)
            self.is_open = True
