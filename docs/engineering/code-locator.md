# Code locator

Search this file for the symptom or the user's words; read only the matching entry. Entries: trigger → start files → invariant/trap → smallest check.

## "speaker is silent" / "喇叭无声" / noise from the camera
- Start: `agent/speaker.py`, `tools/go2rtc/PATCHES.md`, `.env` (`SPEAKER_AUDIO_CODEC`, `GO2RTC_URL`, `SPEAKER_SRC_DIR`).
- Trap: go2rtc API sources may not contain spaces; the host go2rtc is a patched build — a stock upgrade brings the noise back; Xiaomi = `opus`, Tapo = `pcma`; src dir must match the go2rtc instance's filesystem (host path vs `/cache/tts`).
- Check: `python -m agent.main --say "test"` with `SPEAKER_BACKEND=local` first, then `go2rtc`.

## "camera stream disconnects every few minutes"
- Start: `tools/go2rtc/PATCHES.md` (patch 2), `scripts/win/health.ps1`.
- Invariant: host go2rtc, not the container, holds the cs2 P2P connection.
- Check: health script shows dial count stable over 10 minutes.

## "task editor rejected my prompt" / 红线 01
- Start: `agent/tasks.py::validate`, `GUARD_PHRASES`.
- Invariant: a vision-judge prompt must say it does not identify people; empty prompt only allowed for built-in kinds.
- Check: `tests/test_tasks.py`.

## "Leafi says it is listening but nothing happens" (study, planned)
- Start: `leafi/core/hub.py` (Listener selection), `leafi/devices/local_pc.py`, `leafi/services/asr/`.
- Trap: listening is paused while a Mouth plays unless the adapter declares `aec`; a missing ASR model disables the voice Listener and the console Listener silently takes over — check `python -m leafi doctor`.
- Check: `python -m leafi study --text` works; then `doctor` shows `asr: ok`.

## "Leafi read the page wrong" / OCR mistake (planned)
- Start: `leafi/study/corrections.py`, `leafi/study/pages.py`.
- Invariant: `text_truth` wins; corrections are append-only.
- Check: `tests/test_corrections.py`.

## "wrong word flagged as mispronounced" (planned)
- Start: `leafi/study/alignment.py` (normalisation table), `leafi/services/pronunciation/`.
- Trap: ASR normalises numbers and contractions; short function words get false alarms from the phoneme scorer.
- Check: `tests/test_alignment.py`; add the sentence as a fixture.
