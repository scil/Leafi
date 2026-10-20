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

Rules: unknown `adapter` or capability → startup error naming the device. A device whose options are missing a required `${VAR}` is **disabled with a warning**, not fatal, so a laptop without the camera still runs text mode. `console` is always added if no `listener`/`face` exists.

## `.env` additions for study (defaults in `config.py`)

| Variable | Default | Meaning |
|---|---|---|
| `ASR_BACKEND` | `sherpa` | `sherpa` · `whisper` · `mock` |
| `ASR_MODEL_DIR` | `models/asr/parakeet-tdt-0.6b-v2-int8` | sherpa-onnx model folder |
| `TTS_BACKEND_EN` / `TTS_BACKEND_ZH` | `kokoro` / `edge` | `kokoro` · `edge` · `mock` |
| `TTS_VOICE_EN_KOKORO` | `af_heart` | Kokoro voice id |
| `OCR_BACKEND` | `rapidocr` | `rapidocr` · `qwen_vl` · `mock` |
| `OCR_SECOND_OPINION` | `qwen_vl` | backend consulted when primary confidence < `OCR_MIN_CONFIDENCE` (0.85); empty disables |
| `PRON_BACKEND` | `openpronounce` | `openpronounce` · `mock` |
| `BRAIN_MODEL` | `claude-opus-5-5` | cloud model for tutoring turns (ADR-0003) |
| `BRAIN_MODEL_CHEAP` | `claude-haiku-5-5` | one-line habit phrases |
| `BRAIN_LOCAL_MODEL` | `qwen3:8b` | Ollama fallback when the key is empty or the call fails |
| `ANKI_URL` / `ANKI_DECK` / `ANKI_MODEL` | `http://127.0.0.1:8765` / `Leafi` / `问答题` | AnkiConnect target |
| `STUDY_LANGUAGE` | `en` | expected book language |
| `PAGES_RETAIN_DAYS` | `7` | delete cached page images after N days |
| `AUDIO_KEEP_CLIPS` | `false` | keep learner audio clips (off by default; see security) |

Removed names: none yet. Renamed: the repository path in `SPEAKER_SRC_DIR` examples changed from `Carema-Kis-AI` to `Leafi` (2026-10-19).
