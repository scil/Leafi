# Security and privacy

## Red lines

1. **Images, faces, poses never leave the LAN.** Book pages are images. OCR, vision judge and barcode decoding run locally. Enforced by: egress tests below; the `Notifier` port carries text only.
2. **The learner's voice stays local by default.** ASR and pronunciation scoring are local; audio is not persisted unless `AUDIO_KEEP_CLIPS=true`. Enforced by: config default + `tests/test_storage.py` retention test.
3. **Cloud payloads carry no identity; a learner's own words only pseudonymised and only when allowed** (ADR-0018, superseding ADR-0011's "no learner text"). Every household name, school and listed term is replaced before any text leaves; a learner's words leave only with their `cloud.text` on and a school answer, run through the name detector too; an exact age from the profile never leaves (an age said in the learner's own words is sent as said, owner decision 2026-10-23). The protected terms are `household_terms` (`python -m leafi privacy terms`); the retired `REDACT_TERMS` was imported into them. Enforced by: the egress pipeline and the canary tests below.
4. **Cameras never enter the bathroom**; the study camera points at the desk. Enforced by: advisory (physical).
5. **Child-transparent and child-controlled.** Leafi says when it listens and looks; the Face shows the listening state; `stop` and `skip` work in every state; at most 2 retries per word; no persistent Difficulty without corroboration (ADR-0009). Enforced by: `tests/test_practice.py`, `tests/test_session_controls.py`.

## Egress policy (ADR-0018; since M5, 2026-10-24)

Every outbound request from `leafi/` is prepared by `leafi.privacy.egress` (`prepare`: destination, purpose, provenance gate, pseudonymisation, the attempt row) and sent by its mediating transport (an attempt token for that one request, admission before each transmission, a `netguard` grant per connection); the socket guard (`leafi/core/netguard.py`, installed by `leafi.bootstrap`, enforcing) refuses anything else that reaches for a cloud address or a gateway port. The destinations are `leafi/privacy/destinations.py`; a host it does not list is refused. A learner's own words leave only for a learner with `cloud.text` on and a school answer, and only pseudonymised; names, the school and listed terms are replaced in every class of text (ADR-0018 §3). `egress_log` records each attempt with an HMAC of its bytes, never a body.

| Destination | Payload | Module | Switch |
|---|---|---|---|
| Claude API | the page window and target from the page (`page`), counts and fixed instructions (`system`), pseudonymised; no Brain call from the harness until M7 | `leafi/services/brain/claude.py` | `ANTHROPIC_API_KEY` |
| Ollama (local, gateway port) | the same request to `/v1/chat/completions`; a local destination receives text unpseudonymised | `leafi/services/brain/ollama.py` | `BRAIN_LOCAL_MODEL` |
| edge-tts (`library` mode) | `page` / `system` lines without a protected name, pseudonymised; a learner's own words, and any line naming a listed person, school or term, are spoken by a local backend or shown on Faces | `leafi/services/tts/edge.py` | `TTS_BACKEND_ZH`, `TTS_BACKEND_EN` |
| Open Library | ISBN digits (`/api/books`) | `leafi/services/catalog/openlibrary.py` | `BOOK_LOOKUP` |
| Bark / Telegram (parent notification, purpose `notify`) | one per session: "<surrogate> read: pages, words read, words to practise, new items" (integers); "A reader" for a guest or a learner whose own words may not leave (owner decision 2026-10-23) | `leafi/devices/notifiers.py::notify` | `BARK_URL`, `TELEGRAM_*` |
| Healthchecks.io heartbeat (ADR-0016) | a bodyless `GET HEARTBEAT_URL` (`hc-ping.com/<check id>`) every minute; nothing else | `leafi/ops/checks.py::heartbeat` | `HEARTBEAT_URL` (empty: nothing sent) |
| Telegram (operational alerts, ADR-0016) | one fixed catalog sentence (`leafi/core/alerts.py::render`), chosen by codes; never a device name, IP, stream name, exception text or learner data | `leafi/ops/alerts.py::deliver` → `NotifierDevice.send` | `TELEGRAM_*` |
| Ollama health probe (gateway port) | `GET /api/tags` | `leafi/ops/supervisor.py::egress_probe` | `ollama` service enabled |
| Xiaomi cloud | P2P keys, by go2rtc, outside Leafi | — | — |
| Model downloads | only `python -m leafi doctor --download`, through egress (purpose `ops`): a redirect only to a host the destination lists. Hugging Face (pronunciation checkpoints) and RapidOCR's own fetch are not mediated yet and are refused while the guard enforces | `leafi/doctor.py` | explicit |
| Word-list downloads (SCOWL size 60 from `raw.githubusercontent.com/en-wl/wordlist-diff`, CYP-LEX CSVs from `osf.io`; the Cambridge YLE PDF from `cambridgeenglish.org` only when named) | a `GET` of fixed file URLs; nothing sent | `leafi/doctor.py::download_wordlists`, `download_yle` | explicit: `doctor --download` (word lists), `--only yle` (the PDF) |
| Name-detector model download (spaCy `en_core_web_sm-3.8.0` wheel from `github.com/explosion/spacy-models` releases, MIT; unpacked to `models/spacy/`, never pip-installed) | a `GET` of a fixed release URL; nothing sent. The detector itself never connects (tested under `LEAFI_NO_NETWORK`) | `leafi/doctor.py::download_spacy` | explicit: `doctor --download` (`--only names`) |
| Evaluation data downloads (OpenSLR SLR101 speechocean762, public CC BY 4.0 audio) | a `GET` of a fixed archive URL; nothing sent | `leafi/doctor.py::download_speechocean762` | explicit, only `doctor --download --only speechocean762` |

