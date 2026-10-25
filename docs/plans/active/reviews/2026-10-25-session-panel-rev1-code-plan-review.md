# Session panel design rev 1: code-plan-review

Reviewer: a fresh Claude agent (Opus 5.5) running `code-plan-review` on
`docs/plans/active/2026-10-25-study-session-panel-design.md` rev 1, 2026-10-25. Independent of the other two reviewers
of round 1 (prompt `reviews/prompts/session-panel-rev1.md`). Findings as reported; verification is in the round's
comparison file.

## Findings

1. **High · I1.1 / H3.2 / K2.1 · D8.** Two confidence predicates: `teach_items` and `recall_items` score through
   `leafi/study/brain/scoring.py::confident` (28; used at 45, 52, 71), true for any typed utterance, so `_score_item`
   (`activities.py:816-828`) writes a `retrieval_events` row (`typed`) and an encounter from a panel answer. Fix: one
   predicate owns "may count as evidence", the panel rule there; a test per kind (quiz, recall, teach, review).
2. **High · F1.1 · D8 vs the plan's "Answer for the learner (quiz, recall, questions)".** `learner_questions` answers
   an unconfident line with `questions_again; continue` (`activities.py:753`): a panel question loops. Practice needs
   its own branch for `skipped`. Fix: list every call site of either predicate (`activities.py` 516, 659, 753;
   `scoring.py` 45, 52, 71) with its panel branch; `learner_questions` accepts or refuses (owner decision B).
3. **Medium · A3.3 / I3.1 · D1 stamp at request time.** The owner acts on a view 0.2–1.2 s old; the prompt current at
   request time may be the next one, so an answer or `/skip` for q3 lands on q4; a double click sends two skips. Fix:
   the snapshot carries its publish time and owner; each POST echoes the publish time it was based on and the device
   stamps `ended_at` with it, so D21 parks or drops a line for a prompt that moved on; buttons disabled until a newer
   version arrives.
4. **High · C2.2 · D1 "a panel fault never reaches the session".** Bind and runtime-file write run inside
   `next_utterance` on the panel's reader; `OSError` (reserved or used port) or `PermissionError` (`os.replace` while
   the web UI holds the file open) goes through `Latch.spawn.guarded` → `terminate("internal_error")`
   (`latch.py:131-134`); a non-main `ListenerLost` is re-raised (`inputs.py:153-158`). Fix: the device catches its own
   faults, alerts once, then `next_utterance` waits forever; `close()` suppresses and retries the remove; tests for a
   bind failure and a replace failure.
