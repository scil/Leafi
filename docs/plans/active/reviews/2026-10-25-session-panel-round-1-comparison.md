# Session panel design rev 1: round 1 compared

Prompt: `reviews/prompts/session-panel-rev1.md`. Reviewers, run in parallel, none reading another:

- **CPR**: `code-plan-review` by a fresh Claude agent (`2026-10-25-session-panel-rev1-code-plan-review.md`), 21 findings
  (3 High, 9 Medium, 9 Low);
- **A**: a fresh Claude on the prompt (`2026-10-25-session-panel-rev1-claude.md`), 3 High, 7 Medium, 8 Low;
- **B**: a second fresh Claude standing in for codex (`gpt-6-astra` refused with a usage limit until 15:04;
  `2026-10-25-session-panel-rev1-claude-b.md`), 3 High, 9 Medium, 9 Low.

All three ran on Opus 5.5; codex's different model is missing from this round. Codex should run the rev 2 increment.

Verified by the author against the code: two predicates (`scoring.py:28-29` true for any typed line);
`Latch.post_skip` only appends to a deque (`latch.py:107-108`) and a playback skip only cuts the line
(`inputs.py:173-176`); the unconfident-answer rule is ADR-0017 §3.4 ("typed answers always count", 0017:223), not
ADR-0013; `lease.pid_alive` exists and warns that `os.kill(pid, 0)` terminates on Windows (`lease.py:25-29`); the web
UI's `_post_ok` accepts a missing Origin (`__main__.py:113-116`); `storage.py:1016` has the `mode=ro` URI pattern.

## Themes

