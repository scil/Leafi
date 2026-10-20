# Security and privacy

## Red lines

1. **Images, faces, poses never leave the LAN.** Book pages are images. OCR, vision judge and barcode decoding run locally. Enforced by: egress tests below; the `Notifier` port carries text only.
2. **The learner's voice stays local by default.** ASR and pronunciation scoring are local; audio is not persisted unless `AUDIO_KEEP_CLIPS=true`. Enforced by: config default + `tests/test_storage.py` retention test.
3. **Cloud payloads carry no identity and no learner text.** The Claude payload is exactly: the redacted page window (≤ 3 sentences), candidate words, an intent enum + target word/phrase from the page, counts-only summary, fixed coach instructions (ADR-0011). Learner free text never leaves the LAN in v1 (intents are rule-based; comprehension answers are compared locally). `REDACT_TERMS` (set with `python -m leafi setup --redact`) is defence in depth against identity printed or handwritten on a page. Enforced by: canary test below.
4. **Cameras never enter the bathroom**; the study camera points at the desk. Enforced by: advisory (physical).
5. **Child-transparent and child-controlled.** Leafi says when it listens and looks; the Face shows the listening state; `stop` and `skip` work in every state; at most 2 retries per word; no persistent Difficulty without corroboration (ADR-0009). Enforced by: `tests/test_practice.py`, `tests/test_session_controls.py`.

## Egress policy (ADR-0011)

| Destination | Payload | Module | Switch |
|---|---|---|---|
| Claude API | redacted page window, candidate words, intent enum + target from the page, counts-only summary, fixed instructions — never learner free text | `leafi/services/brain/claude.py` | `ANTHROPIC_API_KEY` |
| edge-tts | text to speak | `leafi/services/tts/edge.py` | `TTS_BACKEND_ZH` |
| Open Library | ISBN digits | `leafi/services/catalog/openlibrary.py` | `BOOK_LOOKUP` |
| Bark / Telegram | text | `leafi/devices/notifiers.py` | `BARK_URL`, `TELEGRAM_*` |
| Xiaomi cloud | P2P keys, by go2rtc, outside Leafi | — | — |
| Model downloads | only `python -m leafi doctor --download` | `leafi/doctor.py` | explicit |

Everything else stays on the LAN. OpenPronounce is configured with an offline reference voice (Kokoro) and pre-provisioned checkpoints; gTTS is off.

**Habit-track parent snapshot.** `agent/notify.py` attaches one frame to the parent's Telegram chat only when the owner sets `NOTIFY_WITH_SNAPSHOT=true` (default false; ADR-0011 amendment). The study track never attaches one.

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
