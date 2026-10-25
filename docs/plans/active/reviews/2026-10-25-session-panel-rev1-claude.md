# Session panel design rev 1: fresh Claude review

Reviewer: a fresh Claude agent (Opus 5.5) on `reviews/prompts/session-panel-rev1.md`, 2026-10-25, independent of the
other two reviewers of round 1. Findings as reported; verification is in the round's comparison file.

## High

1. **D8 does not reach `teach_items` / `recall_items`.** `_ask_item` scores through `brain/scoring.py::confident`
   (28-29; used at 45, 52, 71), true for any typed line; `_score_item` writes a retrieval event and an encounter for
   every `success`/`fail` (`activities.py:816-828`). A panel "through" to an `item_said` prompt → `success` → a
   `typed` retrieval event + `teach_ok`; with `expect=item_used` the owner's text goes to the Brain's `judge` as the
   child's answer (`scoring.py:71-80`). Step 3's tests cover only quiz. Fix: one predicate in `scoring`, used by both;
   a test per scored kind (quiz, review, teach `item_said`/`cloze_word`/`item_used`, recall).
2. **D7: a `/do` during playback wakes nothing.** During playback `_deliver` only cuts the line
   (`inputs.py:173-176`). Announce band: `take_skip()` is false → `Run(a)` (`negotiate.py:156-162`). Argue band: the
   listen gets silence and `none` at argue → `Run(a)` (`negotiate.py:166, 196-197`). Quiz: the listen waits
   `CHECK_ANSWER_S`, in text mode `study_idle_s` then `idle_session` (`activities.py:640-646`). Fix: `do` cuts the line
   and always enqueues a wake item; `negotiate` checks the want before every `return Run(a)`.
3. **D7: a pending want does not end `read_listen`, and can end the session.** `activity_over()` is checked only
   after a completed sentence (`activities.py:309, 333`); the skip branch continues (`325-328`). `/do break`
   mid-sentence → `skip_read`, still listening; a silent child → hint → `idle_session` (`312-322`); text mode →
   `idle_session` after `study_idle_s` (`300-303`); two presses skip two sentences. Fix: check the want at the top of
   the loop and after the skip branch; consider ending without skipping (Q2(b)).

## Medium

4. **D8 amends ADRs while claiming to apply them.** The unconfident-answer rule is ADR-0017 §3.4, which says typed
   answers always count (0017:223); ADR-0013 has no §3.4. Practice "panel answer = attempt `skipped`" is a new
   ADR-0013 Practice rule ("Text mode uses exactly these rules", 0013:203-205) and settles the candidate
   `unsure(skipped)` for good (`rows.py:62-73`, `activities.py:403`). Fix: amend ADR-0017 §3.4 explicitly; in practice
   a panel free-text line is not an attempt (a noop, re-listen, no row), so ADR-0013 stays untouched.
5. **D2 vs D8 with the panel as the only source after an Ear loss.** The panel becomes main (`inputs.py:187-198`), a
   `read_listen` continuation runs (`loop.py:405-410`), D8 refuses to align, `mic_lost` tells the child "Type what you
   read" (`phrases.py:52`), then `idle_session`. Fix: keep `listener_lost_no_console` without a console, or define
   panel-only as skip-only with its own phrase and a test.
6. **D1: the snapshot goes stale.** No trailing refresh: `ask` → `show`, then `Display("listening")`
   (`inputs.py:214`) ms later is throttled away. At an activity end there is no `show` before the Brain `sequence`
   (`loop.py:386-390`). Fix: a refresher task spawned through the latch every 0.25–0.5 s driven by a dirty flag;
   refresh at `run_activity` start and end.
7. **D3: SELECTs inside `show()` on the loop thread can block lines.** `busy_timeout` 250 ms (`runner.py:31`); in the
   rollback-journal fallback a reader can wait on a writer; `hub.say` shows before TTS; `asyncio.wait_for`
   (`hub.py:197`) cannot interrupt synchronous code. Fix: a memory-only snapshot (the loop knows each activity's id,
   kind, status, outcome), or the web UI reads the activity list from the database itself.
