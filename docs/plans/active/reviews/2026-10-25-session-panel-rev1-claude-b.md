# Session panel design rev 1: fresh Claude review (codex's stand-in)

Reviewer: a fresh Claude agent (Opus 5.5) on `reviews/prompts/session-panel-rev1.md`, 2026-10-25, standing in for
codex (`gpt-6-astra` refused: usage limit until 15:04), told to hand-execute failure paths as codex does.
Independent of the other two reviewers. Findings as reported; verification is in the round's comparison file.

## High

1. **D8 misses `teach_items` / `recall_items`**: `scoring.confident` (`scoring.py:28-29`) is true for any typed line;
   `_score_item` (`activities.py:816-828`) writes a `typed` retrieval event and an encounter; `item_used` sends the
   parent's text to the Brain's `judge` (`scoring.py:68-71`), an egress the design does not mention. Fix: one shared
   predicate; tests for teach and recall, `item_used` making no Brain call.
2. **D7: `/do` in `read_listen` never ends it; in text mode it ends the session.** `activity_over()` only at
   `activities.py:309, 333`; the skip branch (`325-328`) continues; text mode → `idle_session` (`300-303`); voice and a
   silent child → hint → `idle_session` (`320-322`); each press skips one more sentence. Fix: a dedicated exception
   from `listen()` mapped in `run_activity`, or a wake item plus `activity_over()` at the top of every loop.
3. **D7: "woken by a posted skip" wakes nothing.** `post_skip` appends to a deque (`latch.py:107-108`); `listen`
   waits on the stream (`inputs.py:220`); during playback `_deliver` only cuts the line (`174-176`). Voice: `/do`
   during a quiz question waits `CHECK_ANSWER_S`; during `break_start` the full break runs; taken by `_pause`, the
   break ends `skipped` (`564-565`). Quiz while listening works.

## Medium

4. **D7 at a boundary**: announce band never returns to the loop top (`negotiate.py:156-162`) → `Run(a)`, may open a
   cycle (`world.py:273-280`) and end with nothing done; ask bands exclude the offered kind (`181-183`); the `wanted`
   path skips `drain_skips` (only at 149), so a leftover skip eats the wanted activity's first item. Fix: `take_want`
   before every `return Run(a)` and in `_body` before `run_activity`; drain skips when a want is taken.
5. **D7, a kind not on the menu**: the running activity ends first, then "I can't". Fix: check against
   `s.boundary.menu` when the line arrives; show the refusal in the snapshot.
6. **D8 practice**: `skipped` → `("unsure", "skipped")` (`rows.py:67-68`), settled with its token
   (`activities.py:400-403`): one parent line ends the word's practice, inside ADR-0013's area. Fix: a panel line is
   not an attempt (noop, listen again) unless `/skip`.
7. **Q1 understates (a)**: `anki.answer` (`anki.py:268-290`) writes `review_answers`; on ack `_record_state` writes a
   `card_state` event and re-folds the item.
8. **D1 snapshot stale**: no trailing refresh; text mode `quiz_intro`, `ask(q0)`, listening within ms → the panel
   shows no question; after an activity ends it shows it running through `w.refresh()` and `sequence`. Fix: trailing
   `call_later`, plus hooks at `run_activity` start and finish and at boundary start (through `on_built`).
9. **D4 race and pid check**: the web UI's delete races a new session's replace; "pid not alive" with
   `os.kill(pid, 0)` terminates the process on Windows (`lease.py:29`). Fix: `study-panel-<pid>.json`; reuse
   `lease.pid_alive` or psutil create time (`egress.py:227`).
10. **D1 shutdown hang**: `shutdown()` before `serve_forever` blocks forever (`LeaseHeld`, a recovery error, a
    terminal before the first listen); `close()` can run twice (`inputs.py:372-375`). Fix: shut down only a started
    server; idempotent `close()`; bind after the lease (`loop.py:266`).
11. **D2 Ear lost, panel only**: no alignment, the continuation ends `idle_session`; `listener_lost_no_console` is the
    honest reason. `_console_is_main` (`inputs.py:164`) is one flag for all readers. Fix: keep
    `listener_lost_no_console`; track the main source by name.
12. **D5 not read-only**: the OCR tab opens a full `Store` (`__main__.py:51-56`, `storage.py:575-597`): a shared lock,
    a pragma, schema creation on an empty file; `migrate` fails with `DatabaseInUse` while polled. Fix:
    `file:…?mode=ro` (`storage.py:1016`).

## Low

13. Security fine; `_post_ok` accepts a missing Origin (115) against A4; S6's `SO_EXCLUSIVEADDRUSE` not set.
14. Two lines in one prompt: the first wins, the other is dropped stale with a 202 given; a panel answer can pre-empt
    the child's typed answer. Show dropped lines; which source wins is an owner decision.
15. `learner_questions` always "say that again" (`753-755`); an empty panel line is a line end and completes a
    sentence (`142-147`): refuse empty lines.
16. The Brain's view: `sequence.gather` selects `id, kind, status` (`sequence.py:64`); how `panel_inputs` is counted,
    including `finish_now`, is unspecified; notes see outcome counts (`notes.py:99-105`).
17. `/know` hardcodes `"learner"` (`activities.py:800`); `params.panel` only for panel lines.
18. D6: relative page path, validate n; `/fix` OLD one word; free answers pass the spoken grammar ("stop" stops).
19. `since` restarts per session: add the session id.
20. ADR ownership: D2 amends ADR-0017 §1 and negotiate transcribes §2.1, but no step edits ADR-0017; O3 (storing
    panel lines) touches privacy: make it an owner question.
21. Steps: the `_deliver` change belongs in step 1; `Env` has no `control_sources`; missing tests (`/do` in
    `read_listen` both modes, at announce, twice; panel answers in teach, recall, practice; `close()` before serving;
    trailing refresh; the file race).

## Fine as designed

Publish by reference and guarded `call_soon_threadsafe`; a GET during a synchronous step or cancellation answers from
the published reference; snapshot SELECTs (WAL readers do not wait; in rollback mode a refresh may block up to 250 ms,
raise, be logged and keep the old snapshot); the fixed action table; Host and bearer checks; port 0 and
`allow_reuse_address`; Q3.
