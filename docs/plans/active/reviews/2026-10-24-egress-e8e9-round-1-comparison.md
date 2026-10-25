# Content-only egress E8–E9 — round 1 comparison

Object: E8 (migration 7) and E9 (`forget` and the fence by owning learner) of `docs/plans/active/2026-10-24-content-only-egress-design.md` rev 1, with ADR-0021. Prompt: `reviews/prompts/content-only-egress.md`. Reviewers, independent and in parallel, 2026-10-24:

- **A** — codex (`gpt-6-astra`, high, read-only; `2026-10-24-egress-e8e9-codex.md`), 8 findings (3 High);
- **B** — a fresh Claude (`…-claude.md`), 9 findings (2 High), with probes on a scratch v5 file;
- **C** — `code-plan-review` (`…-code-plan-review.md`), 12 findings (3 High).

The comparing author checked against the code: `migrate_file` runs step 6 with the live `SCHEMA` (`storage.py:822`); `forget_learner` moves only `display_name` into `household_terms` (`records.py:278`); `leafi forget`'s preview promises "every text derived from them" (`cli.py:117`). No finding is a false positive. All three confirm that DROP COLUMN is legal on all 20 columns (A, C: 20 in 7 tables; B: 17 probed together) and that `forget --session` / `--book` are unaffected.

## Themes

| # | Theme | Sev | A | B | C | Rev 2 direction |
|---|---|---|---|---|---|---|
| U1 | Step 6 targets the live `SCHEMA`: once it loses the columns, a v4/v5 file is rebuilt to the v7 shape and stamped 6, and step 7's DROP COLUMN fails ("no such column"), stranding it (B reproduced it) | High | 1 | 1 | 1 | freeze `SCHEMA_V6`; step 6 targets it; a `version == 6` branch runs 7; tests 4→7, 5→7, 6→7 and migrated = fresh |
| U2 | E8 describes a runner the code lacks: `Store` raises `NeedsMigration` (the owner runs `leafi migrate`, which takes its own backup); no `migrate()` `BEGIN IMMEDIATE` exists, the lock is `migrate_file`'s `.users` lock; `_step` already rebuilds to a target schema, so DROP COLUMN is a second mechanism | Med | 1 | L1 | 6 | use `_step(conn, 7, SCHEMA, {})` (one proven mechanism; DROP COLUMN's legality stays a recorded fact); rollout = `leafi migrate`; no extra manual backup |
| U3 | `VACUUM` has no owner; the raw migration connection lacks `secure_delete`; under WAL the old pages stay until a `TRUNCATE` checkpoint; a crash after the commit skips cleanup forever; the planned canary cannot fail (class names recur elsewhere) | Med | 4 | M1 | 5 | `migrate_file` sets `secure_delete`, runs `VACUUM` then `wal_checkpoint(TRUNCATE)` after step 7, still under the lock; a retryable cleanup for a file already at 7; canary `'[987654321]'` checked in `leafi.db` and `-wal` |
| U4 | E10's commits cannot each be green: commit 3 removes provenance while 20 `NOT NULL` columns still need values until commit 4; `learner_store` imports `PARENT_SOURCE`; ~21 test files read the columns or `SCHEMA_VERSION` | High | 2 | M4 | 7 | commit 3 removes only in-memory provenance (egress, TTS, Brain); every storage writer, seed, fixture, the fence and migration 7 move together into commit 4, with the test files named |
| U5 | The fence silently disappears: `insert_named` takes ids from `stated_sources`, empty without the columns, and `_fence([])` is always true; `PROVENANCE_TABLES` and `test_architecture`'s fenced set shrink; `brain_calls` is not in `_OWNER_SQL`; `update_named` reads its owner in a separate statement | High | 5 | M3 | 2, 11 | explicit `DIRECT_OWNED` and `SESSION_OWNED` sets; the owner check inside the statement (`EXISTS(… reading_sessions JOIN learners … forgetting = 0)`), a missing session refusing; `test_architecture` on the explicit sets; tests for late audits, cards, notes, and M's writes allowed |
| U6 | The stated cost is wrong: copies in M's rows do not "stay local" — M's Anki cards quoting N stay in Anki and AnkiWeb and are no longer listed for removal; M's utterances, Brain calls, assessments and explanations quoting N keep going to the cloud under the new rule; the CLI still promises "every text derived from them" and its derived count is always 0. Also an existing exception: a note of M cited only by N's session activities **is** deleted with that session | High | 6 | H2 | 3 | correct E9 and ADR-0021; `leafi forget`'s preview, help and report state what survives; keep and document the citation exception; **owner**: M's Anki notes quoting N (below) |
| U7 | Only the display name moves into `household_terms`; the alias (protected by `pseudonym.py` as part of the learner) is lost with the row, so an alias in M's surviving text is on no list | High | 3 | — | 4 | move the alias and every listed name in the same statement; test: forget N, then M's text with N's alias is still replaced |
| U8 | A refused audit row escapes: `_insert`'s `_withheld` fallback is refused too, `busy.retry` re-raises, `write_audit` raises into the call and `flush_audit` at `finalize`, skipping post-session steps and `post_done_at` | Med | — | M2 | 8 | `_insert` logs and drops the row (popped from `pending_audit`); test: `finalize` completes with a forgetting owner |
| U9 | Stores outside the database: wiping `cache/tts/` races active synthesis of another learner and would delete `cache/tts/camera/` (the camera push folder); `forget` has no cache path; `data/evals/decisions/` and DEBUG-log deletion are not implemented today | Med | 7 | L3 | 10 | delete only the clip entries (not `camera/`), with the configured cache path, coordinated with the synthesizer's publish (skip a clip being written; retry); list each outside store with "exists / not yet"; test the cache deletion |
| U10 | Backups and restore: a v6 backup refuses to open until `leafi migrate` reruns; a pre-forget backup brings N back (ADR-0019 §8) | Low | 8 | L2 | 12 | state both in the rollout and in `leafi forget`'s backup notice |
| U11 | No by-owner sweep before the final `DELETE FROM learners`: a plain insert between batches (`egress_log`) makes it fail on the FK (safe, a rerun resumes, but noisy) | Low | — | — | 9 | the last transaction repeats the by-owner deletes first |
| U12 | The renumbering (M7's migration 7 → 8, M7f's 8 → 9) is not carried into the M7 design (4×), the practice design and the plan | Low | — | — | 12 | renumber in those documents in rev 2's commit |

## Overlap

- Found by all three: U1, U2, U3, U4, U5, U6, U9, U10.
- Found by two: U7 (A, C), U8 (B, C).
- Found by one: U11, U12 (C).

## The structural reading

U1–U4 come from E8 being written against an imagined migration runner rather than `migrate_file` / `_step`; the fix is to use the runner as it is (a frozen `SCHEMA_V6`, `_step` to the new `SCHEMA`, cleanup after the commit under the same lock). U5–U8 come from one move: removing the source columns removes the **subject** of the fence and of the purge, and E9 replaced it in a sentence, not in a mechanism. Rev 2 should state the owner sets and the in-statement checks as code-level rules and correct the cost statement.

## For the owner

1. **U6: M's Anki cards that quote N.** With the columns gone nothing can find them. Options: (a) accept it and say so in `forget`'s report: "cards in other learners' decks may still mention them; check Anki" (recommended: no source data comes back); (b) keep one narrow column on `anki_outbox` only (the learner ids a card quotes), so those cards are still listed for removal — a source record for cards alone.