Everything else stays on the LAN. OpenPronounce is configured with an offline reference voice (Kokoro) and pre-provisioned checkpoints; gTTS is off.

**Habit-track parent snapshot.** `agent/notify.py` attaches one frame to the parent's Telegram chat only when the owner sets `NOTIFY_WITH_SNAPSHOT=true` (default false; ADR-0011 amendment). The study track never attaches one.

Enforcement: `tests/test_privacy.py` — (a) the wire beneath egress's mediator recorded over a text-mode session seeded with canaries (learner name, school, a handwritten label in the page fixture, audio bytes), a Brain request carrying a learner's words (a Chinese sibling name, a Latin name inside Chinese text, the school), and operational alerts; every outbound body is canary-free and every host is in the table above; (b) a subprocess run with `LEAFI_NO_NETWORK=1` must complete a text-mode session and a pronunciation score on a fixture clip. `tests/test_egress.py` (the real `anthropic` SDK against a loopback gateway port with the guard enforcing; tokens, admission, refusals), `tests/test_netguard.py` (grants, revocation shutting retained sockets including TLS, gateway ports, `lan`, UDP, proxies), `tests/test_pseudonym.py`, `tests/test_detector.py`. The suite itself runs with the guard enforcing and an offline egress, so no test reaches the network.

**Known limits** (stated, not prevented): sockets opened by subprocesses (docker, netsh) are outside the guard; a write on a socket kept past its grant is not intercepted on Windows (revocation shuts admitted sockets down instead); a transmission admitted just before a privacy change made by another process may complete (one request); the `lan` class is resolved at process start, so a DHCP change needs a restart.

## Privacy settings (ADR-0018 §5)

Household keys are in `.env` (settings page, group Privacy); a † key needs the page's confirmation bound to its value, and after any privacy change a running Leafi process refuses to send learner or parent text until it restarts (its `.env` fingerprint no longer matches). Learner keys are in `learners.settings`, changed only by `python -m leafi privacy …` (shown, then `--yes`).

| Setting | Where | Default | Values |
|---|---|---|---|
| `cloud.text` † | learner (`privacy learner` writer; a `consents` row each change) | on | on / off; guests always off |
| `privacy.school` | learner | unanswered (learner words stay local) | a school term, or `none` |
| `privacy.media` † | learner | ask | ask / never (media refused until M9) |
| `CLOUD_PARENT_TEXT` † | household | true | true / false |
| `PRIVACY_TTS_LEARNER_LINES` † | household | local | local / cloud |
| `TTS_EDGE_MODE` † | household | library | library (mediated not built) |
| `PRIVACY_NAME_DETECTOR` † | household | true | true / false (`doctor` shows the model's state) |
| `household_terms` † | `python -m leafi privacy terms add|remove --yes` | names and schools from enrolment | a list |
| `LOCAL_MODELS` †, `MAGPIE_URL` † | household | empty | ADR-0018 §2 |
| `PRIVACY_OPS_LOG_DAYS` | household | 30 | 1–365 |
| `GUEST_KEEP_DAYS` | household | 7 | 0–30 |
| `HOUSEHOLD_TZ` | household | this machine's zone | an IANA name |

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

See data-model.md → Retention. Parent deletion: `python -m leafi forget --session <id>` and `--book <id>`, defined in ADR-0010 §9, and `--learner <id> --yes` (a learner and every text derived from them), defined in ADR-0018 §1.
