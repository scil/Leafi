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
| edge-tts | Leafi-authored lines only, after `REDACT_TERMS` redaction; a line that embeds learner-originated text (a typed correction, a learner answer) is marked local-only and is shown on Faces / spoken by a local backend, never sent to a cloud TTS | `leafi/services/tts/edge.py` | `TTS_BACKEND_ZH`, `TTS_BACKEND_EN` |
| Open Library | ISBN digits | `leafi/services/catalog/openlibrary.py` | `BOOK_LOOKUP` |
| Bark / Telegram | text | `leafi/devices/notifiers.py` | `BARK_URL`, `TELEGRAM_*` |
| Healthchecks.io heartbeat (ADR-0016) | a bodyless `GET HEARTBEAT_URL` (`hc-ping.com/<check id>`) every minute; nothing else | `leafi/ops/checks.py::heartbeat` | `HEARTBEAT_URL` (empty: nothing sent) |
| Telegram (operational alerts, ADR-0016) | one fixed catalog sentence (`leafi/core/alerts.py::render`), chosen by codes; never a device name, IP, stream name, exception text or learner data | `leafi/ops/alerts.py::deliver` → `NotifierDevice.send` | `TELEGRAM_*` |
| Xiaomi cloud | P2P keys, by go2rtc, outside Leafi | — | — |
| Model downloads | only `python -m leafi doctor --download` | `leafi/doctor.py` | explicit |
| Evaluation data downloads (OpenSLR SLR101 speechocean762, public CC BY 4.0 audio) | a `GET` of a fixed archive URL; nothing sent | `leafi/doctor.py::download_speechocean762` | explicit, only `doctor --download --only speechocean762` |

Everything else stays on the LAN. OpenPronounce is configured with an offline reference voice (Kokoro) and pre-provisioned checkpoints; gTTS is off.

**Habit-track parent snapshot.** `agent/notify.py` attaches one frame to the parent's Telegram chat only when the owner sets `NOTIFY_WITH_SNAPSHOT=true` (default false; ADR-0011 amendment). The study track never attaches one.

Enforcement: `tests/test_privacy.py` — (a) an `httpx` transport recorder wrapped around every client the study loop can create, run under a text-mode session seeded with canaries (learner name, school, a handwritten label in the page fixture, audio bytes); every outbound body is asserted canary-free and every host is in the table above; (b) a subprocess run with `LEAFI_NO_NETWORK=1` (any non-loopback connect raises) must complete a text-mode session and a pronunciation score on a fixture clip.

## Prompt safety

Page text and learner text are data: quoted in a delimited block, the Brain's reply validated against a strict schema and an allow-list of actions; anything else is dropped. With ADR-0017 the allow-list is the activity kinds of ADR-0017 §3.1 (`review_anki`, `read_listen`, `read_aloud`, `practise_errors`, `teach_items`, `recall_items`, `quiz`, `learner_questions`, `add_cards`, `break`, `end`) plus the record types of §7.1 (`assessment`, `item_status`, `book_note`), and every proposal is constructed against the harness's current menu and budgets, so a valid-looking reply still cannot start an activity the menu does not allow; the v1 list (`practice`, `explain`, `ask`, `encourage`, `none`) holds until that code lands. Fixed injection scenarios live in `tests/test_prompt_injection.py`. Coach lines shown to the child pass a short deny-list (shaming words) before being spoken; failures fall back to the static phrase.

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

See data-model.md → Retention. Parent deletion: `python -m leafi forget --session <id>` and `--book <id>`, defined in ADR-0010 §9.
