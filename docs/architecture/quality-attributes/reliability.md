# Reliability

Objective: a study session never ends because a model or device failed; it degrades, and every degraded step reports a typed outcome (`completed` / `uncertain` / `unavailable`) so that an unavailable assessment is never recorded as a learner difficulty and a late result is rejected when `(session_id, page_revision_id)` has moved on (ADR-0010 §5).

| Failure | Behaviour | Check |
|---|---|---|
| Claude API down / no key / deadline (12 s, 1 retry) | Brain returns `unavailable`; immediate lines come from static Coach-voice phrases (`study/phrases.py`); explanations and checks are skipped without recording a difficulty | `tests/test_coach.py::test_brain_unavailable` |
| TTS backend fails with a Mouth present | `say()` shows text on Faces, logs, returns; the gate reopens; next line tries again | `tests/test_hub.py::test_say_tts_failure` |
| Camera unreachable or frame-diff without confident match | state `PAGE_UNCERTAIN`: assessment suspended, utterances stored without observations, Leafi asks for the page number | `tests/test_page_tracker.py` |
| OCR low confidence | recapture once; then ask the learner to read the first line; then offer typed page text (second-opinion VLM deferred, ADR-0011) | `tests/test_ocr_pipeline.py` |
| Anki closed, or add succeeded but the response was lost | `anki_outbox` keeps the op `pending`; next wrap dedupes by the `leafi-id::` tag before adding | `tests/test_anki.py::test_lost_ack_no_duplicate` |
| Crash between correction insert and revision insert | single transaction rolls back; nothing applied | `tests/test_corrections.py::test_rollback` |
| Process crash mid-session | `reading_sessions.ended_at` null; next start closes it (`summary.interrupted=true`, open candidates → `unsure (interrupted)`, reading state kept); a new session on the same book offers to continue from the committed cursor in a new page read (ADR-0013) | `tests/test_storage.py::test_close_stale_sessions`, `tests/test_session_resume.py` |
| go2rtc speaker push rejected (space in src, codec) | logged with the src string; no retry storm (one retry) | existing `agent/speaker.py` behaviour, to be kept in the adapter |
| go2rtc running but the camera sends no video (Mi Home app viewed, TD-25), or its API hangs | the supervisor restarts go2rtc after two bad polls, at most 3 times per outage, then sends one `camera` alert and stops; ten good minutes or the 🔁 button rearm it (ADR-0016) | `tests/test_supervisor.py` |
| a supervised service stops (go2rtc or habit agent exits, Docker / Frigate / mosquitto / Ollama stops answering) | the same policy per service: recovery after two bad polls (child restart, Docker Desktop restart, `compose up -d` + `restart`), at most 3 per outage, then one alert; containers are not probed while Docker is down | `tests/test_supervisor.py` |
| the supervisor exits | `keep.ps1` starts it again (5 s, 30 s, 2 min, then 5 min) and alerts after 3 exits in 30 min; its children died with it and are started again | manual drill |
| microphone lost / speech lease lost in a session | besides LISTENER_LOST / WRAP, one coded alert (`study-mic`, `study-lease`) to toast + Telegram | `tests/test_voice_mode.py`, `tests/test_privacy.py` |
| Telegram unreachable | alerts stay in `alert_outbox`, oldest first, retried at 30 s, 2 min, 10 min, then hourly | `tests/test_alerts.py` |

Timeouts: `say()` 20 s; Brain 12 s overall with 1 retry (`BRAIN_DEADLINE_S`); OCR 15 s; ASR per utterance 10 s after VAD stop; Anki 10 s.

Backups: `data/*.db` are copied by the user's normal backup; `python -m leafi export --session <id>` writes a JSON summary for the parent (no audio).
