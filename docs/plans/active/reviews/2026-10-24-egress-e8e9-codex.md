# Content-only egress E8–E9 — codex (round 1)

Reviewer: codex-cli 0.155.0, `gpt-6-astra`, effort high, read-only sandbox, on `reviews/prompts/content-only-egress.md`, 2026-10-24. Output copied verbatim.

E8–E9 need revision before implementation. I found eight issues; the column-drop operation itself is sound.

1. **High — E8 does not fit the existing migration chain.**  
   [E8 and rollout step 3](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-24-content-only-egress-design.md:56) assume an automatic migration on first open. `Store._open_schema()` instead raises `NeedsMigration`. Also, [migration 6 currently targets `SCHEMA`](/E:/GitHub/scil/Leafi/leafi/core/storage.py:821). Editing that constant to remove provenance makes a version-5 upgrade remove the columns during step 6; a subsequent step 7 issuing `DROP COLUMN` then fails because they are already gone. Version-4 upgrades inherit this problem.

   **Fix:** freeze `SCHEMA_V6`, preserve `SCHEMA_V5` and `_V5_COPY`, and explicitly sequence 5 → 6 → 7 in `migrate_file`. Specify the transaction wrapper for the DROP statements: `_step` currently rebuilds tables and does **not** reread `user_version` inside its transaction. Keep the exclusive `.users` lock, reread the version after `BEGIN IMMEDIATE`, and change rollout to explicit `backup` → `migrate` → cleanup → restart. Test upgrades from 4, 5 and 6, interruption, rerun, and fresh/migrated schema equality.

2. **High — E10’s independently green commits need a compatibility bridge.**  
   [Commit 3 removes provenance before commit 4 removes its storage requirements](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-24-content-only-egress-design.md:75). At schema 6, the provenance columns remain `NOT NULL` without defaults. Removing those writer arguments produces constraint failures; retaining them after migration 7 produces unknown-column failures. Deleting `core/provenance.py` also breaks `learner_store` unless its dependency is handled in that earlier commit.

   E11 additionally misses concrete fixture work: `tests/seed.py` writes provenance columns, migration-5 tests query them after upgrading, and migration-6 tests assert the latest version is exactly 6.

   **Fix:** move storage-dependent provenance removal into commit 4, or specify a temporary storage adapter. Include all affected writers, seeds, assertions and architecture checks in the same schema-changing commit. Keep historical migration fixtures intact; distinguish tests of an intermediate version from upgrades to the latest version.

3. **High — E9’s promise that forgotten names remain protected is incomplete.**  
   [E9’s accepted-cost justification](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-24-content-only-egress-design.md:65) relies on moving N’s names into `household_terms`. The current [forget implementation](/E:/GitHub/scil/Leafi/leafi/study/records.py:277) moves only `display_name`. Pseudonymisation also protects `learners.alias`.

   **Failure:** N has alias “Mimi”; M’s retained note contains “Mimi”; N is forgotten. The alias disappears with N’s row and is absent from `household_terms`. With the detector off or missing that name, the surviving text can subsequently leave without that replacement.

   **Fix:** explicitly preserve every identifying name currently supplied by the learner row, including the alias, before deletion. Add a regression test that forgets N and redacts M’s surviving text afterward.