5. **Medium · B3.6 · D4 "the web UI then deletes it".** One shared path, two writers: a new session's `os.replace`
   between the web UI's stale read and its delete loses the live file; a transient 403 or timeout also deletes it.
   Fix: the reader never deletes; per-process files `study-panel-<pid>.json` (Jupyter's pattern), removed by the
   writer, stale ones swept by the next study process at start.
6. **Medium · I2.2 · D7 `activity_over()` plus a posted skip.** In `read_listen` the skip path
   (`activities.py:325-328`) calls `skip_read` and continues without checking `activity_over`; panel lines are not
   aligned and text mode has no pauses, so `/do` skips one sentence per press and never ends the activity; `_pause`
   returns `skipped`, not `completed`. Fix: while an activity runs, a posted want makes `listen()` raise a `Jump` (as
   `StaleInput`), caught by `run_activity`, finished `completed` with `outcome.ended_by = "panel"`.
7. **Medium · F2.1 / C2.1 · D7 at a boundary.** The posted skip reaches `take_skip()` → `_exclude(s, a.kind)`
   (`negotiate.py:181-183`): the offered kind is excluded as if refused; if the wanted kind is not constructible both
   are gone. A `/do` during a plain `say` gets owner None and is taken by the next activity's first listen. Fix: at a
   boundary `/do` is a named choice (`parse_choice` → `named:<kind>`, `negotiate.py:186-195`), no skip; `Jump` only
   while `activity_started_at` is set.
8. **Medium · C4 / C1.3 · D8 and D7 vs C2(a) "every row carries the source".** A panel `/fix` writes
   `corrections.source='text'` (`activities.py:192`) though `'parent'` is allowed and handled (`corrections.py:106-110`);
   the activity cut short is plain `completed`; `params.panel=true` is set for a console `/do` too. Fix: tag from
   `u.source` (`/fix` → `parent`, `params.by = u.source`, `ended_by`); ask the owner whether counts are enough (A).
9. **Medium · D3.1 / J1.3 · D1 throttle.** No trailing edge: `ask` then `show("listening")` within 0.2 s drops the
   second publish; nothing calls `show()` during a listen, so the panel shows a stale prompt; clocks freeze, or if they
   change each publish `?since=` never returns 204. Fix: a dirty flag and a guarded trailing `call_later(0.2, …)`;
   clocks sent as instants and counted down on the page; the version bumps only on non-clock changes.
10. **Medium · C2.1 · D2 / devices.yml.** In text mode `app.py:79-81` and `hub.listener()` take the first listener as
    main: a `panel` entry before `console` makes the panel main. `runner._mock_config()` (99-104) holds only the
    console, so `--mock --panel` builds no panel. Fix: the panel is never the study listener unless `study.listener`
    names it; add it to the mock config under `--panel`; test both.
11. **Medium · I1.3 · D6 page text path.** A relative `cache/panel/page-<n>.txt` resolves against each process's own
    working directory (`activities.py:63-65`, `loop.py:361-363`); a second paste overwrites the first before it is
    read. Fix: an absolute path under `settings.cache_dir`, a unique name per paste, `n` validated.
12. **Medium · F1.1 · D6 answers.** `controls.parse` applies the spoken grammar to any line of ≤ 6 words not starting
    with `/` (`controls.py:29-48, 112-113`): an answer "stop" ends the session; "again"/"good" press an ease; "no" and
    "next page" act. Fix: panel lines are parsed with `parse_typed` only (or a `/say <text>` command); test that the
    answer "stop" does not stop; `/fix` OLD is one word (`controls.py:83-85`), validate in the web UI.
13. **Low · F1.1 · D2 details.** `_speak` (`inputs.py:314-315`) must request every typed source, main included; pick
    "the console" by adapter, not name; the panel needs `pause`/`resume` if it becomes main; a voice session without a
    console that loses its Ear now continues on the panel instead of `listener_lost_no_console` (decision C).
14. **Low · D4.2 / F2.1 · D5 tab states.** Unspecified: live, no session (database), proxy failure, database error
    (`SchemaError` / `DatabaseInUse`); buttons only when live; a proxy timeout must not flip to "last session"; put
    `session_id` into `since`.
15. **Low · A3.8 · D1 202 at once.** A line dropped as stale (`inputs.py:231`) or a refused `/do` is invisible to the
    owner; the snapshot should list the last panel inputs and what happened to each.
16. **Low · H3.2 / F1.1 · D3.** The reading counts restate `World.end_page_read` (`world.py:266`): extract one
    function; `learner.kind` also allows `anonymous` (`storage.py:170`).
17. **Low · I2.3 · D8 vs D9.** `last_activity` (`observe.py:93-98`) is an egress payload: D9 should say the count goes
    there; `security.md` and the prompt version name the field.
18. **Low · K2.1 · D8 practice / Q2.** A panel answer or a `/do` skip settles a candidate `unsure:skipped`, writes a
    `practices` row, marks a quiz item `unavailable`; Q2 should name these effects (or leave the candidate untouched).
19. **Low · security details.** `secrets.compare_digest` for the token; refuse by `Content-Length` (413) before reading
    the body; refuse CR/LF in an answer.
20. **Low · I1 second pass.** The plan still states superseded decisions (port 8771, "token from the lease file's
    directory", an anyio memory stream, "every row … carries that source").
21. **Low · H5.1 · step 7.** Names the console button but not running `check-console.js`.

## Fine as designed

Threading (publish by reference, guarded `call_soon_threadsafe`, `shutdown()` via `to_thread`, no `SO_REUSEADDR` on
Windows, port 0); A5 confirmed (a browser cannot add `Authorization` cross-origin without a preflight this endpoint
never answers); the web UI hop (Origin stays the real guard: `Sec-Fetch-Site` treats other 127.0.0.1 ports as
same-site); polling; the architecture seam (`on_built`); no migration needed (every stored value passes its CHECK);
the one-slot want; D21 reuse; provenance lines present.

## Owner decisions named

A counts plus tags without a migration, or migration 9; B a panel-typed question in `learner_questions` sent to the
Brain (through egress) or refused; C Ear lost without a console: continue on the panel or end as today; Q1–Q3; D the
status of an activity cut by `/do` (`completed` + `ended_by`, recommended, or a new ADR-0017 status).
