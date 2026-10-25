Design round 3 (one decision). Review **D7** of revision 3 of
`docs/plans/active/2026-10-25-study-session-panel-design.md` as a design, not as prose. Rev 3 restates `/do` on the
session's existing `stop` cancellation, narrowed to a nested anyio cancel scope around the running activity, after
two rounds found new failures in rev 1's skip and rev 2's `listen()` exception
(`reviews/2026-10-25-session-panel-round-1-comparison.md` T2–T4, `reviews/2026-10-25-session-panel-rev2-codex.md`
findings 1, 2, 4, 5, 6). Other decisions are out of scope this round unless D7 breaks them.

1. **Cancel safety, the main question.** Today a cancellation at any await of an activity is followed only by
   `finalize`. Under D7 the session goes on: the next boundary and activity run after it. Walk every activity in
   `leafi/study/harness/activities.py` (and what it calls: `world.py`, `rows.py`, `pages`, `knowledge`, `anki.py`,
   `leafi/study/brain/generate.py`, `scoring.py`, `filler.py`) and list each write sequence that spans an await, with
   what the next activity would see if the scope were cancelled at that await. Which of them are already reachable
   today by `aborted_stale` (`StaleInput` at a listen) and handled, and which are new?
2. Hand-execute D7 on the code: a want during playback and during the listen at each autonomy band
   (`negotiate.py`); during a quiz question after three answers; mid-sentence in `read_listen` (text and voice);
   during a Brain wait (`Inputs.controls_only`, `brain/call.py`) and the filler; in `read_aloud` while it reads;
   twice; at a setup prompt; with `/stop` right after; while `run_activity`'s `finish_now` or the normal end is
   writing; while the session's own scope is being cancelled. Check the absorbed cancellation against anyio 4.14's
   rules for nested scopes (`.venv/Lib/site-packages/anyio/`), including `except*` in `run_session` and
   `run_activity`'s `except (Terminal, cancelled)` clause.
3. `progress`: does each listed count reach the Ledger (`ledger.py`) and the summary (`records.summary`) on both
   finish paths? Is any other outcome field read later (`notes.py`, `sequence.py`, `item_status`)?
4. The Hub change (`hub.py`: `_skip_next` cleared on a generation bump): can it lose a skip the console meant?

If nothing needs to change, say so plainly. Otherwise report findings as a numbered list, each with severity
(High / Medium / Low), the decision or line, the concrete failure (inputs → outcome), and a suggested fix. Do not edit
any file.
