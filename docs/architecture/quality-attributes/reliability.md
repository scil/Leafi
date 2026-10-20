# Reliability

Objective: a study session never ends because a model or device failed; it degrades.

| Failure | Behaviour | Check |
|---|---|---|
| Claude API down / no key | Brain falls back to Ollama, then to static Coach-voice phrases (`study/phrases.py`); the session continues | `tests/test_coach.py::test_brain_fallback_chain` |
| TTS backend fails | `say()` shows text on Faces, logs, returns; next line tries again | `tests/test_hub.py::test_say_without_mouth` |
| Camera unreachable | Eye returns `None`; page tracker keeps the last Page; Leafi asks the learner to read the page number | `tests/test_page_tracker.py` |
| OCR low confidence | second opinion (`OCR_SECOND_OPINION`), then ask the learner to read the first line; Page text marked `unsure` | `tests/test_ocr_pipeline.py` |
| Anki closed | cards queue in `knowledge_items` with null `anki_note_id`; pushed at the next wrap | `tests/test_anki.py::test_queue_when_unreachable` |
| Process crash mid-session | `reading_sessions.ended_at` null; next start closes it with `summary="interrupted"` | `tests/test_storage.py::test_close_stale_sessions` |
| go2rtc speaker push rejected (space in src, codec) | logged with the src string; no retry storm (one retry) | existing `agent/speaker.py` behaviour, to be kept in the adapter |

Timeouts: `say()` 20 s; Brain 30 s; OCR 15 s; ASR per utterance 10 s after VAD stop; Anki 10 s.

Backups: `data/*.db` are copied by the user's normal backup; `python -m leafi export --session <id>` writes a JSON summary for the parent (no audio).
