Review **E8 (migration 7) and E9 (`forget` and the write fence by owning learner)** of
`docs/plans/active/2026-10-24-content-only-egress-design.md` (rev 1) as a design, not as prose, together with
`docs/adr/0021-content-only-egress.md` and the research `docs/research/2026-10-24-content-only-egress.md`. The rest
of the design (E1–E7, the privacy rule itself) is the owner's decision and is out of scope for this round (owner,
2026-10-24: privacy-only changes need no review); read it only where E8–E9 depend on it, and do not argue the
content-only rule. Check against `docs/adr/0018-learners-and-privacy-v2.md` (§1 Forget, the fence, guests; §3
Columns; §7.2 migration 5), `docs/adr/0019-sqlite-wal-mode.md` (§5 migrations in the lock, §7 `secure_delete` and
`VACUUM`, §8 backups), `docs/adr/0010-*.md` (§9 deletion) and the code they change: `leafi/core/storage.py`
(`SCHEMA`, `SCHEMA_V5`, `_V5_COPY`, `migrate_file`, `_step`, every table with `*_provenance_class` /
`*_source_learners`), `leafi/core/learner_store.py` (`stated_sources`, `insert`, `insert_named`, `update_named`,
`PROVENANCE_TABLES`, `_OWNER_SQL`), `leafi/study/records.py` (`forget`, `_CLEAR`, `_purge_derived`, the rescan,
`LearnerBusy`), `leafi/study/brain/call.py` (`_row`, `_insert`, `_withheld`), `leafi/study/cards.py`,
`leafi/study/knowledge.py`, `leafi/services/tts/__init__.py` (the cache sidecar), `tests/test_forget.py`,
`tests/test_learner_store.py`, `tests/test_migration_5.py`, `tests/test_migration_6.py`, `tests/test_architecture.py`.
Project rules: `AGENTS.md`. Leafi runs in a child's home; `forget` is how a parent removes a child's data.

What will be hard to get right, and what will keep going wrong? In particular:

1. Migration 7 (E8): does `ALTER TABLE … DROP COLUMN` succeed on every listed column given SQLite's eight failure
   conditions (an index, a CHECK naming another column, a foreign key, a trigger or view, a partial index)? Check
   the real schema, including indexes and any table CHECK that names these columns. Is the list of tables and
   columns complete? Does the step fit `migrate_file` / `_step` (one transaction under `BEGIN IMMEDIATE`, the
   version re-read in the lock, ADR-0019 §5), and what happens to a file at schema 5 or below, a file opened by two
   processes at once, a crash mid-step? Does `VACUUM` after the step work under WAL, inside or outside the
   migration's transaction, with other connections open? Does the new `SCHEMA` (fresh file) equal a migrated file
   column for column? Is renumbering M7's and M7f's planned migrations to 8 and 9 safe?
2. `forget` by owning learner (E9): hand-execute `forget --learner N` on a household with learners N and M where
   N has sessions, notes, encounters, cards in `anki_outbox`, `brain_calls`, a correction, and M has a note and a
   card derived from a session with N present (or citing N). Which rows go, which stay, and does anything the
   design says goes stay (or the reverse)? Is every table ADR-0018 §1 lists reached by `learner_id` or by
   `session_id → reading_sessions.learner_id`, including `brain_calls` of N's sessions, `egress_log`, TTS cache,
   `data/learners/<id>/`, `data/evals/`? Are `forget --session` and `--book` still complete? Is the stated cost
   (derived copies in M's rows survive) the only loss, and is it stated where a parent would see it?
3. The fence (E9): with the subject changed from "every source learner" to "the owning learner", can a write land
   after `forgetting` is set or after the learner row is gone (a `brain_calls` audit row written in `finalize`, a
   card written by a late Brain reply, a note from `extract_notes` after the session)? Is the conditional insert
   still one transaction? What does `insert_named` look like for a table owned through `session_id`? What happens
   to the final rescan that read `json_each(source_learners)`? Does `test_architecture`'s fence regex still prove
   every writer goes through the fence?
4. Order and green suite (E10's commit 4, E11): can E8–E9 land as one commit with the full suite green, given the
   seeds and fixtures that write provenance columns (`tests/seed.py`, `test_forget.py`, `test_learner_store.py`, …)?
   Is anything left that reads a dropped column at runtime (a query, a JSON export, `doctor`, `report`)?
5. Backups and rollout (E8 rollout): with `leafi backup` before the migration and older backups predating it, can a
   restore bring dropped columns or forgotten rows back, and does the design say so?

Report findings as a numbered list, each with severity (High / Medium / Low), the decision or line it concerns,
the concrete failure (inputs → what breaks or survives), and a suggested fix. Say plainly when a part is sound. Do
not edit any file.
