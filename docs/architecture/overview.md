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
- **composition root** `leafi/app.py` (used by `cli.py`) is the only place that imports everything: it reads `devices.yml`, asks the devices registry for adapter factories, builds services from the registries, constructs Listeners (Ear + VAD + ASR, or console) and hands the Hub its adapters plus a `Synthesizer` (a core-defined protocol that `services/tts` implements). Core therefore never imports devices or services (codex review B1).

Audio ownership (codex review B2): `AudioChunk`/`AudioClip` carry sample rate, channels, dtype and a monotonic timestamp; a voice `Utterance` carries an in-memory `AudioRef` (bounded ring, released after the Practice step that may score it); typed Utterances carry none and can never receive a pronunciation score.

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
3. Every call that leaves the LAN is listed in the egress policy (quality-attributes/security.md, ADR-0011) with its module and payload; the study track's notifications are text-only. Enforced by `tests/test_privacy.py` (outbound recorder with canaries + no-network subprocess run).
4. Cloud payloads are built by `study/coach.py` from the redacted page window, miscue words and an intent enum; learner free text is redacted first. Enforced by the canary test.
5. Page text is read through `pages.current_text()`; verified spans survive re-OCR; history is invalidated, never deleted (ADR-0010). Enforced by `tests/test_corrections.py`.
6. Half-duplex: the session's listening gate is closed while any Mouth plays; one `SpeechSerializer` per session; the study session holds the speech lease that the habit track respects. Enforced by `tests/test_hub.py` temporal tests, `tests/test_speaker_lease.py`.

## Runtime picture

1. `python -m leafi study` starts the Hub (loads devices), warms services in the background, then runs the `study.session` state machine: identify book → find page → read loop → practice → check → wrap.
2. The read loop asks the `Listener` for the next Utterance (audio → VAD → ASR, or typed text), aligns it to the current page revision (observations + committed cursor, ADR-0009), stores observations and candidate miscues, and asks `coach` for the immediate line (local static phrases); the Brain is called only for enrichment (explanations, questions), asynchronously, with a strict output schema and a revision guard.
3. `hub.say()` turns the line into audio through `services/tts` and plays it on every Mouth per policy, and shows the text on every Face.
4. Habit tasks keep running from `agent/main.py` unchanged until they are migrated.

## Design principles

- Deep modules, small interfaces (Matt Pocock's `codebase-design` vocabulary): `alignment.align(window, utterance, committed_cursor) -> AlignResult` (observations + cursors, ADR-0009) is the seam most tests sit on.
- Mock-first: every port and service has an in-memory implementation so the whole study loop runs in CI without models or hardware.
- Data over weights: improvement is stored corrections, lexicon entries and learner profile rows (ADR-0006).
- Local-first: a cloud failure degrades to static Coach-voice phrases, never to silence; a missing Mouth degrades to text.
