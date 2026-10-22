# Leafi — product

Vocabulary lives in [`../GLOSSARY.md`](../GLOSSARY.md); terms below are used as defined there.

## Purpose

Leafi is a household AI agent. It does family tasks through whatever hardware the home has: cameras with speakers, a PC, small boxes with a screen. Its first track reminded and verified a child's habits. Its current and primary track helps a 10-year-old learn English from physical books: see the page, listen to the reading, help with words that are read wrong, accept corrections when Leafi itself misread the page, explain what the child did not understand, and bring it all back for review.

## Users

- **Learner**: the child, age 10, learning English. Reads aloud, answers questions, corrects Leafi.
- **Parent**: sets up devices and books, reads summaries, receives notifications, curates Anki.
- **Agents**: Claude Code / Codex sessions that build and maintain Leafi; the docs are written for them first.

## Principles (non-negotiable)

1. Images, faces and poses never leave the LAN. Book-page images are images. Vision runs locally.
2. The learner's voice stays local by default. ASR and pronunciation scoring run locally; the cloud Brain receives text only (page excerpts, miscue words, session summaries), never audio, never identity.
3. Cameras never enter the bathroom. For study, the camera looks at the desk and the book.
4. Transparent to the child: Leafi is a coach and teammate, not surveillance. Coach voice everywhere.
5. Hardware is a configuration, not a dependency. Zero mouths, one mouth or three mouths must all work; the study loop must run with typed text and no camera.

## Requirements (decision state: Candidate · Proposed · Accepted · Implemented)

### Hardware independence

| id | Requirement | State |
|---|---|---|
| H1 | A session obtains capabilities (Eye, Ear/Listener, Mouth, Face, Presence, Notifier) from the Hub, never a device by brand. | Implemented (2026-10-20) |
| H2 | Devices and their capabilities are declared in `config/devices.yml`; a device may provide several capabilities. | Implemented (2026-10-20) |
| H3 | Voice policy: `all`, `primary`, `none`. With no Mouth available, every line is shown on every Face and logged. | Implemented (2026-10-20) |
| H4 | Adapters in v1: go2rtc camera (Eye, Mouth, optional Ear), local PC (Ear, Mouth, Face), typed console (Listener, Face), Frigate presence, Bark/Telegram notifier. | Implemented except Frigate presence and the camera Ear (2026-10-20); real-device checks pending |
| H5 | Adapters planned, in their own future plan: xiaozhi ESP32 (Ear, Mouth, Face with subtitles), Wyoming satellite, Tapo camera. | Proposed |
| H6 | v1 device set: console, PC mic/speaker/terminal, Xiaomi camera Eye + Mouth; the study session holds a speech lease the habit track respects (ADR-0011). | Accepted |
| H7 | Reading is half-duplex: listening pauses while Leafi speaks; `stop` and `skip` work in every state, including during playback. | Accepted |

### Book study

| id | Requirement | State |
|---|---|---|
| B1 | Identify the Book from the camera (ISBN barcode or cover/title OCR) or from the learner saying the title; confirm with the learner. | Implemented with mock OCR and a fake camera (2026-10-20); real camera pending P-3 |
| B2 | Detect which Page is open (printed page number, else observation match per ADR-0010) and keep page revisions per Page. | Implemented with mock OCR (2026-10-20); page-turn threshold to be calibrated on the camera (P-3) |
| B3 | Listen to the learner reading and align the Utterance to the current page revision per the reading algorithm (ADR-0013); a disagreement is a candidate miscue, not a judgement. v2: a real-word misreading is a candidate, rereads and lost starts are tracked across the page, off-task speech is ignored, function words are never practised. | v1 implemented in text and voice mode (2026-10-20); v2 proposed (ADR-0013) |
| B4 | No correction while the learner reads. After reading, the `practise_errors` activity takes the cycle's candidate miscues (≤ 5 per cycle): show the sentence, model the word, invite a retry (≤ 2, skip always offered), record the practice outcome; an automatic pronunciation judgement is made only when `PRON_AUTO_JUDGE` is on after evaluation (ADR-0011). | Accepted (ADR-0017 §3.1, ADR-0013 v2 → Practice); the v1 form (practice at each sentence end) is implemented in text mode (2026-10-20) |
| B5 | On an OCR error the learner notices ("the book says *through*, not *though*"): accept the Correction by voice or text, store it as a revision, re-align, add the word to the Lexicon. | Implemented (2026-10-20) |
| B6 | On "I don't understand": explain the word or sentence in simple English first, Chinese second, with one example; record a Knowledge item. | Implemented (2026-10-20); Brain mock in tests, Claude backend real |
| B7 | Comprehension questions in the Coach voice when the sequencer picks the `quiz` activity: ≤ 4 per cycle, each answerable from the cited sentences, CROWD question types; a spoken answer counts only when confidently recognised; counted answers scored by keywords (ADR-0013 → CHECK outcomes) or by `judge` for open answers (ADR-0017 §3.4); misunderstandings recorded as Knowledge items. | Accepted (ADR-0017); the v1 form (≤ 2 questions after each page, keyword scoring) is implemented (2026-10-20) |
| B8 | Review: Knowledge items are pushed to Anki (deck `Leafi`, FSRS) through an outbox and a short review turn runs at the start of the next session. | Implemented against a fake AnkiConnect (2026-10-20); first real push happens at the owner's first non-mock session |
| B9 | Store Books, Pages, Reading sessions, Miscues, Knowledge items, Corrections in SQLite; export a session summary for the parent. | Implemented (2026-10-20) |
| B10 | Self-improvement: Corrections become page revisions; Lexicon is advisory (ADR-0011); recurring Miscues become Difficulties that steer Practice and cards. | Implemented in its advisory v1 form (2026-10-20) |
| B11 | B3–B8 work functionally in text mode (typed Utterances, console Face, no hardware): the same states, records and cards; pronunciation evidence is explicitly `none` and no acoustic success or failure is ever recorded. | Implemented (2026-10-20): `python -m leafi study --text --mock` |
| B12 | Repeated-reading fluency metrics (words per minute, accuracy) per Page over time. | Proposed |
| B13 | Chinese-language books and other subjects. | Candidate |

### Habits (first track)

| id | Requirement | State |
|---|---|---|
| T1 | Scheduled Tasks with presence / pose-and-dwell / vision-judge Verifiers, parent notifications, weekly report. | Implemented (`agent/`) |
| T2 | Habits run on the Hub instead of talking to go2rtc directly; one config, one database — its own future plan with a migration policy (codex review A7). | Proposed |
| T3 | The habit track attaches one frame to the parent's Telegram notification only when the owner sets `NOTIFY_WITH_SNAPSHOT=true` (default off); the study track never does. | Accepted (ADR-0011 amendment) |

## Non-goals

- No cloud vision, no cloud ASR, no face recognition in the cloud, ever.
- No full-duplex barge-in voice pipeline in v1; turns are explicit.
- No model fine-tuning in v1; improvement is data (ADR-0006).
- No grading or scores shown to the child as judgement; numbers are for the parent and for Practice ordering. No "wrong" without acoustic or practice evidence; the default is "let's hear it once more".
- No automatic rewriting of page text or ASR output by the lexicon in v1; improvement loops are advisory until measured (ADR-0011).
- No management web app; configuration is YAML plus the existing task editor.
