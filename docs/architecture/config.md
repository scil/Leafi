# Configuration

Three roots, one owner each:

| Root | Owner | Reload | Holds |
|---|---|---|---|
| `.env` (from `.env.example`) | `leafi/core/config.py` (pydantic-settings; the legacy `agent/config.py` reads the same file) | process start | secrets, hosts, ports, model names, feature flags |
| `config/devices.yml` | `leafi/core/hub.py` | process start (`python -m leafi devices` prints the parsed result) | which devices exist and which capabilities each provides |
| `config/tasks.yml` | `agent/tasks.py` (task editor UI) | mtime check on every read | habit tasks |

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
      input_device: default           # sounddevice name or index
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
| `ASR_MODEL_DIR` | `models/asr/parakeet-tdt-0.6b-v2-int8` | sherpa-onnx model folder |
| `TTS_BACKEND_EN` / `TTS_BACKEND_ZH` | `kokoro` / `edge` | `kokoro` · `edge` · `mock` |
| `TTS_VOICE_EN_KOKORO` | `af_heart` | Kokoro voice id |
| `OCR_BACKEND` | `rapidocr` | `rapidocr` · `qwen_vl` · `mock` |
| `OCR_SECOND_OPINION` | `` (empty) | deferred in v1 (ADR-0011); `qwen_vl` when enabled later |
| `OCR_MIN_CONFIDENCE` | `0.85` | below it: recapture, then ask the learner |
| `PRON_BACKEND` | `openpronounce` | `openpronounce` · `mock`; offline reference voice forced |
| `PRON_AUTO_JUDGE` | `false` | automatic pronunciation judgement; on only after the evaluation threshold in ADR-0011 |
| `ASR_HOTWORDS` | `off` | `off` · `lexicon`; on only after the biased-vs-unbiased comparison |
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
