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

## "go2rtc / Frigate / Docker keeps restarting" / "restarts paused" alert / no alert arrived / 告警
- Start: `leafi/ops/supervisor.py` (`ServicePolicy`, `poll`, `build`, `observe_camera`, `Child`), `leafi/ops/alerts.py::deliver`, `leafi/core/alerts.py` (catalog), `scripts/win/keep.ps1`; ADR-0016.
- Invariant: once the `leafi-supervisor` task exists, only the supervisor starts or kills its children; at most 3 recoveries per service per outage; containers are not probed while Docker is down; alerts leave only as catalog sentences (toasts at once, Telegram oldest-first).
- Check: `python -m leafi alert --status` (per-service budget, unsent rows), `data/logs/supervisor.log`, `data/logs/keep-supervisor.log`; `tests/test_supervisor.py`, `tests/test_alerts.py`.

## "supervision timing settings conflict" / changed a timing and nothing happened
- Start: `leafi/ops/timing.py` (`resolve`, `violations`, `derived`, `as_env`), `scripts/win/timing.ps1`; ADR-0016 "Timing settings".
- Invariant: one parser; a broken invariant resets every setting involved to its default, repeated until consistent; the supervisor never exits over timing.
- Check: `python -m leafi timing` (values in use, derived times, conflicts), `tests/test_timing.py`.

## "Leafi check: …" alert / dashboard red / heartbeat alarm from Healthchecks.io
- Start: `leafi/ops/checks.py` (one pure rule per check, `build`, `CheckRunner`, `heartbeat`, `push`), `config/gatus/config.yaml`; ADR-0016.
- Invariant: checks never repair; one alert per drift and one when it passes again; Gatus has no alerting provider; the heartbeat is a bodyless GET.
- Check: `python -m leafi checks` (each check ok / FAIL), the dashboard at http://127.0.0.1:18080, `tests/test_checks.py`.

## "task editor rejected my prompt" / 红线 01
- Start: `agent/tasks.py::validate`, `GUARD_PHRASES`.
- Invariant: a vision-judge prompt must say it does not identify people; empty prompt only allowed for built-in kinds.
- Check: `tests/test_tasks.py`.

## "Leafi says it is listening but nothing happens" (study)
- Start: `leafi/app.py::_compose_voice_listener`, `leafi/services/asr/__init__.py::VoiceListener`, `leafi/services/asr/vad.py` (Silero), `leafi/devices/local_pc.py`.
- Trap: listening is paused while any Mouth plays (half-duplex, `core/hub.py::ListeningGate`); without an ASR model (`doctor` → `asr: missing …`) the voice Listener is not built and the console Listener takes over with a warning. The default PC input on the deployment PC is a Bluetooth hands-free headset mic (narrowband, starts ~1 s late); `input_device` in `devices.yml` takes a name fragment and picks WASAPI over MME when the name is ambiguous (P-6).
- Check: `python -m leafi doctor` all `ok`; `scripts/probes/p6_capture.py --list` then `--seconds 3` shows rms > 0 while someone talks; `LEAFI_HW_TESTS=1 pytest tests/test_hardware.py` (Kokoro → Silero → Parakeet → alignment).

## "Leafi can't read the page" / page turn not noticed / OCR garbage from the camera
- Start: `leafi/services/ocr/rapidocr.py` (`_read`, `ROTATIONS`, `MIN_GOOD_LINES`), `leafi/study/page_tracker.py` (`frame_diff`, `settle`, `changed`), settings `OCR_VERSION`, `OCR_AUTO_ROTATE`, `PAGE_DIFF_THRESHOLD`.
- Trap: the desk camera's noise floor is 2.3–3.0 grey levels and the stream has a burnt-in timestamp that OCR always reads; a sideways book reads as nothing at 0°; in the current wide shot the page is ~20 % of the frame and OCR is partial (TD-21). The printed page number may be a stray glyph.
- Check: `scripts/probes/p3_ocr_compare.py --capture 3 --out cache/desk` then `--dir cache/desk` (silent snapshots); `LEAFI_HW_TESTS=1 pytest tests/test_hardware.py -k rotation`.

## "Leafi stopped by itself" / "I can't hear the microphone any more" / two sessions
- Start: `leafi/study/harness/inputs.py` (`_renew_lease`, `_listener_lost`, `listen`), `leafi/core/lease.py`, `leafi/services/asr/__init__.py::VoiceListener._pump`.
- Invariant: a failed lease renewal (another launch took `data/leafi.lock` after the TTL expired, e.g. after a suspend) stops this session at its next renewal (≤ `LEASE_TTL_S`/3) with no more audio and summary `lease_lost=true` (TD-15); a dead Ear raises `ListenerLost` once, the session says so and continues on the console when one exists, else stops (`LISTENER_LOST`, TD-16). Replug = restart the session.
- Check: `tests/test_voice_mode.py`.

## "Parakeet heard 'Yeah.' in silence" / ASR oddities
- Start: `leafi/services/asr/sherpa.py` (P-1 contract in the module docstring: space-prefixed pieces, 80 ms timing, `ys_log_probs` confidence, 1 s padding, hotwords via `bpe.vocab`).
- Trap: inputs shorter than 0.5 s hallucinate; the backend pads to `MIN_SECONDS`; the Silero VAD never emits segments shorter than 0.25 s.
- Check: `tests/test_hardware.py::test_sherpa_returns_nothing_for_short_silence_and_noise`; `scripts/probes/p1_parakeet.py` for the full report.

