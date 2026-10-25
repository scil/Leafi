---
status: draft
---

# Plan: a live panel for the study session (watch it, and move it along)

## Purpose

The owner wants to use the reading feature at home now, while OCR is still being tuned. Today a running
`python -m leafi study` session can be followed only in its terminal, and moved only by typing `/commands` there.
This plan adds a **session panel** (a new term; industry: an operator console / admin dashboard): a page in the
existing web UI (`agent/webui`, 127.0.0.1:8770) that shows the live session and offers buttons that act on it.

Done looks like: during a real session the owner opens the panel on the PC, sees which learner, book, page and
activity is running, what Leafi last said, which prompt waits for an answer and how far the page read is, and can
press "skip", "next page", "answer for the learner", "go to activity X" or "stop" and see the session react within a
second.

## Context and orientation

- The session runs in its own process (`leafi/runner.py` → `leafi/study/harness/loop.py::run_session`). The web UI is
  another process (`agent/webui/__main__.py`, stdlib `http.server`, Host/Origin/token checks, an OCR tab that already
  reads `data/leafi.db` read-only through `leafi.study.page_history`).
- Every input reaches the session through `Inputs` (`leafi/study/harness/inputs.py`): a main Listener plus an optional
  non-voice **control source**. Typed text there is parsed by `leafi/study/controls.py` (`/skip`, `/stop`, `/next`,
  `/page N`, `/yes`, `/no`, `/good` …); any other text is an answer or reading. M7 design D21 stamps each input with
  the prompt (owner) that was current when it arrived, so a typed answer goes to the question on screen.
- At a boundary the learner may name an activity ("questions", "take a break"): `negotiate.py` sets
  `Boundary.wanted` and runs it with `override="learner_choice"`.
- What is durable already: `reading_sessions`, `activities` (kind, status, params, decided_by), `page_reads`,
  `utterances`, `observations`, `practices`, `retrieval_events`. What is only in memory: the current prompt and its
  text, the boundary's offers and exclusions, the arm, the deadlines, the reading pointer between writes.

## Design choices (for the owner; recommendation first)

**C1. Where the panel gets live state and sends actions.**

- (a, recommended) The study process opens a small loopback endpoint of its own, served by a new device adapter
  `leafi/devices/panel.py` that is a Face (it records every `Display`) and a non-voice Listener (button presses
  become typed utterances), plus a read-only `status()` the harness fills. The web UI's new "Reading" tab calls it
  through the web UI's own server (one origin, one token). The endpoint exists only while a session runs; the tab
  then shows "no session" and the last session from the database.
- (b) Database only: the session writes a `live_status` row; the panel writes a `panel_commands` row the session
  polls. No new port, but a migration on the owner's file, a polling delay, and two writers on `leafi.db`.
- (c) A status file `data/study-live.json` plus a command file. No migration, but files as a queue race and leave
  stale state after a crash.

(a) reuses the control-source path, so every button is something a typed console line can already do, and the
harness rules (stop cancels speech, skip cuts the line, a page turn becomes a continuation) apply unchanged.

**C2. What an "answer for the learner" counts as.** The learner's evidence (item status fold, Difficulties,
`confirmed` words) must stay honest; ADR-0013 says `confirmed` needs acoustic evidence.

- (a, recommended) A panel answer is a typed utterance with source `panel`; it moves the session exactly like a
  typed console answer (typed answers already never count as acoustic evidence), and every row it creates carries
  that source so the export and the Brain's observation can tell it apart.
- (b) Panel answers move the session but write no evidence at all (outcome `skipped`-like). Cleaner data, but needs
  a new branch in each activity.
- (c) Allowed only for guest or `--mock` sessions.

**C3. Who may open the panel.** Loopback only, the web UI's token, as now. The page shows the child's words and
first name, so it is not exposed on the LAN (a phone on the Wi-Fi cannot open it). Opening it to the LAN is a later,
separate privacy decision.

## Panel content (phase 1, read-only)

- Header: learner (or guest), book, printed page, arm (`brain`/`default`), elapsed vs soft/hard deadline, Mouths
  and Ear in use, Eye online, lease held.
- Now: the running activity (kind, params, decided_by, started at), the prompt that waits for an answer and its text
  (the last `say`/`ask` line), "Leafi is speaking" / "listening".
- Reading progress: sentences read / total of the open page read, words committed vs candidates, the current
  sentence with each token's state (read, unread, candidate), current page text version (link to the OCR tab).
- Session timeline: every activity row of this session with status and outcome; the last 20 lines said and heard
  (`Display` history), each with the prompt it belonged to.
- Boundary: the menu (`allowed(s)`), the offered activity, excluded kinds.

## Actions (phase 2)

Each button sends one typed line through the panel Listener; nothing bypasses `Inputs` or the activities.