4. **Medium — E8 leaves physical cleanup and its recovery undefined.**  
   [E8](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-24-content-only-egress-design.md:58) assumes `secure_delete` is already enabled. `migrate_file` opens a raw SQLite connection rather than a `Store`; my check found its default is **0**. `VACUUM` cannot run inside the migration transaction. It can run in WAL mode, but successful vacuuming does not itself establish that old WAL pages have been removed; readers can delay checkpointing. [SQLite VACUUM](https://www.sqlite.org/lang_vacuum.html), [WAL checkpointing](https://www.sqlite.org/wal.html#checkpointing).

   **Failure:** step 7 commits, then the process crashes before cleanup. A rerun sees version 7 and returns immediately, leaving the promised cleanup unfinished.

   **Fix:** enable `secure_delete` on the migration connection; run `VACUUM` after commit while retaining migration exclusion; complete a `TRUNCATE` checkpoint. Define a retryable cleanup operation for an already-version-7 file and report incomplete cleanup. Test canary absence in both the database and WAL, including interrupted cleanup.

5. **Medium — E9 needs an ownership-based fence registry and executable coverage rule.**  
   [E9](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-24-content-only-egress-design.md:66) states the correct invariant, but the existing machinery derives eligibility from provenance: `insert_named` checks source IDs, `PROVENANCE_TABLES` defines coverage, and `_OWNER_SQL` omits `brain_calls`. Removing sources without replacing this machinery makes the empty-source predicate succeed.

   **Failure:** a late audit row can enter while N is marked but its session still exists. After session deletion, the same path produces a foreign-key error instead of the promised logged refusal. Merely removing provenance terms from the architecture regex also stops it detecting raw text updates such as `UPDATE activities SET outcome=...`.

   **Fix:** define explicit direct-owner and session-owner registries. For a session-owned insert, put `EXISTS(SELECT 1 FROM reading_sessions JOIN learners ... WHERE session_id=? AND forgetting=0)` inside the insert statement; missing sessions must refuse. Resolve update ownership within the protected statement/transaction, include `brain_calls`, and replace the regex’s provenance-based coverage. Test delayed audits, cards and notes both while marked and after deletion, plus allowed writes owned by M.

6. **Medium — The sibling-survival rule has an existing citation exception, and parents are told the opposite policy.**  
   [E9’s example](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-24-content-only-egress-design.md:65) suggests M’s derived note survives. However, `_delete_session_records` deletes a note belonging to **any learner** when all its citations target N’s session activities. I reproduced this in memory: M’s exclusively cited note disappeared; M’s card remained. A note with citations outside N’s session survives and loses only the removed citations.

   Separately, the [CLI preview](/E:/GitHub/scil/Leafi/leafi/cli.py:117) still promises deletion of “every text derived from them”; the help text makes the same promise. E10 mentions other CLI wording changes, not this one.

   **Fix:** explicitly retain and document the citation exception, or deliberately change it for learner deletion without changing session deletion. Test both citation cases. Update the preview, help and completion output to explain that copies in other learners’ records can survive, including their cards.

7. **Medium — Whole-cache deletion needs coordination with active TTS writers.**  
   [E7’s cache deletion, relied on by E9](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-24-content-only-egress-design.md:54) is not covered by N’s database fence. N may be forgotten while M’s session is active. TTS writes audio and then publishes its sidecar after an `await`.

   **Failure:** M starts synthesis, `forget N` clears the cache, then synthesis publishes another entry—or deletion encounters an open audio file. The database owner check cannot resolve either case. `forget_learner` also currently receives `data_dir`, not the configured cache location.

   **Fix:** specify how the configured cache is passed to deletion and coordinate purge with synthesis/publication. Preserve the marked learner on deletion failure so retry remains possible. Test an in-flight synthesis and a held-open file. Distinguish currently absent evaluation-record writers from implemented deletion coverage; `records.py` still treats evaluation cleanup as future work.

8. **Low — Rollout should explicitly describe restoration of pre-migration backups.**  
   [The rollout](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-24-content-only-egress-design.md:87) requires a backup but does not explain its consequences. Restoring a version-6 backup restores provenance columns and its live learner rows. Migrating that restored file removes the columns again; it does **not** replay subsequent `forget` operations.

   **Fix:** carry ADR-0019 §8’s restore warning into this rollout: backups retain their historical data, restoration requires migration again, and previously forgotten learners must be forgotten again. Preserve the existing CLI backup warning.

The following parts are sound:

- **DROP COLUMN eligibility:** all **20 columns across seven tables** dropped successfully against the populated current schema in memory. Row counts and indexes survived; integrity and foreign-key checks passed. None encounters SQLite’s eight documented blockers; the provenance CHECKs belong to the dropped columns themselves. [SQLite DROP COLUMN](https://www.sqlite.org/lang_altertable.html#alter_table_drop_column).
- **Deletion traversal:** the existing helpers reach N’s session evidence, activities, cycles, `brain_calls` and session egress rows; direct deletion reaches N’s notes, encounters, outbox, items, consents and remaining egress rows. Corrections and revisions intentionally survive, with attribution cleared. M’s independently owned copies survive after removing `_purge_derived`, subject to the citation exception above.
- **Session/book deletion:** their existing sanctioned retention rules do not depend on provenance columns. Retained summaries, corrections and—in session deletion—encounters are intentional.
- **Concurrency foundations:** the exclusive migration lock prevents concurrent Leafi migration/opening. Transactional drops roll back together; I verified rollback restores a dropped column. The existing `post_done_at` busy check also protects post-session work and should remain.
- **Renumbering:** moving the unimplemented M7/M7f migrations to 8/9 is safe, provided their plans and test names move together.

No files were edited. Verification used source inspection and in-memory SQLite probes; I did not run the file-writing pytest suite.
