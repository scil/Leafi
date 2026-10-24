# M7 design rev 5 — fresh Claude, fallback for codex (round 5)

Reviewer: a fresh Claude agent on `reviews/prompts/m7-design-rev5.md`, run 2026-10-23 while codex's quota was out (until 2026-10-24 02:00). It read `inputs.py`, `devices/console.py`, `services/asr/__init__.py`, `core/ports.py`, `hub.ListeningGate`, `learner_store.py`, `records.py`, `rows.py`, `activities.py`, `guests.py`, `identify.py`, `anki.py`, `egress.py`, `versions.py`, and ran one in-memory SQLite probe. No file edited.

## Round 4 verdicts

| # | Verdict | Remaining |
|---|---|---|
| 1 | closed | (new D21 defects: findings 1–6) |
| 2 | closed | — |
| 3 | partly | `guests.discard` foreign-key failure (8); an Anki race (10) |
| 4 | partly | `Prepared` has no attempt id (12) |
| 5 | partly | detector load needs a loading state; callers outside a session (11) |
| 6 | partly | page items contradict the rule and break `practise_errors` (4) |
| 7 | closed | `cardsInfo` caveat (14) |
| 8 | partly | "covers the legacy keys too" contradicts the goal (13) |
| 9, 10, 11 | closed | — |
| 12 | partly | D2 still repeats "A mixed output therefore leaves only when…" |

## Findings

