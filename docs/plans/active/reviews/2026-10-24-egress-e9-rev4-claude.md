# Content-only egress E9 rev 4 — fresh Claude (structural round, fallback for codex)

Reviewer: fresh Claude session (in codex's place), structural round on E9 rev 4 of `2026-10-24-content-only-egress-design.md` only. Read: `leafi/services/tts/{__init__,kokoro,edge}.py`, `leafi/core/{hub,learner_store,storage,audio}.py`, `leafi/app.py`, `leafi/runner.py`, `leafi/cli.py` (`devices`, `doctor`), `leafi/privacy/runtime.py`, `leafi/devices/go2rtc_camera.py`, `config/devices.yml`, `leafi/study/harness/{identify,guests,rows,loop}.py`, `leafi/study/{records,anki,knowledge}.py`, `tests/test_architecture.py`, `agent/tts.py`. I grepped every `UPDATE … SET` in `leafi/`, every caller of `synth` / `tts.create`, and every reader of `cache/tts`. I hand-executed the paths the prompt names. No probes were needed: each failure below follows from the code as written.

## Findings

**1. High — the camera Mouth keeps a copy of every clip, and E9 keeps that copy on purpose.** E9 says (Layout) that `cache/tts/camera/` is "never touched by Leafi's study code", and its test says `forget` "leaves … `camera/`". Both are wrong. `config/devices.yml` makes `desk_cam` (adapter `go2rtc_camera`) the primary Mouth, with `local_dir: cache/tts/camera`. `Go2rtcCamera.prepare` writes a padded copy `<key>.cam.wav` of every clip the study Hub plays, and never deletes it. Nothing ages it out either: no 90-day sweeper exists anywhere in the repo.
Inputs: voice session, learner L (display name "Ada"), policy `all`. `identify` speaks "Shall I remember you as Ada?" and the Kokoro clip lands in `tts/learners/<guest>/`, while the camera copy lands in `tts/camera/<key>.cam.wav`. L is adopted, and later lines naming L or quoting L's words get copies there too. Then `forget --learner L`, and the next session start's sweep. Outcome: `learners/L/` and the guest folder are gone, but every `.cam.wav` of L's lines stays indefinitely. Only the habit track's root files are truly out of scope; `camera/` is Leafi-only (the habit track pushes from the `cache/tts` root).
Fix: make the camera copy transient. `play()` deletes its `.cam.*` file once playback ends (after `stop()` or the drain). On Windows, a delete refused because go2rtc's ffmpeg holds the file is logged and retried. At Mouth construction, any stale `*.cam.*` left in `local_dir` is removed. Then E9's test asserts that `camera/` holds no clip of L, not that it is kept, and E9's sentence about `camera/` is corrected.

**2. High — recovery's guard "on its first write, abandoned when it touches no row" skips healthy sessions, and one of the two recovery loops is not covered.** The first write in `rows.recover` is `UPDATE activities SET status=? … WHERE session_id=? AND status='running'`. In the failed-finalisation state E9 names, no activity is normally still running: `run_activity` already called `finish_activity`. So that UPDATE touches 0 rows even when the owner M has `forgetting = 0`.
Inputs: M's session with `post_done_at` set, `ended_at` NULL, no running activity. Outcome: the guarded write touches nothing, the transaction is abandoned, and the session is never recovered. Every later startup repeats this. E9's own test "recovered normally" fails.
Separately, `records.close_stale_sessions` (called from `recover`) selects `ended_at IS NULL` again in its own per-session transactions. It writes `miscues` (`settle_open`), `page_reads.reading_state`, `reading_sessions.ended_at/summary` and `recompute_difficulties`, and E9's guard does not cover it.
Fix: `Store.transaction()` is already `BEGIN IMMEDIATE`, so the write lock is held from the first statement. Make the guard a standalone first statement, `SELECT 1 FROM reading_sessions rs JOIN learners l ON l.id = rs.learner_id WHERE rs.id = ? AND l.forgetting = 0`, and skip the session when it returns no row. `forget`'s marking `UPDATE learners SET forgetting=1` cannot commit in between. Put this guard in both loops, or merge them into one per-session transaction that also catches `LearnerUnavailable`.
Hand-execution between two `forget` batches: N is marked, the session row S still exists, M's runner starts and calls `recover`. With this fix the guard returns nothing for S, so S gets no write and no abort, and `forget`'s next batch deletes S. The final bulk `UPDATE reading_sessions SET post_done_at … WHERE post_done_at IS NULL` only touches a maintenance column and is harmless.

**3. Medium — a kept guest's folder holds clips naming N, and nothing deletes them on `forget`.** Before adoption, `identify` speaks enrolled learners' names into the guest's folder: the console list "1. Ada, 2. Ben", the confirm question "Ada?" and "Shall I remember you as …?". Inputs: a visitor says "Ada" and then answers no to "Ada?". After two attempts the session stays guest G, `unconfirmed`, and is kept `guest_keep_days`. Then `forget --learner` Ada. Outcome: G is a valid row and not forgetting, so neither the forget step nor the sweep touches `learners/G/`. The "Ada?" clip survives until G expires. If G is adopted instead, the folder survives only until the next session start, which E9's report sentence already covers.
Fix: have `forget` also delete the folder of every guest with no live session (guest clips are cheap to remake). Or synthesise `identify`'s name-bearing prompts uncached, to a temporary file deleted after playback.

**4. Medium — `anki.sync_outbox` keeps pushing a forgetting learner's cards, and its raw UPDATEs fall outside the allow-list as written.** `sync_outbox` runs in M's `deliver` step (M's `post_done_at` is still NULL, so no `LearnerBusy` blocks it). Its query takes every learner's outbox rows (`o.state IN ('pending','sent')`) without checking `forgetting`.
Inputs: N is marked forgetting and is between batches. M's session ends, and `sync_outbox` reads N's row, sets it to `'sent'` with a raw UPDATE, then runs `addNote`. Outcome: N's card goes into Anki after `forget` has already gathered `anki_note_ids`, so the report does not list it.
Separately, the rule "status, timestamps, counters and ids only; any JSON text column goes through `update_named`" catches `attempted_fields` / `last_acked_fields` (JSON of hashes), `card_ids` (JSON of ids) and `last_error` (text) at `anki.py:143,167,193,198,206`. Under that rule they would raise `LearnerUnavailable` inside the sync loop, and `deliver` swallows the error as "anki sync failed", which aborts the sync for every later row.
Fix: the sync query joins `learners` with `forgetting = 0`, and the `'sent'` UPDATE carries the owner `EXISTS` predicate (0 rows means skip the row, no raise). Add those five columns to `MAINTENANCE_COLUMNS`, each with its reason (hashes, ids, an AnkiConnect error string).

**5. Low — allow-list inventory and scanner details.** With `DIRECT_OWNED | SESSION_OWNED` as defined today, the raw UPDATEs outside learner_store are:
- `reading_sessions`: `ended_at` and `summary` at `loop.py:220` and `records.py:38`; `summary` and `post_done_at` at `loop.py:322`; `book_id` at `loop.py:113`; `post_done_at` at `rows.py:130` (bulk) and `records.py:270`.
- `activities`: `cycle_id` at `activities.py:93` and `world.py:253`; `status` and `ended_at` at `rows.py:123` (bulk by session).
- `review_answers`: `state`, `sent_at`, `acked_at` in `anki.py`.
- `knowledge_items`: `status` and `updated_at` at `anki.py:279`; `updated_at` at `knowledge.py:63`.
- `anki_outbox`: see finding 4.

`summary` is a JSON column, so the stated rule would force it through `update_named`. List it instead: it holds counts and enum strings by construction (`records.summary`). The bulk sites (`rows.py:123,130`) cannot use a per-row `update_named` at all. No other site needs `update_named`. Today every owned-table SET is a single literal that the scanner can parse: implicit concatenation becomes one `Constant`, and the only f-string UPDATEs are on non-owned tables or in `learner_store`.

Specify the scanner:
- Extract targets as `(\w+)\s*=` at parenthesis depth 0, so `COALESCE(?, summary)` is not read as a target.
- Treat any `{}` in the SET of an owned table as a refusal.
- Walk module-level and class-level strings as well as functions; today `ast.walk(fn)` misses a module-level SQL constant.
- Keep `reading_sessions.learner_id` out of the allow-list. Listing it would let any module re-key a session raw, which is weaker than today's rule; `adopt_session` sits in `learner_store`, and `guests.discard` keeps its function exemption.

**6. Low — `set_owner` is a second copy of a fact the code already has.** `runtime.attribution` is set to the guest at session start and moved in place by `runtime.attribute` inside `adopt()`, for every context that shares it. The only synthesis caller in `leafi/` is the session (`hub.say` via `run_session`). `doctor` and `devices` never synthesise, so `shared/` has no writer today. `set_owner` would need a new `Synthesizer` port method, a `None` guard in text mode, and updated test fakes. Recommendation: have `TtsService.synth` read the folder from `runtime.attribution.get()` before awaiting the backend, with `None` meaning `shared/`. That leaves no ordering gap and no new call sites.

A related cost to note: every session starts as a new guest, so the greeting and system phrases are re-synthesised in each session before adoption.

**Checked and sound:**
- Ids cannot be reused (`learners.id` is `AUTOINCREMENT`), so a late file in `learners/<N>/` cannot be adopted by a new row.
- A late file from a cancelled Kokoro worker recreates the folder (`write_wav` runs `mkdir`), and the next start's sweep removes it.
- The habit track writes only root `*.mp3` files and deletes nothing under subfolders.
- No test or reader depends on the flat cache layout.
- The camera push path does not change with the new layout.

## Sound

Part 1's per-owner layout is sound once the camera copy (1) and kept-guest folders (3) are handled. Part 2's inversion is sound once the allow-list is filled as in 4–5. Part 3's per-session skip is sound once the guard is a standalone first statement under `BEGIN IMMEDIATE`, in both recovery loops (2).