| T | Theme | CPR | A | B | Severity | Answer in rev 2 |
|---|---|---|---|---|---|---|
| T1 | Panel answers still scored in teach/recall: a second predicate `scoring.confident`; `item_used` sends the owner's text to `judge` | 1 | 1 | 1 | High | one predicate `counts_as_answer(u)` in `scoring`, used by both; panel → false; tests per scored kind |
| T2 | `/do` as "a posted skip" wakes nothing, and during playback posts nothing | 7 | 2 | 3 | High | structural: `/do` is its own item kind; while an activity runs `listen()` raises `Jump` (as `StaleInput`) |
| T3 | `/do` does not end `read_listen`; text mode ends `idle_session`; each press skips a sentence | 6 | 3 | 2 | High | answered by T2: `run_activity` catches `Jump`, ends `completed`, `outcome.ended_by = "do"`; nothing skipped |
| T4 | `/do` at a boundary excludes the offered kind; announce band returns `Run(a)`; leftover skips | 7 | 17 | 4 | Medium | at a boundary `/do` is a named choice (`parse_choice` → `named:<kind>`); `take_want` before every `Run`, before `sequence`; no skip posted |
| T5 | D8 rewrites ADR rules: practice `skipped` settles the candidate for good; ADR-0017 §3.4 says typed answers count | 18 | 4 | 6 | Medium | ADR-0017 §3.4 amended (a panel line never counts); in practice a panel free line is not an attempt (noop, listen again); ADR-0013 untouched |
| T6 | Snapshot goes stale: no trailing refresh, no refresh at activity end or boundary | 9 | 6 | 8 | Medium | dirty flag + trailing `call_later`; hooks at `run_activity` start/end and boundary start through `on_built` |
| T7 | Snapshot SELECTs on the loop inside `show()` can block a line | – | 7 | (fine) | Medium | split: memory-only snapshot (the loop keeps the session's activity list); the history comes from the web UI's read-only DB read |
| T8 | Runtime file: one shared name races; web UI deletes live files; pid check unsafe on Windows | 5 | 8 | 9 | Medium | `data/run/study-panel-<pid>.json`; writer removes its own; reader never deletes; `lease.pid_alive` + psutil create time; stale = 401/403 or dead pid |
| T9 | Device faults kill the session; `shutdown()` before serving hangs; `close()` twice | 4 | 8 | 10 | High | device catches its own faults (one alert, then a dead panel); bind after the lease; shutdown only a started server; idempotent `close()` |
| T10 | Composition: the panel can become the main listener; mock config lacks it; console EOF is `/stop` | 10 | 10 | – | Medium | the panel is never the study listener; `--panel` adds it to the mock config; console EOF under `--panel` without a terminal is ignored |
| T11 | Ear lost with the panel only: reading cannot move; dishonest end reason; one `_console_is_main` flag | 13 | 5, 15 | 11 | Medium | the panel never becomes main: `listener_lost_no_console` as today; main source tracked by name |
| T12 | Free answers pass the spoken grammar ("stop" stops, "good" eases) | 12 | 13 | 18 | Medium | panel lines parsed with `parse_typed` only; free text is data |
| T13 | An action stamped at request time lands on the next prompt | 3 | – | – | Medium | the POST echoes the snapshot's publish stamp; the device stamps `ended_at` with it; D21 parks or drops |
| T14 | `learner_questions` loops on panel lines; egress of the owner's text | 2 | 11 | 15 | Medium | owner question |
| T15 | Hint offer: a panel `/yes` supplies the word (a `supplied` candidate) | – | 12 | – | Low | allowed: the owner saw the child stuck; recorded in `panel_inputs` |
| T16 | Q1 understates: an ease writes `review_answers`, `card_state`, re-folds the item | – | 16 | 7 | Low | Q1 reworded |
| T17 | DB fallback is a full `Store` (lock, pragma); polling blocks `migrate` | – | 14 | 12 | Medium | `file:…?mode=ro` connection per request, closed at once |
| T18 | `_post_ok` accepts a missing Origin; `Sec-Fetch-Site` from other loopback ports is `same-site` | 19 | 14 | 13 | Low | Reading tab POSTs need a matching Origin; refuse `Sec-Fetch-Site` other than `same-origin`/`none`; `compare_digest`, `Content-Length` 413, no CR/LF, no empty lines |
| T19 | `since` restarts per session | 14 | 9 | 19 | Low | version `"<session_id>:<n>"`, compared by equality |
| T20 | Page path relative to each cwd; `/fix` OLD one word | 11 | 13 | 18 | Medium | absolute `cache_dir` path, unique per paste, `n` an integer; `/fix` OLD validated as one word |
| T21 | Rows not tagged where they could be: `/fix` → `parent`, `/know` → `owner`, `params.panel` for console `/do` | 8 | 16 | 17 | Medium | tag from `u.source`: `corrections.source='parent'`, `item_status_events.source='owner'`, `params.by` |
| T22 | The Brain's view is `sequence.gather`, not `observe.py`; D9 must name the count as egress | 17 | 16 | 16 | Low | change in `sequence.gather`; D9 names the field |
| T23 | ADR amendments unmarked (ADR-0017 §1, §2.1, `activity_over`, latch slot) | 20 (I1) | 18 | 20 | Low | a step edits ADR-0017; marked [ADR-0017 amended] |
| T24 | Small: tab states, dropped inputs invisible, `pause`/`resume`, `Settings` field, `check-console.js`, plan stale text, `SO_EXCLUSIVEADDRUSE`, a reading-count helper | 14–16, 20, 21 | 17 | 13, 20, 21 | Low | each folded into rev 2 |

## Overlap

All three found T1, T3, T6, T8, T12, T19, T20, T21 and T23; two found T2, T4, T5, T9, T10, T11, T17, T18, T22. Only
CPR found T13 (the stale view's stamp) and the device-fault path of T9; only A found T7 (blocking SELECTs, which B
judged acceptable) and T15. No finding was judged false. The class behind T2–T4 is one decision: rev 1 expressed a
want as a skip. Rev 2 restates it as its own input kind with one exception, per `codex-review`'s "the structural move
is a restatement".

## Owner decisions raised

B (a panel question in `learner_questions`: to the Brain or refused), A + O3 (how panel inputs are recorded and
whether they are stored), Q1 (Anki eases), Q3 (the runtime file's ACL). Decided by the author with the reviewers'
agreement, reversible by the owner: C (the panel never becomes main; Ear loss ends as today), D (a `/do` ends the
activity `completed` with `ended_by`), Q2 (moot: `Jump` skips nothing), T14's "which source wins" (the first line
delivered, as today, with dropped lines shown on the panel).
