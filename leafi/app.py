"""Composition root (overview.md): the only module that imports core, devices and services together.

It reads `config/devices.yml`, expands `${VAR}`, constructs the enabled adapters through the devices
registry, builds services from their registries, composes the voice Listener when an Ear and an ASR model
exist, and constructs the Hub.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from leafi import devices as device_registry
from leafi.core.config import Settings, env_lookup
from leafi.core.hub import DevicesConfig, DeviceSpec, Hub, load_devices_config
from leafi.core.ports import Ear, Eye, Face, Listener, Mouth, Notifier

log = logging.getLogger("leafi.app")

_PORTS = {"eye": Eye, "mouth": Mouth, "face": Face, "listener": Listener, "notifier": Notifier, "ear": Ear}


@dataclass
class App:
    settings: Settings
    config: DevicesConfig
    hub: Hub
    devices: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def load_config(settings: Settings) -> DevicesConfig:
    return load_devices_config(settings.devices_file, lambda n: env_lookup(n, settings),
                               known_adapters=set(device_registry.ADAPTERS))


def build(
    settings: Settings,
    *,
    config: DevicesConfig | None = None,
    text_mode: bool = False,
    voice_policy: str | None = None,
    tts_backend: str | None = None,
    extra: dict[str, Any] | None = None,
) -> App:
    """Build the Hub. `extra` maps capability → {name: adapter} for tests and scripted runs."""
    cfg = config or load_config(settings)
    warnings = list(cfg.warnings)
    slots: dict[str, dict[str, Any]] = {k: {} for k in _PORTS}
    devices: dict[str, Any] = {}
    for spec in cfg.enabled():
        obj = _construct(spec, settings, warnings)
        if obj is None:
            continue
        devices[spec.name] = obj
        for cap in spec.capabilities:
            if cap == "presence":
                continue
            if not isinstance(obj, _PORTS[cap]):
                warnings.append(f"device {spec.name!r}: adapter {spec.adapter!r} does not provide {cap}")
                continue
            slots[cap][spec.name] = obj
    for cap, named in (extra or {}).items():
        slots[cap].update(named)

    if not slots["listener"] or not slots["face"]:
        from leafi.devices.console import ConsoleDevice

        console = ConsoleDevice("console")
        slots["listener"].setdefault("console", console)
        slots["face"].setdefault("console", console)

    study_listener = cfg.study_listener
    if text_mode:
        slots["listener"] = {n: lis for n, lis in slots["listener"].items() if not getattr(lis, "is_voice", False)}
        study_listener = next(iter(slots["listener"]), None)
    elif study_listener not in slots["listener"]:
        voice = _compose_voice_listener(settings, slots["ear"].get(study_listener or ""), warnings)
        if voice is not None:
            slots["listener"][study_listener] = voice
        else:
            fallback = next(iter(slots["listener"]))
            warnings.append(f"study listener {study_listener!r} unavailable; using {fallback!r} (text)")
            study_listener = fallback

    policy = voice_policy or ("none" if text_mode else cfg.voice_policy)
    synthesizer = None
    if policy != "none" and slots["mouth"]:
        from leafi.services import tts

        backend = tts_backend
        synthesizer = tts.create(settings, en=backend, zh=backend) if backend else tts.create(settings)
    hub = Hub(mouths=slots["mouth"], faces=slots["face"], eyes=slots["eye"], listeners=slots["listener"],
              notifiers=slots["notifier"], synthesizer=synthesizer, policy=policy,
              primary_mouth=cfg.primary_mouth, study_eye=cfg.study_eye, study_listener=study_listener,
              say_timeout_s=settings.say_timeout_s)
    for w in warnings:
        log.warning(w)
    return App(settings, cfg, hub, devices, warnings)


def _construct(spec: DeviceSpec, settings: Settings, warnings: list[str]) -> Any | None:
    try:
        cls = device_registry.factory(spec.adapter)
        return cls(spec.name, spec.options, settings)
    except Exception as e:  # an adapter that cannot be built is disabled, never fatal
        warnings.append(f"device {spec.name!r} disabled: {type(e).__name__}: {e}")
        return None


def _compose_voice_listener(settings: Settings, ear: Ear | None, warnings: list[str]) -> Listener | None:
    if ear is None:
        return None
    from leafi.services import asr

    state, detail = asr.REGISTRY.status(settings.asr_backend, settings)
    if state != "ok":
        warnings.append(f"voice listener off: asr {settings.asr_backend} {state} {detail}".strip())
        return None
    recognizer = asr.REGISTRY.create(settings.asr_backend, settings)
    vad = None
    if settings.asr_backend != "mock":
        from leafi.services.asr import vad as vad_module

        state, detail = vad_module.status(settings)
        if state == "ok":
            vad = vad_module.create(settings, threshold=settings.vad_threshold, min_silence_s=settings.vad_silence_s)
        else:
            warnings.append(f"Silero VAD {state} ({detail}); using the energy end-pointer")
    return asr.VoiceListener(ear, recognizer, pause_s=settings.sentence_pause_s, vad=vad)
