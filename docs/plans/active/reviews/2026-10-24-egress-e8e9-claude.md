# Content-only egress E8–E9 — fresh Claude (round 1)

Reviewer: fresh Claude session (Opus). Read the prompt, design rev 1 (E8–E9, E6/E7/E10/E11 where they touch them), ADR-0021, ADR-0018 §1/§3, ADR-0019 §3–§8, and the code: `storage.py` (`SCHEMA_V5`, `SCHEMA`, `_V5_COPY`, `migrate_file`, `_step`, `_open_schema`), `learner_store.py`, `records.py`, `brain/call.py`, `harness/{rows,loop,guests,busy}.py`, `cards.py`, `knowledge.py`, `tts/__init__.py`, `cli.py` (`_forget_learner`), `test_architecture.py`, and the provenance reads in `tests/`. Probes (scratch files, `.venv` Python, SQLite 3.54.1, never `data/`): (a) a WAL v6 file from the real `SCHEMA` with rows in all seven tables, all 17 `DROP COLUMN`s in one `BEGIN IMMEDIATE` with `foreign_keys=OFF`, `legacy_alter_table` ON and OFF; (b) `schema_of` of the result against `SCHEMA` with the 17 definitions removed; (c) `VACUUM` in a transaction, with an idle second connection, with an open read transaction; canary bytes in the main file and `-wal` before and after `wal_checkpoint(TRUNCATE)`; (d) a v5 file migrated by the current `migrate_file` with `SCHEMA` edited as E8 says, then step 7's `DROP COLUMN`.

## Findings

**1. High — E8 "`SCHEMA` edited to match": step 6 targets `SCHEMA`, so every file at 5 or below skips past the columns and step 7 can never run.**
`migrate_file` runs `_step(conn, 6, SCHEMA, …)`, and `_step` rebuilds every table whose DDL differs from its target. Probe (d): a v5 file with one utterance, `SCHEMA` edited → step 6 rebuilds `activities, brain_calls, utterances, encounters, learner_notes, book_notes, anki_outbox` *without* the columns and sets `user_version = 6`; step 7's `ALTER TABLE utterances DROP COLUMN provenance_class` → `no such column: "provenance_class"`, rollback, file stuck at 6 forever (every rerun fails the same way, and `Store` refuses version 6). The same gap breaks E8's own test: "a version-6 file" cannot be built once `SCHEMA` has changed, as there is no frozen v6 DDL; `test_migration_6` asserts `SCHEMA_VERSION == 6` and compares a migrated v5 file against fresh `SCHEMA`.
Fix: freeze `SCHEMA_V6` (today's `SCHEMA` plus the trigger block and `SEEDS`); step 6 targets `SCHEMA_V6`; `SCHEMA = _edit(SCHEMA_V6, …)` once per column definition; add `if version == 6:` step 7; keep `_V5_COPY`'s provenance expressions (`SCHEMA_V5` still has the NOT NULL columns, so step 5 fails without them). Write the rule into the module comment: each migration targets a frozen constant, and only the newest step targets `SCHEMA`. M7's migration 8 then freezes `SCHEMA_V7` the same way.

**2. High — E9 "accepted cost": the loss is wider than the design says, and the text a parent reads says the opposite.**
Walk-through of `forget --learner N`, where M's rows name N:
- Gone, as before: N's direct rows, everything reached through N's sessions (including M-owned encounters and notes whose `session_id` is N's, and `brain_calls` and `egress_log` of N's sessions), the correction links, `data/learners/N/`.
- Survive now, though `_purge_derived` used to remove them: M's notes and book notes naming N; M's encounter explanations; M's activity outcomes and assessments; `brain_calls` payloads and responses in M's sessions; **M's `anki_outbox` cards citing N**.
- What follows from that, beyond what the design states:
  - (a) a *pending* card of M citing N is pushed to Anki (and from there to AnkiWeb) by the next `sync_outbox`, *after* the forget; before, the card was deleted.
  - (b) cards citing N that are already in Anki are no longer listed for the household to remove (`_remember_notes` ran inside `_purge_derived`).
  - (c) "the stored copy itself stays local" is not true under E1: M's notes and context feed M's later cloud requests, so N's words keep leaving, redacted only by the lists (which gain N's `display_name`, not nicknames) and the detector (which misses lower-case names, O6).
  - (d) `cli._forget_learner` still tells the parent "…and every text derived from them" and prints "`{derived_removed}` derived text(s)", which is now always 0.

