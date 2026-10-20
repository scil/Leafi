---
status: accepted
date: 2026-10-19
---

# Sessions ask for capabilities; devices are adapters that provide several

## Context

The home may have zero, one or several mouths; a camera may also be a speaker; an ESP32 box is a microphone, a speaker and a screen at once; with no speaker at all the agent must still answer in text. The first track hard-wired "speaker = go2rtc push to the camera".

## Decision drivers

- Hardware changes without code changes (user requirement).
- The study loop must run in CI with no hardware.
- Prior art: Wyoming advertises services by domain (`asr`, `tts`, `mic`, `snd`), Home Assistant pipelines take `start_stage`/`end_stage`, xiaozhi treats one ESP32 as mic + speaker + subtitle screen.

## Considered options

1. One `Speaker` class with backends (status quo).
2. Device classes by brand (`XiaomiCamera`, `Esp32Box`) that the session picks from config.
3. Capability ports (`Eye`, `Ear`, `Mouth`, `Face`, `Presence`, `Notifier`, composed `Listener`) with a `Hub` that loads `config/devices.yml`; each device adapter implements any subset; `hub.say()` applies a voice policy and always writes to Faces.

## Decision outcome

Option 3. Ports are `typing.Protocol`s in `leafi/core/ports.py`. `Listener` is a composition (Ear + VAD + ASR) so a typed-text listener satisfies the same contract. Voice policy `all | primary | none`; zero Mouths is a valid configuration.

## Consequences

- One more indirection than the first track had; paid back the first time a second device appears.
- Adapters must be side-effect free at import time so the Hub can report "disabled, missing option" instead of crashing.
- Text output is first-class: every line is shown on Faces before audio.

## Confirmation

`tests/test_hub.py`: `say()` with 0, 1 and 2 Mouths; a device with a missing option is disabled with a warning; the study loop runs end to end with the console device only.
