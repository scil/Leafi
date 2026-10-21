# Configuration

Three roots, one owner each:

| Root | Owner | Reload | Holds |
|---|---|---|---|
| `.env` (from `.env.example`) | `leafi/core/config.py` (pydantic-settings; the legacy `agent/config.py` reads the same file) | process start | secrets, hosts, ports, model names, feature flags |
| `config/devices.yml` | `leafi/core/hub.py` | process start (`python -m leafi devices` prints the parsed result) | which devices exist and which capabilities each provides |
| `config/tasks.yml` | `agent/tasks.py` (task editor UI) | mtime check on every read | habit tasks |

`.env` is edited on the task editor's 设置 (.env) tab (`python -m agent.webui`) or by hand. The page and `python -m leafi setup --redact` write only through `leafi/core/envfile.py::update_env` (lock, backup to `data/env-backup/`, ACL kept) and only while the file is in canonical form: every line blank, a column-0 comment, or `KEY=value` with a bare `[A-Za-z0-9_./:@,+=%-]*` value or a single-quoted value without `'`, `\` or `${`; an empty value followed by a comment is written `KEY=''  # …`. Design: `docs/plans/active/2026-10-21-env-settings-page.md`.

## `config/devices.yml` (schema v1)

```yaml
version: 1
voice_policy: all          # all | primary | none
primary_mouth: desk_cam    # used when voice_policy = primary
devices:
  - name: desk_cam
    adapter: go2rtc_camera
    capabilities: [eye, mouth]        # ear is opt-in once the mic path is verified
    options:
      go2rtc_url: ${GO2RTC_URL}       # ${VAR} expands from .env
      stream: ${STREAM_NAME}
      audio_codec: opus
      src_dir: ${SPEAKER_SRC_DIR}
      snapshot_width: 1920
  - name: pc
    adapter: local_pc
    capabilities: [ear, mouth, face]
    options:
      input_device: ${PC_INPUT_DEVICE:-DJI}  # name fragment, index or `default`
      zeros_lost_after_s: 10          # all-zero capture this long → ListenerLost (TD-26); 0 disables
  - name: console
    adapter: console
    capabilities: [listener, face]    # typed input; always safe to leave on
  - name: hallway_presence
    adapter: frigate_presence
    capabilities: [presence]
  - name: parent_phone
    adapter: notifier
    capabilities: [notifier]
```

Selection block (required for study):

```yaml
study:
  eye: desk_cam            # the one Eye used for pages
  listener: pc             # the one voice Listener; console controls stay active in parallel
```

Rules: unknown `adapter` or capability → startup error naming the device. A device whose options are missing a required `${VAR}` is **disabled with a warning**, not fatal, so a laptop without the camera still runs text mode. `console` is always added if no `listener`/`face` exists.

## `.env` additions for study (defaults in `config.py`)

| Variable | Default | Meaning |
|---|---|---|
| `ASR_BACKEND` | `sherpa` | `sherpa` · `whisper` · `mock` |
| `ASR_MODEL_DIR` | `models/asr/parakeet-tdt-0.6b-v2-int8` | sherpa-onnx model folder (`python -m leafi doctor --download` fills `models/` for asr, vad, tts en, pronunciation and ocr) |
| `TTS_BACKEND_EN` / `TTS_BACKEND_ZH` | `kokoro` / `edge` | `kokoro` · `edge` · `mock` |
| `TTS_VOICE_EN_KOKORO` | `af_heart` | Kokoro voice id |
| `OCR_BACKEND` | `rapidocr` | `rapidocr` · `qwen_vl` · `mock` |
| `OCR_SECOND_OPINION` | `` (empty) | deferred in v1 (ADR-0011); `qwen_vl` when enabled later |
| `OCR_MIN_CONFIDENCE` | `0.85` | below it: recapture, then ask the learner |
| `PRON_BACKEND` | `openpronounce` | `openpronounce` · `mock`; offline reference voice forced |
| `PRON_AUTO_JUDGE` | `false` | automatic pronunciation judgement; on only after the evaluation threshold in ADR-0011 |
| `ASR_HOTWORDS` | `off` | `off` · `lexicon`; on only after the biased-vs-unbiased comparison. P-1 (2026-10-20): hotwords work per stream with `modified_beam_search` and a `bpe.vocab` built from `tokens.txt` (`services/asr/sherpa.py`) |
| `ASR_THREADS` | `4` | sherpa-onnx CPU threads (P-1: 12-word sentence 0.17 s at 2, 0.12 s at 4, 0.09 s at 8) |
| `VAD_SILENCE_S` / `VAD_THRESHOLD` | `0.6` / `0.5` | Silero VAD (`models/vad/silero_vad.onnx`): silence that closes an utterance; speech probability threshold. Sentence completion is still `SENTENCE_PAUSE_S` |
| `OCR_VERSION` | `PP-OCRv6` | `PP-OCRv6` (ships inside the rapidocr wheel) · `PP-OCRv5` (English recogniser, fetched by `doctor --download`); P-3 on desk captures (2026-10-20): v6 gave 6–8 confident lines where v5 gave 1–5 |
| `OCR_AUTO_ROTATE` | `true` | when 0° yields < 3 confident lines, read 90/270/180 too and keep the best (the desk book lay at 270°); up to four passes of ~1.5 s once per page |
| `CHECKS_EVERY_S` | `900` | configuration checks interval (ADR-0016); `python -m leafi checks` runs them once and prints the result |
| `GO2RTC_SHA256` | the patched build of 2026-10-21 | the `go2rtc-patched` check's expected hash; update it after a patched rebuild (`tools/go2rtc/PATCHES.md`) |
| `ACTIVE_HOURS` / `MIN_FREE_GB` | `7-21` / `5` | Windows Update active hours must cover these hours; free space required on the data drive |
| `REQUIRED_CHANNELS` | `telegram,heartbeat` | the `telegram` and `heartbeat` checks fail while a listed channel is not configured; remove one to accept toast-only or no heartbeat |
| `HEARTBEAT_URL` | `` (empty) | Healthchecks.io ping URL; the supervisor GETs it every poll (dead man's switch) |
| `GATUS_URL` / `GATUS_TOKEN` | `http://127.0.0.1:18080` / `` | the read-only dashboard; the same `GATUS_TOKEN` must reach the `gatus` container (docker-compose.yml reads `.env`); empty: no pushes |
| `SUPERVISE` | `docker,camera,frigate,mosquitto,gatus` | services the supervisor keeps running (ADR-0016). `habit-agent` is opt-in because the habit coach speaks through the camera on its schedule; add `ollama` when the vision judge is used daily |
| `SUPERVISOR_POLL_S` | `60` | poll interval |
| `SUPERVISOR_BAD_STREAK` / `SUPERVISOR_MAX_RECOVERIES` / `SUPERVISOR_HEALTHY_S` | `2` / `3` / `600` | bad polls before a recovery; recoveries per outage; continuous good time that ends an outage |
| `SUPERVISOR_GRACE` | `camera=90,habit-agent=90,docker=180,frigate=120,mosquitto=60,gatus=60,ollama=60` | per-service grace after a recovery (minimums: docker 120, frigate 60, camera 60) |
| `SUPERVISOR_RESUME_GAP_S` / `SUPERVISOR_RESUME_GRACE_S` | `180` / `120` | wall-clock gap read as sleep/resume (must exceed one poll plus its worst duration); grace after it |
| `TASK_REPEAT_MIN` | `5` | the logon task's repeating trigger (read by `install-tasks.ps1`) |
| `KEEP_BACKOFF_S` / `KEEP_CRASH_EXITS` / `KEEP_CRASH_WINDOW_MIN` | `5,30,120,300` / `3` / `30` | keep.ps1's restart delays and its "crashed repeatedly" rule (window > (exits − 1) × the longest delay) |
| (all timing settings above) | — | validated together by `leafi/ops/timing.py` (ADR-0016): a value that breaks an invariant falls back to its default and the `supervision-timing` check alerts; `python -m leafi timing` shows the values in use, the derived recovery and give-up times, and any conflict |
| `SUPERVISOR_PORT` | `18771` | the supervisor's `POST /rearm?service=S` listener on 127.0.0.1 (the 🔁 button rearms `camera`); outside Windows' excluded port ranges |
| `GO2RTC_EXE` / `GO2RTC_CONFIG` | `tools/go2rtc/go2rtc.exe` / `tools/go2rtc/go2rtc-host.yaml` | the go2rtc child the supervisor starts |
| `MQTT_PORT` | `18830` | mosquitto's host port, probed by TCP connect |
| `DOCKER_DESKTOP_EXE` | `` (empty) | Docker Desktop executable for the `docker` recovery; empty finds it next to the docker CLI (scoop) or under Program Files |
| `FRIGATE_URL` / `FRIGATE_CAMERA` | `http://127.0.0.1:15000` / `hallway` | Frigate listing this camera counts as demand for the stream, so a dead producer is not mistaken for idle |
| `PAGE_DIFF_THRESHOLD` | `6.0` | page-turn watcher: mean grey diff (64×64) that counts as motion. Desk camera noise 2.3–3.0, a hand 37–66 (P-3); rendered test pages differ by 1.7, so tests use 1.0 |
| `OCR_SNAP` | `advisory` | `off` · `advisory` (candidates shown) · `auto` (not in v1) |
| `STUDY_BRAIN_MODEL` | `claude-opus-5-5` | study track: cloud model for enrichment turns (ADR-0003); the habit track keeps its own `BRAIN_MODEL` in `agent/config.py` |
| `BRAIN_MODEL_CHEAP` | `claude-haiku-5-5` | one-line habit phrases |
| `BRAIN_DEADLINE_S` | `12` | overall deadline per Brain call, 1 retry |
| `BRAIN_LOCAL_MODEL` | `` (empty) | Ollama fallback, deferred (ADR-0011) |
| `REDACT_TERMS` | `` | comma-separated terms removed from cloud payloads (learner name, school); set by `python -m leafi setup --redact "…"`; `doctor` warns when empty |
| `NOTIFY_WITH_SNAPSHOT` | `false` | habit track only: attach one frame to the parent's Telegram notification (owner opt-in, ADR-0011) |
| `STUDY_IDLE_S` | `180` | idle timeout to WRAP (READ/CHECK/REVIEW_DUE only) |
| `PRACTICE_RETRY_S` | `10` | voice: no retry within this → `unsure(idle)`, next candidate |
| `CHECK_ANSWER_S` | `20` | voice: no answer within this → `unavailable` |
| `SAY_TIMEOUT_S` | `20` | per `say()` call |
| `EVAL_TRANSCRIPTS` | `false` | opt-in text-only transcripts under `data/evals/` |
| `LEAFI_NO_NETWORK` | unset | `1` makes any non-loopback connect raise (tests) |
| `ANKI_URL` / `ANKI_DECK` / `ANKI_MODEL` | `http://127.0.0.1:8765` / `Leafi` / `问答题` | AnkiConnect target |
| `STUDY_LANGUAGE` | `en` | expected book language |
| `PAGES_RETAIN_DAYS` | `7` | delete cached page images after N days |
| `AUDIO_KEEP_CLIPS` | `false` | keep learner audio clips (off by default; see security) |
| `BRAIN_BACKEND` | `claude` | `claude` · `ollama` (deferred) · `mock`; an empty `ANTHROPIC_API_KEY` means static phrases only |
| `BOOK_LOOKUP` | `off` | `off` · `openlibrary` (ISBN digits only, egress table) |
| `TTS_VOICE_ZH_EDGE` / `TTS_VOICE_EN_EDGE` | `zh-CN-YunxiNeural` / `en-US-JennyNeural` | edge-tts voices |
| `PAGE_POLL_S` | `1.0` | how often the session checks the Eye for a physical page turn |
| `SENTENCE_PAUSE_S` | `1.2` | voice: silence that completes a sentence near its end (ADR-0013 completion (ii)) |
| `REVIEW_KNOWN_INTERVAL_DAYS` / `REVIEW_MAX_CARDS` | `21` / `5` | `learning→known` interval; cards per review turn |
| `LEASE_TTL_S` | `60` | speech-lease expiry, renewed every third of it |
| `DATA_DIR` / `CACHE_DIR` / `MODELS_DIR` / `DEVICES_FILE` | `data` / `cache` / `models` / `config/devices.yml` | paths (tests and the no-network run point them at a temp dir) |
| `LEAFI_DEBUG_TEXT` | `false` | allow raw utterance text in DEBUG logs |

`devices.yml` values may use `${VAR:-default}` for optional variables (empty allowed); a plain `${VAR}` is required.

Removed names: `BRAIN_MODEL` no longer configures the study track (2026-10-20, replaced by `STUDY_BRAIN_MODEL`; the habit track still reads it). Renamed: the repository path in `SPEAKER_SRC_DIR` examples changed from `Carema-Kis-AI` to `Leafi` (2026-10-19).
