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
| H1 | A session obtains capabilities (Eye, Ear/Listener, Mouth, Face, Presence, Notifier) from the Hub, never a device by brand. | Accepted |
| H2 | Devices and their capabilities are declared in `config/devices.yml`; a device may provide several capabilities. | Accepted |
| H3 | Voice policy: `all`, `primary`, `none`. With no Mouth available, every line is shown on every Face and logged. | Accepted |
| H4 | Adapters in v1: go2rtc camera (Eye, Mouth, optional Ear), local PC (Ear, Mouth, Face), typed console (Listener, Face), Frigate presence, Bark/Telegram notifier. | Accepted |
| H5 | Adapters planned, in their own future plan: xiaozhi ESP32 (Ear, Mouth, Face with subtitles), Wyoming satellite, Tapo camera. | Proposed |
| H6 | v1 device set: console, PC mic/speaker/terminal, Xiaomi camera Eye + Mouth; the study session holds a speech lease the habit track respects (ADR-0011). | Accepted |
| H7 | Reading is half-duplex: listening pauses while Leafi speaks; `stop` and `skip` work in every state, including during playback. | Accepted |

### Book study

| id | Requirement | State |
|---|---|---|
| B1 | Identify the Book from the camera (ISBN barcode or cover/title OCR) or from the learner saying the title; confirm with the learner. | Accepted |
| B2 | Detect which Page is open (printed page number, else text fingerprint) and keep Page text cached per Page. | Accepted |
| B3 | Listen to the learner reading and align the Utterance to the current page revision; produce observations (matched/substituted/deleted spans, insertions) and a committed cursor; a disagreement is a candidate miscue, not a judgement (ADR-0009). | Accepted |
| B4 | On a candidate miscue at a sentence end: model the word, invite a retry (≤ 2, skip always offered), record the practice outcome; an automatic pronunciation judgement is made only when `PRON_AUTO_JUDGE` is on after evaluation (ADR-0011). | Accepted |
| B5 | On an OCR error the learner notices ("the book says *through*, not *though*"): accept the Correction by voice or text, store it, re-align, add the word to the Lexicon. | Accepted |
| B6 | On "I don't understand": explain the word or sentence in simple English first, Chinese second, with one example; record a Knowledge item. | Accepted |
| B7 | After a passage: one or two comprehension questions in the Coach voice; record misunderstandings as Knowledge items. | Accepted |
| B8 | Review: due Knowledge items are pushed to Anki (deck `Leafi`, FSRS) and a short review turn runs at the start of the next session. | Accepted |
| B9 | Store Books, Pages, Reading sessions, Miscues, Knowledge items, Corrections in SQLite; export a session summary for the parent. | Accepted |
| B10 | Self-improvement: Corrections become Page text; Lexicon biases ASR and post-corrects OCR; recurring Miscues become Difficulties that steer Practice and cards. | Accepted |
| B11 | B3–B8 work functionally in text mode (typed Utterances, console Face, no hardware): the same states, records and cards; pronunciation evidence is explicitly `none` and no acoustic success or failure is ever recorded. | Accepted |
| B12 | Repeated-reading fluency metrics (words per minute, accuracy) per Page over time. | Proposed |
| B13 | Chinese-language books and other subjects. | Candidate |

### Habits (first track)

| id | Requirement | State |
|---|---|---|
| T1 | Scheduled Tasks with presence / pose-and-dwell / vision-judge Verifiers, parent notifications, weekly report. | Implemented (`agent/`) |
| T2 | Habits run on the Hub instead of talking to go2rtc directly; one config, one database — its own future plan with a migration policy (codex review A7). | Proposed |
| T3 | Whether the habit track keeps attaching one frame to the parent's Telegram notification (the study track never does). | Candidate — owner's decision (TD-9) |

## Non-goals

- No cloud vision, no cloud ASR, no face recognition in the cloud, ever.
- No full-duplex barge-in voice pipeline in v1; turns are explicit.
- No model fine-tuning in v1; improvement is data (ADR-0006).
- No grading or scores shown to the child as judgement; numbers are for the parent and for Practice ordering. No "wrong" without acoustic or practice evidence; the default is "let's hear it once more".
- No automatic rewriting of page text or ASR output by the lexicon in v1; improvement loops are advisory until measured (ADR-0011).
- No management web app; configuration is YAML plus the existing task editor.