1. **High · D21 — the owner is set at `listen` entry, not when the prompt is presented.** In text mode with a Mouth, `say()` requests the main read while the line plays (`inputs.py:166-167`); an answer typed while B's question is still playing has `ended_at` before `set_owner(B)` and is dropped (a regression: today it reaches the next listen); the same for the voice-mode console. If `negotiate`'s offer reuses the `decide` wait's `("boundary", turn)`, a line typed during the wait answers an offer not yet made. Fix: set the owner when the prompt starts (`say(…, owner=o)` / `inputs.present(o)`); every spoken question its own prompt id (each offer, each item); `read_listen` one id per page.
2. **High · D21 — skip no longer reaches the activity.** The pseudocode's reader calls `post_skip()` and sends nothing; today `_deliver` posts it and sends the utterance (`inputs.py:117-118`), and activities check `take_skip()` after `listen` returns. Text `read_listen` waits up to `study_idle_s`; voice `read_listen`'s `u is None` path never checks `take_skip`, so the next real reading utterance is consumed by `take_skip()` and discarded (`activities.py:289-292`). Fix: a `Skip` item that wakes `listen`; test in `read_listen`, both modes.
3. **Medium · D21 — `ended_at` taken when the line or segment is popped, not when the learner finished.** `ConsoleDevice` queues stdin in a thread and builds `typed_utterance` inside `next_utterance` (`console.py:43-48`); VAD runs only during a read and the energy segmenter closes 1.2 s after speech ends. Fix: stamp at the device (console thread at `readline`; voice from the last speech chunk's `AudioChunk.t`); name one clock (`time.monotonic`, shared today by `AudioChunk.t`, `VoiceListener` and asyncio's loop time) and inject it in tests.
4. **Medium · D21 — page items contradict the rule and each other.** `page_open` is set only in `read_listen` (`activities.py:249`), yet `practise_errors` may end `page_turned`; consequence 6 says practice accepts pages, so a `/page` typed during `decide` ends the following `practise_errors` at once. Fix: stamp `Page` with its owner; the boundary consumes a page owned by it (pending page request, then `Reobserve`); `accept_page` per kind.
5. **Medium · D21 — `Switched` carries no epoch:** after an Ear loss during `controls_only` the boundary re-observes, but the waiting `Switched` makes the next activity's first listen raise `StaleInput` (ends `aborted_stale`, "mic lost" spoken again). Fix: `Switched(epoch)`; raise only when the listener's epoch is older.
6. **Medium · D21 — pruning the timeline can remove the current owner** during a long listen (`owner_at` → None, every input stale, a hang). Fix: always keep the newest entry at or before the cutoff. Minor: `Timeout(owner_at(now()))` can end B's listen in scripted tests.
7. **Medium · D22 — the `test_architecture` rule over-flags and misses.** Misses `Store.insert("<table>", …)` (SQL built from a variable, `storage.py:627`): `activities._store_utterance` (`utterances`, names a learner, unfenced) and `rows.start_activity`. Over-flags ≈ 20 existing UPDATEs naming no new learner (`loop.py:112, 212, 313`, `rows.py:123, 130`, `activities.py:92`, `world.py:247`, `anki.py:143–303`, `knowledge.py:58`, `records.py:38`, `guests.py:50`, `identify.adopt`). Fix: flag (a) every INSERT into a `DIRECT`/`PROVENANCE` table, incl. `store.insert("<t>"` and dynamic `INSERT INTO {…}`, outside `learner_store`/`storage`; (b) every UPDATE whose SET names `learner_id`, `*_source_learners` or `*_provenance_class`; move `adopt` and `_store_utterance` onto `learner_store`; list remaining exemptions by function name.
8. **Medium · D17/D22 — `guests.discard` hits a foreign-key failure:** it deletes `knowledge_items WHERE learner_id=guest` (`guests.py:55`) without `item_status_events`; guests can write events; probe confirms "FOREIGN KEY constraint failed", the discard rolls back, guests accumulate. Fix: add `item_status_events` (and `decision_records`) to the guest deletion and D22's order; test.
9. **Medium · D22 — "who catches `LearnerUnavailable`" is wrong when a row of the session's own learner names another learner** (an encounter explanation, an `add_cards` outbox row, B's notes, refused once A is marked; uncaught → the activity errors). Fix: one rule — on refusal, drop the foreign-sourced text and write with B-only provenance, or drop the row; extend `test_forget_race` to an encounter.
10. **Low · D17/D22 — an Anki note can be orphaned** when A is marked during `sync_outbox`'s awaited `addNote` (the ack UPDATE finds A's row deleted; the note never reaches `forget.anki_notes`; exists today). Fix: when the ack matches 0 rows or the learner is forgetting, record the note id on the marked learner row.
11. **Low · D8 — the detector load needs a tri-state** (a `prepare` during the threaded load would load spaCy again on the loop); "refuse when not ready" changes M5 behaviour for every caller (replay script, edge-tts outside a session). Fix: unloaded / loading / ready behind a lock; start the load in a thread at process start (after identification leaves ≈ 8 s of dead air).
12. **Low · D5 — `Prepared` has `token_id` but no attempt id** (`egress.py:120-127`); one `CallAttempt` per backend call, not per `ModelRequest`.
13. **Low · D9 — the fingerprint wording contradicts itself;** `policy_values` reads raw `.env` (`versions.py:82-96`), so the fallback would be implemented twice: one shared `effective_tiers(values)`; `model_fields_set` also counts environment variables.
14. **Low · D17 — `cardsInfo` for a missing card** may return `{}` rather than omit it (reviewer's recollection, unverified); `due_cards`' `c["cardId"]` would raise. Fix: "absent" = missing or empty entry; test.

## Hand-execution outcomes

D21: late voice from A's `judge` dropped, B re-asks (correct); read in flight and B's answer typed after `set_owner` (correct); typed during B's prompt (dropped, 1); typed with no read in flight (wrong prompt, 3); two voice segments (consistent only with audio-time stamps, 3); `/stop` during the filler works from the console; spoken "stop" is not heard during the filler (the gate). D22 at each point of `forget --learner A`: before T1 deleted or cleared by the rescan; after T1 refused and dropped; card events likewise; `forget --session` order holds with foreign keys on.

## Sound

D22's core (same-statement fence, `insert_named` / `update_named`, a refused audit row dropped, the rescan) holds at every interleaving tried; the empty-`IN ()` fence evaluates true (probe); source `0` in `named()` and `_gate`; the deletion order; D21's per-iteration `request` closes round 4 #1's hang; D9's `claude:` prefix and prefix gate; D17's per-card-id lapses and card return; `limits.extract_calls` in M7a and `test_construct` ported.

**Readiness: not ready.** M7a is blocked only by finding 7; findings 1–6 block M7b, 8–10 block M7d.