## "pronunciation judge" / `PRON_AUTO_JUDGE` / OpenPronounce
- Start: `leafi/services/pronunciation/openpronounce.py` (offline wiring: HF cache under `models/pronunciation/hf`, Kokoro reference registered as the `leafi` TTS backend, espeak from `espeakng-loader`), `docs/engineering/pronunciation-evaluation.md` (the gate), `scripts/probes/p4_openpronounce.py` (`--eval`).
- Trap: the scorer loads ~2.5 GB on first use (15 s on the GPU); a correct native "little" scored 0.65 and homophones score 1.0, so `PRON_CONFIRM_BELOW` must come from the evaluation, not from a guess.
- Check: `LEAFI_NO_NETWORK=1 python scripts/probes/p4_openpronounce.py`.

## "Leafi read the page wrong" / OCR mistake / correction did not stick
- Start: `leafi/study/corrections.py::apply_correction`, `leafi/study/pages.py` (`current_text`, `add_ocr_revision`).
- Invariant: corrected text wins; each correction is one transaction (correction row + revision with edit map + state re-tokenised + overlapping miscues of any revision invalidated + Difficulties + lexicon); a later OCR keeps verified spans.
- Check: `tests/test_corrections.py`, `tests/test_page_tracker.py::test_verified_correction_survives_a_later_misread_and_feeds_the_lexicon`.

## "wrong word flagged" / alignment surprises (cursor, unread, reread, line skip)
- Start: `leafi/study/alignment.py` (`align`, `best_path`), `leafi/core/text.py` (`norm`, contractions, numbers; bump `TOKENIZER_VERSION` on change). Rules: ADR-0013 only.
- Trap: fuzzy ≥ 0.80 matches near-misses (`though`/`through`); a short prefix before a skipped line can lose to jump + substitutions (plan Surprises).
- Check: `tests/test_alignment.py`; add the sentence as a walkthrough-style test.

## "practice never ends" / "skip did nothing" / controls
- Note: `/skip` typed while Leafi is talking only cuts that line (`Hub.skip_current`); it is not delivered to the state, so practice still waits for a retry or another `/skip`. ADR-0013 promises only `/stop` during playback (plan Decision log, review 2 D4).
- Start: `leafi/study/harness/activities.py` (`practise_errors`, `read_listen`, `_page_turn`), `leafi/study/harness/rows.py::close_cycle`, `leafi/study/controls.py`.
- Trap: control precedence wins everywhere, even when the page text says "stop" or the practised word is "skip" (ADR-0013 "skip always"); only a spoken utterance longer than 6 words is never a control; `/back N` counts from the sentence just read when `pcur` sits at a sentence start or at the page end (`alignment.back`).
- Check: `tests/test_practice.py`, `tests/test_session_controls.py`.

## "/stop does nothing while Leafi is talking" / "page turned but Leafi kept the old page"
- Start: `leafi/study/harness/inputs.py` (`say`, `_deliver`, `listen`, `_watch_page`), `leafi/core/hub.py` (`stop_speaking`, `skip_current`), `leafi/study/page_tracker.py::changed`.
- Invariant: the console is read by one persistent task also during playback; `/stop` cancels speech and is routed to the current state; an Eye page turn becomes `/page`. Text mode has no Eye.
- Check: `tests/test_control_dispatch.py`.

## "duplicate Anki cards" / "review answer lost"
- Start: `leafi/study/anki.py` (`sync_outbox`, `answer`, `reconcile`), table `anki_outbox`, `review_answers`.
- Invariant: dedupe by tag `leafi-id::<anki_item_key>` before every add; a `sent` answer is never replayed; parent edits win.
- Check: `tests/test_anki.py` (fake AnkiConnect in `tests/fakes/anki.py`).

## "habit reminder silent during study" / "two voices at once"
- Start: `leafi/core/lease.py`, `agent/speaker.py::_study_lease_held`, `data/leafi.lock`.
- Invariant: the habit speaker logs instead of speaking while a live study session holds the lease; a dead pid or expired lease is free.
- Check: `tests/test_speaker_lease.py`.

## "something went to the cloud" / privacy
- Start: `docs/architecture/quality-attributes/security.md` (egress table, privacy settings), `data/leafi.db` table `egress_log` (one row per attempt: destination, purpose, learner, status, transmissions; an HMAC, never a body), `leafi/privacy/egress.py` (`prepare`, the mediating transport), `leafi/privacy/destinations.py`, `leafi/privacy/pseudonym.py` (lists, surrogates), `leafi/privacy/detector.py`, `leafi/core/netguard.py` + `leafi/bootstrap.py` (the socket guard).
- A refusal: the caller got a 403 `{"refused": reason}` or `egress.Refused`; the reason names the rule (a model-bound destination without its model, a version changed, the `.env` fingerprint changed: restart).
- A spoken line went to edge-tts / stayed local: `leafi/services/tts/__init__.py::TtsService._must_stay_local` (provenance, protected names).
- Check: `tests/test_privacy.py` (the wire beneath egress, canaries, `LEAFI_NO_NETWORK=1` subprocess), `tests/test_egress.py`, `tests/test_netguard.py`, `tests/test_pseudonym.py`, `tests/test_architecture.py`.

## "a child's school / a protected name"
- Start: `python -m leafi privacy schools`, `python -m leafi privacy terms`; `leafi/privacy/settings.py` (the learner privacy writer, `household_terms` helpers); enrolment's question in `leafi/study/harness/identify.py::ask_school`.
- Check: `tests/test_privacy_settings.py`, `tests/test_identify.py`.