Fix: reword the CLI dry-run and result lines, ADR-0021's Consequences and `security.md`, covering (a)–(c). Consider a content-based pass that fits the new rule: at forget time, clear or delete M-owned texts and pending cards that contain N's household terms (names and alias), and list any cards in Anki that matched. At minimum, delete pending `anki_outbox` rows whose front, back or sentence contain N's name.

**3. Medium — E8 "After: one `VACUUM`" and Rollout 3: who runs it, where, and when the values actually leave the file.**
Probe (c): `VACUUM` inside a transaction → `cannot VACUUM from within a transaction`, so it cannot be part of `_step`. In WAL the VACUUM writes to the `-wal`, and the canary was **still in the main file** after it; it disappeared only after `wal_checkpoint(TRUNCATE)`. The connection `migrate_file` opens sets neither `secure_delete` nor `journal_size_limit`, so the `-wal` grows to the size of the whole file. Rollout step 3 also says "the first open migrates to 7, then `VACUUM`", but `Store._open_schema` raises `NeedsMigration` and never migrates.
Fix: in `migrate_file`, after the last step and still under the exclusive `.users` lock, run `VACUUM`, then `PRAGMA wal_checkpoint(TRUNCATE)`, and fail loudly if the checkpoint reports busy. The test checks the main file **and** the `-wal`, and excludes `backups/` (the `leafi-v6-*.db` copy keeps the columns by design). Rollout: `leafi backup`, `leafi migrate`, done.

**4. Medium — E9 "`brain_calls` … refused (the audit write logs and drops them)" does not happen with today's `_insert`.**
`call._insert` catches `LearnerUnavailable` and retries with `_withheld(row)`. Under an owner fence the retry has the same owner and is refused too, and the second `LearnerUnavailable` escapes:
- `busy.retry` re-raises everything that is not a busy `OperationalError`, so `write_audit` raises;
- `loop.finalize` calls `bc._insert` directly and catches only `OperationalError`, so `run_session` skips `deliver`, `finalize_guest` and the `post_done_at` write.

