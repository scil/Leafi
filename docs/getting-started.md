# Getting started

Setup and run commands for both tracks. What Leafi is and why: [`../README.md`](../README.md). Rules for agents: [`../AGENTS.md`](../AGENTS.md).

## Status

| Track | State |
|---|---|
| Habits (`agent/`): scheduled reminders → presence → pose/vision verification → parent push, weekly report | Working; Xiaomi camera stream and speaker verified 2026-08-07; pose stream and dwell calibration still need live runs |
| Book study (`leafi/`): hardware-agnostic core, text-mode study loop, OCR, voice | Text-mode loop working (S0, S1); real models installed and `doctor` all ok (Parakeet, Silero, Kokoro, RapidOCR, OpenPronounce); voice session runs on the PC microphone (S3 plumbing); camera prototypes P-2/P-3/P-5 wait for the camera to be online and the owner present |

## Prerequisites

- Windows 11, Docker Desktop (WSL2), Python 3.12 venv at `.venv` (created with `uv venv --python 3.12 .venv`; it has no `pip`, use `uv pip install --python .venv …`)
- Habit vision (P1): NVIDIA driver, `torch` cu128, `ultralytics`, Ollama with `qwen3-vl:8b`
- Study: `uv pip install --python .venv -r requirements-study.txt` (heavy model packages are only needed for camera/voice); `python -m leafi doctor` tells you what is missing
- Evaluation tools (development only): their own venv, `.venv-eval`, from `requirements-eval.txt`

## Quick start

```powershell
copy .env.example .env            # camera, schedule, notification channels, model backends
docker compose up -d              # Frigate + MQTT
scripts\win\go2rtc-host.bat       # host go2rtc (Xiaomi camera)
uv pip install --python .venv -r requirements.txt
.venv\Scripts\python -m agent.main                 # habits, scheduled
.venv\Scripts\python -m agent.main --now brush_pm  # run one task now
.venv\Scripts\python -m leafi devices              # parsed config/devices.yml and the Hub
.venv\Scripts\python -m leafi doctor               # backends: ok / missing package / missing model / disabled / deferred
.venv\Scripts\python -m leafi doctor --download    # fetch the missing models under models/ (the only sanctioned download)
.venv\Scripts\python -m leafi study --text --mock --book "Fixture" --page-text tests/fixtures/pages/p1.txt --page 1
#   typed study loop, no hardware, nothing spoken; drop --mock to use Claude (ANTHROPIC_API_KEY) and Anki
.venv\Scripts\python -m leafi study --book "Fixture" --page-text tests/fixtures/pages/p1.txt --page 1 --mouth pc
#   voice session on the PC microphone and speaker (Silero VAD + Parakeet); the console still takes /stop, /skip, /page N;
#   --voice-policy none shows text only; without --mouth pc the camera speaker is used too (ask the owner first)
$env:LEAFI_HW_TESTS="1"; .venv\Scripts\python -m pytest -q   # real-model plumbing tests (Kokoro, Parakeet, Silero, OpenPronounce)
.venv\Scripts\python -m leafi export --session 1   # JSON summary for the parent (no audio, no learner free text)
.venv\Scripts\python -m leafi forget --session 1   # parent deletion (ADR-0010 §9); also --book <id>
```

Mock run without a camera: `docker compose up -d mosquitto` then `python -m agent.main --mock --now brush_pm` and `python scripts/fake_event.py` in another terminal.

## Tests

```powershell
.venv\Scripts\python -m pytest -q
```

Hardware and model tests are skipped unless `LEAFI_HW_TESTS=1`. Lint: `.venv\Scripts\python -m ruff check leafi tests` (`requirements-dev.txt`).

## Cameras

- Current: Xiaomi Smart Camera 3 PTZ (`cam_xiaomi`) through the patched host go2rtc in `tools/go2rtc/` (read `PATCHES.md` before upgrading). Speaker codec `opus`.
- Candidate: Tapo C260 (`cam_tapo`), RTSP + `tapo://` speaker, codec `pcma`.
- Switch with `STREAM_NAME` and `SPEAKER_AUDIO_CODEC` in `.env`, then `scripts\win\apply-env.bat`.

## Human console

The owner's Obsidian vault (`scil/Leafi/`) holds a button console and four tutorials for the habit track; every button calls a script in `scripts/win/`.

## Where to read next

[`../GLOSSARY.md`](../GLOSSARY.md), [`product.md`](product.md), the active plan [`plans/active/2026-10-22-ai-led-study.md`](plans/active/2026-10-22-ai-led-study.md) (its predecessor [`2026-10-19-leafi-book-study.md`](plans/active/2026-10-19-leafi-book-study.md) holds S0–S3 and the owner-present hardware steps), and the archived habit design [`archive/2026-08-habit-coach-design-v0.2.md`](archive/2026-08-habit-coach-design-v0.2.md).