| Button | Sends | Effect (existing rule) |
| --- | --- | --- |
| Skip line / item | `/skip` | cuts the line while speaking, else skips the item or activity (ADR-0017 §2.1) |
| Stop session | `/stop` | latch `stop`, closing line, finalize |
| Next page | `/next` | page turn → `read_listen` continuation |
| Page N with this text | `/page N --text <file>` | the panel saves the pasted or OCR-tab text to `cache/` first |
| Yes / No | `/yes`, `/no` | answers an offer or a confirm prompt |
| Review ease | `/again` … `/easy` | `review_anki` |
| "I know this word" | `/know` | `teach_items` / `recall_items` item `ignored` |
| Answer for the learner | `/say <text>` | answers the current prompt; never counts as the child's (design D8); refused in `learner_questions` |
| Go to activity X | new `/do <kind>` | ends the running activity `completed` and runs X, or is refused when X is not on the menu (design D7) |
| Fix a word | `/fix OLD NEW` | a correction revision (ADR-0010), source `parent` |
| Finish reading this page | repeated `/skip` until the page read ends | no `confirmed` without acoustic evidence (ADR-0013) |

`/do <kind>` and `/say <text>` are the new controls. "Jump ahead" means end the current activity and choose the next
one; it never edits stored state. The design (`2026-10-25-study-session-panel-design.md`) is the reference for every
mechanism; this table only lists the buttons.

## Steps

1. **Design gate (AGENTS.md → Verification).** Research `docs/research/2026-10-25-session-panel.md`; design rev 1,
   three reviewers (round 1 compared in `reviews/2026-10-25-session-panel-round-1-comparison.md`); rev 2 answers it;
   a codex increment round on rev 2.
2. **Implementation:** the design's steps 1–8 (ADR-0017 amendments and the one predicate; `/do`; several typed
   sources; the snapshot; records; the device and wiring; the web UI tab; the console button and docs).

## Validation

- `.venv\Scripts\python -m pytest -q` green after each step; a mock run
  `python -m leafi study --text --mock --panel --book X --page-text <file>` driven only from the panel through a full
  session (identify, read with a page turn, quiz answered from the panel, `/do break`, stop).
- No camera audio in any test (AGENTS.md); `--mock` or `--mouth pc` only.
- The endpoint refuses a non-loopback Host, a missing token and a cross-origin POST (tests).

## Risks

- A second typed source changes `Inputs`' demand-driven reads (D21): design D2.
- Panel answers could hide a real reading problem in the data: design D8 keeps them out of every evidence row.
- The snapshot is read from another thread: design D1 publishes it by reference from the loop.

## Decision log

- 2026-10-25 owner: C1(a) the study process hosts the endpoint in a device the web UI proxies; C2(a) panel answers
  move the session but are told apart from the child's; C3 loopback only.
- 2026-10-25 owner, after round 1: a panel question in `learner_questions` is refused (no egress of the owner's
  text); panel lines are stored as text and counted, never evidence, with no migration; panel Anki eases go to Anki
  as the child's review; the runtime file keeps the profile's default permissions.
- 2026-10-25 owner, on rev 4: the safe-point rule of `/do` is shown in the UI (design D5: a note before the press,
  a banner with what the switch waits for, then the result).
- 2026-10-25 author, with the reviewers' agreement (reversible by the owner): the panel never leads after an Ear
  loss (`listener_lost_no_console` as today); `/do` ends the activity `completed` with `ended_by = "do"` and skips
  nothing; when a panel and a console line answer one prompt, the first delivered wins and the other is shown as
  dropped.

## Progress

- [x] 2026-10-25 plan drafted; owner chose C1(a), C2(a).
- [x] 2026-10-25 research (`docs/research/2026-10-25-session-panel.md`), design rev 1, round 1 with three reviewers
  (codex out of quota until 15:04; a second fresh Claude stood in), compared; owner answered four questions; rev 2.
- [x] 2026-10-25 round 2 (codex on rev 2, 13 findings) → rev 3 (`/do` restated on activity cancellation); round 3
  (codex on D7, 9 findings: cancelling at any await is unsafe) → rev 4 (`/do` at safe points; TD-29, TD-30); owner:
  show the safe-point rule in the UI; round 4 (fresh Claude for codex, out of quota; 0 High) → rev 5.
- [x] 2026-10-25 owner: start implementation without the optional codex round on rev 5; design docs committed
  (2f6f55a).
- [x] 2026-10-25 design step 1 (7e667d5): ADR-0017 §1, §2.1, §3.4 amended; `scoring.counts_as_answer` is the one
  predicate; `controls.of`, `/say`; every D8 site; `tests/test_panel_lines.py` (13 tests); full suite 1142 passed.
- [x] 2026-10-25 design step 2: `/do <kind>` at safe points — `Latch.want` and `Jump`, a payload-free wake,
  `Jump` at an activity's owned prompts and listens, `activity_over()` true while a want is set, `progress` kept by
  each jumpable activity, every negotiate exit and the offer listen checked first, no Brain `sequence` and no
  continuation while a want is set, `Inputs.accepting`; `tests/test_do.py` (15 tests); full suite 1155 passed.
- [ ] Design steps 3–8.
