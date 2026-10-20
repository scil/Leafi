# Architecture overview

Diagrams: [`c4-context.md`](c4-context.md), [`c4-container.md`](c4-container.md). Flows: [`flows/`](flows/). Decisions: [`../adr/`](../adr/).

## Shape

Leafi is one Python process (plus Frigate/mosquitto containers and a host go2rtc) organised in four rings. Dependencies point inward only.

```
tracks (study, habits)  →  services (asr, tts, ocr, pronunciation, brain, vision)
        ↓                          ↓
      core (ports, hub, config, storage, events)
        ↑
devices (adapters: go2rtc camera, local pc, console, frigate, xiaozhi, wyoming, notifiers)
```

- **core** owns the capability ports (`Eye`, `Ear`, `Mouth`, `Face`, `Presence`, `Notifier`, `Listener`), the `Hub` that loads `config/devices.yml`, settings, SQLite access, and the `say()` routing with the voice policy. It imports nothing from the other rings.
- **devices** implements ports for real hardware. Each adapter is one file; it may implement several ports. Adapters never contain tutoring logic.
- **services** wrap models behind small interfaces with a backend registry: `asr`, `tts`, `ocr`, `pronunciation`, `brain`, `vision`. Every service has a `mock` backend; backends are chosen by config.
- **tracks** hold the behaviour: `study` (book study state machine, alignment, coaching, knowledge, Anki) and `habits` (today still the legacy `agent/` package).

## Package layout (target)

```
leafi/
  core/        ports.py hub.py config.py storage.py audio.py text.py
  devices/     go2rtc_camera.py local_pc.py console.py frigate_presence.py notifiers.py xiaozhi_server.py (later) wyoming.py (later)
  services/    asr/ tts/ ocr/ pronunciation/ brain/ vision/   (each: __init__.py with the Protocol + registry, one module per backend, mock.py)
  study/       books.py pages.py page_tracker.py alignment.py miscues.py coach.py session.py knowledge.py anki.py review.py corrections.py lexicon.py
  cli.py       python -m leafi <command>
agent/         legacy habit track; unchanged until T2 (product.md) migrates it onto the Hub
```

## Boundaries and rules

1. `leafi.core` imports no `leafi.devices`, `leafi.services` or `leafi.study`. Enforced by `tests/test_architecture.py` (import graph check).
2. A track never imports a device adapter or a model backend module directly; it asks the Hub for capabilities and the service registry for a service. Enforced by the same test.
3. Any call that leaves the LAN goes through `services/brain` (text) or `devices/notifiers` (text + one frame to the parent's own phone). Everything else is LAN-only. Enforced by `tests/test_privacy.py` (allow-list of modules that may import `anthropic`/`httpx` with public hosts) and review.
4. Prompts to the Brain contain no image and no learner identity; they are built by `study/coach.py` from Page text and Miscues only. Enforced by a test that asserts the prompt builder's output schema has no image/identity fields.
5. Corrected Page text wins over OCR, always. Enforced by `tests/test_pages.py`.

## Runtime picture

1. `python -m leafi study` starts the Hub (loads devices), warms services in the background, then runs the `study.session` state machine: identify book → find page → read loop → practice → check → wrap.
2. The read loop asks the `Listener` for the next Utterance (audio → VAD → ASR, or typed text), aligns it to the Page text, stores Verdicts and Miscues, and asks `coach` what to say; `coach` may call the Brain with a text-only context and a strict output schema.
3. `hub.say()` turns the line into audio through `services/tts` and plays it on every Mouth per policy, and shows the text on every Face.
4. Habit tasks keep running from `agent/main.py` unchanged until they are migrated.

## Design principles

- Deep modules, small interfaces (Matt Pocock's `codebase-design` vocabulary): `alignment.align(expected_words, utterance) -> list[Verdict]` is the seam most tests sit on.
- Mock-first: every port and service has an in-memory implementation so the whole study loop runs in CI without models or hardware.
- Data over weights: improvement is stored corrections, lexicon entries and learner profile rows (ADR-0006).
- Local-first: a cloud failure degrades to static Coach-voice phrases, never to silence; a missing Mouth degrades to text.
