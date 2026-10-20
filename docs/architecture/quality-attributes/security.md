# Security and privacy

## Red lines

1. **Images, faces, poses never leave the LAN.** Book pages are images. OCR, vision judge and barcode decoding run locally. Enforced by: egress tests below; the `Notifier` port carries text only.
2. **The learner's voice stays local by default.** ASR and pronunciation scoring are local; audio is not persisted unless `AUDIO_KEEP_CLIPS=true`. Enforced by: config default + `tests/test_storage.py` retention test.
3. **Cloud payloads carry no identity.** Local redaction of `REDACT_TERMS` (learner name, school, any term the parent adds) before any cloud call; free-form learner speech goes to the Brain only redacted and only as intent + target; page text goes as the selected window (≤ 3 sentences). Enforced by: canary test below.
4. **Cameras never enter the bathroom**; the study camera points at the desk. Enforced by: advisory (physical).
5. **Child-transparent and child-controlled.** Leafi says when it listens and looks; the Face shows the listening state; `stop` and `skip` work in every state; at most 2 retries per word; no persistent Difficulty without corroboration (ADR-0009). Enforced by: `tests/test_practice.py`, `tests/test_session_controls.py`.

## Egress policy (ADR-0011)

| Destination | Payload | Module | Switch |
|---|---|---|---|
| Claude API | redacted page window, miscue words, intent enum + target, counts-only summary | `leafi/services/brain/claude.py` | `ANTHROPIC_API_KEY` |
| edge-tts | text to speak | `leafi/services/tts/edge.py` | `TTS_BACKEND_ZH` |
| Open Library | ISBN digits | `leafi/services/catalog/openlibrary.py` | `BOOK_LOOKUP` |
| Bark / Telegram | text | `leafi/devices/notifiers.py` | `BARK_URL`, `TELEGRAM_*` |
| Xiaomi cloud | P2P keys, by go2rtc, outside Leafi | — | — |
| Model downloads | only `python -m leafi doctor --download` | `leafi/doctor.py` | explicit |

Everything else stays on the LAN. OpenPronounce is configured with an offline reference voice (Kokoro) and pre-provisioned checkpoints; gTTS is off.

**Habit-track exception.** `agent/notify.py` can attach one frame to the parent's Telegram chat (the owner's 2026-08 design). The study track never does; whether the habit track keeps it is the owner's open decision (TD-9).

Enforcement: `tests/test_privacy.py` — (a) an `httpx` transport recorder wrapped around every client the study loop can create, run under a text-mode session seeded with canaries (learner name, school, a handwritten label in the page fixture, audio bytes); every outbound body is asserted canary-free and every host is in the table above; (b) a subprocess run with `LEAFI_NO_NETWORK=1` (any non-loopback connect raises) must complete a text-mode session and a pronunciation score on a fixture clip.

## Prompt safety

Page text and learner text are data: quoted in a delimited block, the Brain's reply validated against a strict schema and an allow-list of actions (`practice`, `explain`, `ask`, `encourage`, `none`); anything else is dropped. Fixed injection scenarios live in `tests/test_prompt_injection.py`. Coach lines shown to the child pass a short deny-list (shaming words) before being spoken; failures fall back to the static phrase.

## Secrets

`.env` is gitignored; `.env.example` has placeholders. Keys are read by pydantic-settings and never logged.

## Network exposure

| Service | Binding | Auth | Note |
|---|---|---|---|
| Leafi task editor 8770 | 127.0.0.1 | none | local only |
| host go2rtc api 2984 | 127.0.0.1 | none | local only |
| host go2rtc rtsp 2554 | 0.0.0.0 | none | needed by the Frigate container; TD-3 |
| Frigate 15000, MQTT 18830 | host-mapped | none | TD-3 |
| xiaozhi ws (future) | LAN | device token | ADR-0008 |

## Retention

See data-model.md → Retention. Parent deletion: `python -m leafi forget --session <id>` and `--book <id>`.