This is rare (a session's learner cannot be marked while `post_done_at IS NULL`), but it can happen when `owner_alive` misjudges a live owner.
Fix: `_insert` catches the refusal, logs it and returns; delete `_withheld`; add a test where the owner is marked between queueing an audit row and `finalize` flushing it.

**5. Medium — E9 fence: the table set, the SQL and the architecture test are not specified.**
- `PROVENANCE_TABLES` is derived from `PROVENANCE`, which goes, so a careless edit leaves `fenced = DIRECT` and `test_architecture` stops catching inserts into `activities`, `utterances` and `brain_calls`.
- `_NAMES_LEARNER` loses two of its three alternatives. That is benign: an `UPDATE activities SET outcome=…` on a forgotten session hits 0 rows because the row is already deleted. Say so.
- Today the fence is vacuous for any row without sources: `id IN ()` gives `COUNT = 0 = 0`. Every `start_activity` and every page or system `brain_calls` row bypasses it now; the owner fence closes that hole, which is an improvement.

Fix: define `SESSION_OWNED = {"activities", "utterances", "brain_calls"}` explicitly, and say why `cycles`, `page_reads`, `observations`, `miscues` and `practices` stay unfenced (written only by a running session, which `forget` refuses). `insert_named` requires `session_id` in `cols` and uses `… WHERE EXISTS(SELECT 1 FROM reading_sessions rs JOIN learners l ON l.id = rs.learner_id WHERE rs.id = ? AND l.forgetting = 0)`. For direct rows that carry a `session_id` (`encounters`, the notes tables), `insert` checks both the row's learner and the session's learner. Drop `_purge_derived` from `_WRITE_EXEMPT`. Decide whether `update_named` stays, as an owner check through `_OWNER_SQL`, or goes.

**6. Medium — E10 order: commit 3 (E6) cannot be green without commit 4, unless it silently empties the fence.**
E6 deletes `provenance.py`, but `learner_store` imports `PARENT_SOURCE`, and `call._row`, `cards.stored_text`, `knowledge.record_encounter` and `rows`/`activities` build the NOT NULL provenance values from `Provenance`/`join`. To stay green, commit 3 must write constant `('system','[]')`. A build at commit 3 then fences nothing on sources, and `_purge_derived` finds nothing, while the CLI still promises it does. E11 also lists only `test_forget` and `test_migration_7`. The reads of the dropped columns in `test_migration_5` (116–121), `test_migration_6` (58), `test_learner_store` (45–46, 127–182), `tests/seed.py` (23–24, 47), `test_brain_call`, `test_activity_status`, `test_brain_activities`, `test_card_checks`, `test_anki_single_path` and `test_harness_sessions` all change in commit 4.
Fix: land E8–E9 together with the storage-facing half of E6 in one commit, or put E8–E9 before E6. List the test files in E11.

**7. Low — E8 "one transaction under `migrate()`'s `BEGIN IMMEDIATE` (ADR-0019 §5)".**
There is no `migrate()`. `migrate_file` reads the version once, before the backup and outside any transaction, and is protected by the exclusive `.users` lock: a second migrator or a `Store` gets `DatabaseInUse`. `_step` opens its own `BEGIN IMMEDIATE`, and a crash or error mid-step rolls the DDL back to 6, so a rerun works (each rerun writes one more `leafi-v6-*` backup). That is sound, but the design cites the wrong mechanism.
Fix: reword. Implement step 7 inside `_step`'s pattern (it can even be `_step(conn, 7, SCHEMA, {})`, a 12-step rebuild, if DROP COLUMN is not wanted), and keep the `_hook` failure-injection case in `test_migration_7`.

**8. Low — Rollout: backups and restore are not mentioned.**
Restoring the migration backup, or any older backup, brings back the columns (harmless: `Store` refuses version 6 and `migrate` drops them again). It also brings back every row forgotten since that backup. After E9 that is still true, and copies in M's rows were never deleted anyway.
Fix: one line in Rollout that cites ADR-0019 §8, plus "rerun `forget --learner` after a restore".

**9. Low — E7/E9: the TTS-cache wipe and ADR-0018 §1's list.**
- `forget_learner(store, id, data_dir)` has no `cache_dir`.
- `cache/tts/camera/` is the go2rtc camera's push folder (`go2rtc_camera.local_dir`), so a whole-tree delete removes it.
- On Windows a clip held open makes `rmtree` raise after the database deletes. The learner then stays marked, which is re-runnable but noisy.
- E9 says "as ADR-0018 §1 already lists", but `data/evals/decisions/` and the DEBUG logs are not in the code today.

Fix: pass `cache_dir` in; delete only the top-level `cache/tts/*.json` files and their clips, before the final transaction (as for `data/learners/`); either track the evals and logs items or say they are deferred.

## Sound

- All 17 `DROP COLUMN`s succeed together in one `BEGIN IMMEDIATE` on WAL, with `legacy_alter_table` ON or OFF. Every CHECK is a column constraint on its own column; no index, partial index, foreign key, view or trigger names the columns (the six triggers sit on `learners` and `household_terms`). `integrity_check` returns `ok` and `foreign_key_check` is empty.
- The column list is complete: the only other match, `corrections.source_learner_id`, is an owner pointer that `forget` still clears, and it should stay.
- A migrated file's `schema_of` equals `SCHEMA` with the 17 definitions removed: no difference in the probe.
- `VACUUM` works in WAL with another connection open, even one holding a read transaction.
- Renumbering M7 and M7f to 8 and 9 is safe because neither is written, provided each step targets a frozen constant (finding 1).
- `forget --session` and `--book` never used provenance and are unchanged.
- The conditional insert stays one statement and is WAL-safe (`Store` writes cannot hit `SQLITE_BUSY_SNAPSHOT`, ADR-0019 §3). Removing the source rescan leaves no hole for a session-owned or direct write, because both are fenced by owner and a session cannot start for a marked learner (`reading_sessions` goes through `insert`). A row that slips into an unfenced table naming N (`egress_log`, `corrections`) makes the last `DELETE FROM learners` fail on its foreign key and leaves N marked for a rerun, as it does today.
