# Code locator

Search this file for the symptom or the user's words; read only the matching entry. Entries: trigger → start files → invariant/trap → smallest check.

## "speaker is silent" / "喇叭无声" / noise from the camera
- Start: `agent/speaker.py`, `tools/go2rtc/PATCHES.md`, `.env` (`SPEAKER_AUDIO_CODEC`, `GO2RTC_URL`, `SPEAKER_SRC_DIR`).
- Trap: go2rtc API sources may not contain spaces; the host go2rtc is a patched build — a stock upgrade brings the noise back; Xiaomi = `opus`, Tapo = `pcma`; src dir must match the go2rtc instance's filesystem (host path vs `/cache/tts`).
- Also: while a Leafi study session holds `data/leafi.lock`, the habit speaker logs instead of speaking; the study Mouth is `leafi/devices/go2rtc_camera.py` (same facts, `tests/test_go2rtc_camera.py`).
- Check: `python -m agent.main --say "test"` with `SPEAKER_BACKEND=local` first, then `go2rtc`.

## "camera stream disconnects every few minutes"
- Start: `tools/go2rtc/PATCHES.md` (patch 2), `scripts/win/health.ps1`.
- Invariant: host go2rtc, not the container, holds the cs2 P2P connection.
- Check: health script shows dial count stable over 10 minutes.

## "task editor rejected my prompt" / 红线 01
- Start: `agent/tasks.py::validate`, `GUARD_PHRASES`.
- Invariant: a vision-judge prompt must say it does not identify people; empty prompt only allowed for built-in kinds.
- Check: `tests/test_tasks.py`.

## "Leafi says it is listening but nothing happens" (study)
- Start: `leafi/app.py::_compose_voice_listener`, `leafi/services/asr/__init__.py::VoiceListener`, `leafi/devices/local_pc.py`.
- Trap: listening is paused while any Mouth plays (half-duplex, `core/hub.py::ListeningGate`); without an ASR model (`doctor` → `asr: missing …`) the voice Listener is not built and the console Listener takes over with a warning.
- Check: `python -m leafi study --text --mock --book X --page-text tests/fixtures/pages/p1.txt`; then `python -m leafi doctor` shows `asr ok`.

## "Leafi read the page wrong" / OCR mistake / correction did not stick
- Start: `leafi/study/corrections.py::apply_correction`, `leafi/study/pages.py` (`current_text`, `add_ocr_revision`).
- Invariant: corrected text wins; each correction is one transaction (correction row + revision with edit map + state re-tokenised + overlapping miscues of any revision invalidated + Difficulties + lexicon); a later OCR keeps verified spans.
- Check: `tests/test_corrections.py`, `tests/test_page_tracker.py::test_verified_correction_survives_a_later_misread_and_feeds_the_lexicon`.

## "wrong word flagged" / alignment surprises (cursor, unread, reread, line skip)
- Start: `leafi/study/alignment.py` (`align`, `best_path`), `leafi/core/text.py` (`norm`, contractions, numbers; bump `TOKENIZER_VERSION` on change). Rules: ADR-0013 only.
- Trap: fuzzy ≥ 0.80 matches near-misses (`though`/`through`); a short prefix before a skipped line can lose to jump + substitutions (plan Surprises).
- Check: `tests/test_alignment.py`; add the sentence as a walkthrough-style test.

## "practice never ends" / "skip did nothing" / controls
- Start: `leafi/study/session.py` (`practice`, `_practise_word`, `_read_control`, `_depart`), `leafi/study/controls.py`.
- Trap: a spoken control that equals the page text at the cursor is read, not executed; `/back N` counts from the sentence just read when `pcur` sits at a sentence start or at the page end (`alignment.back`).
- Check: `tests/test_practice.py`, `tests/test_session_controls.py`.

## "duplicate Anki cards" / "review answer lost"
- Start: `leafi/study/anki.py` (`sync_outbox`, `answer`, `reconcile`), table `anki_outbox`, `review_answers`.
- Invariant: dedupe by tag `leafi-id::<anki_item_key>` before every add; a `sent` answer is never replayed; parent edits win.
- Check: `tests/test_anki.py` (fake AnkiConnect in `tests/fakes/anki.py`).

## "habit reminder silent during study" / "two voices at once"
- Start: `leafi/core/lease.py`, `agent/speaker.py::_study_lease_held`, `data/leafi.lock`.
- Invariant: the habit speaker logs instead of speaking while a live study session holds the lease; a dead pid or expired lease is free.
- Check: `tests/test_speaker_lease.py`.

## "something went to the cloud" / privacy
- Start: `docs/architecture/quality-attributes/security.md` (egress table), `leafi/services/brain/__init__.py::BrainRequest`, `leafi/study/coach.py` (redaction, page window), `leafi/core/netguard.py`.
- Check: `tests/test_privacy.py` (canaries + `LEAFI_NO_NETWORK=1` subprocess), `tests/test_architecture.py`.