8. **D1/D4 lifecycle.** (a) `shutdown()` waits for `serve_forever`; a never-started server (`LeaseHeld` at
   `loop.py:266`) hangs `close()` forever. (b) `close()` always removes the file: a second `study --panel` refused
   with `LeaseHeld` deletes the live session's file. (c) The web UI's delete races a new session's replace. Fix: start
   the server after the lease; `close()` stops only a started server and removes the file only if it holds its token;
   the web UI never deletes; `leafi.core.lease.pid_alive` (`lease.py:25`) and psutil `create_time` (as
   `egress.py:227-240`) instead of the token probe; "refuses" = 401/403 only.
9. **`?since=` across sessions.** The version restarts per process; scope it (`"<session_id>:<n>"`), compare by
   equality.
10. **Composition hazards.** Text mode takes the first listener as main (`app.py:79-81`, `87`). Console end of input
    is `/stop` (`console.py:47-48`): a panel-only session started without an interactive stdin stops at the first
    listen. Fix: the panel is never the study listener unless configured; with `--panel` and no terminal, do not
    attach the console (or ignore its EOF).

## Low

11. `learner_questions`: each panel line gets `questions_again` and uses a turn (`activities.py:753-755`); say so,
    test it (no egress of the owner's text).
12. Hint offer: a panel `/yes` supplies the word and creates a `supplied` candidate (`activities.py:225-249`):
    evidence from a press; decide it.
13. D6 parsing: `/fix` splits once (`controls.py:82-86`); `/page --text` rejoins with single spaces and resolves
    against the study process's cwd: absolute `cache_dir` path without spaces; free answers still go through the
    spoken grammar (`controls.py:112-113`): "stop", "skip", "page 5", "it is X not Y" act.
14. D5 vs code: the OCR tab opens a full `Store` per request (`agent/webui/__main__.py:51-56`), shared lock and
    journal pragma; polling it every second makes `migrate`/`backup` fail with `DatabaseInUse`. `_post_ok` accepts a
    missing Origin (`__main__.py:115`). From another loopback port `Sec-Fetch-Site` is `same-site`: refuse anything
    but `same-origin`/`none`.
15. D2 "the `None` of a non-main source stays dropped" is false after an Ear loss (`_console_is_main`,
    `inputs.py:164`); `_speak` hard-codes `"control"` (`inputs.py:315`). Track the main source by name.
16. D8 plumbing: `last_activity` is built in `sequence.py:64-71` from id, kind, status, not in `observe.py`
    (`notes._activity_leaves`, `notes.py:99-105`, already shows integer outcome fields); panel lines at a boundary
    belong to no activity; `/know` needs `activities.py:800` to pass `owner`; Q1(a): `anki.answer` also records
    `card_state` and re-folds the item (`anki.py:286-289`).
17. Missing pieces: `STUDY_PANEL_PORT` must be a `Settings` field (`test_architecture.py:138-147`); `pause`/`resume`
    (`ports.py:150-152`, `app.py:64`, `hub.py:317-323`); `close()` idempotent (`inputs.py:372-375` and the runner);
    check the want before the Brain `sequence` call (`loop.py:386-390`); the wake skip at an offer also excludes the
    offered kind (`negotiate.py:181-183`).
18. Provenance: the 0.2 s throttle and the lazy server start have none; D7 changes `activity_over`'s meaning and adds
    a Latch slot: mark as ADR-0017 amendments.

## Fine as designed

A console line and a panel line during one prompt (the second is dropped as stale; the test should assert it); a
panel line during playback; publish by reference, guarded `call_soon_threadsafe`, 202 at once; both hops' Host checks
and custom-header tokens (A5 confirmed); `/do` of a kind not on the menu; a second `/do` replacing the first.

## Tests missing

`/do` during playback at each band and during a quiz question; `/do` in `read_listen` with a silent child (voice and
text); two `/do`s in `read_listen`; teach and recall panel answers (no retrieval event, encounter or `judge`); a
panel answer in practice (no `practices` row); a panel `/yes` at the hint offer; `learner_questions` with panel
lines; Ear lost with the panel only; text mode with `--panel` keeps the console main; `close()` without start;
a refused second process keeps the live file; the throttle's trailing edge and a refresh at an activity end; `since`
across two sessions. Step 1 must include the wake item in `Inputs._deliver`; step 5 carries the runner, CLI and
`Settings` wiring.
