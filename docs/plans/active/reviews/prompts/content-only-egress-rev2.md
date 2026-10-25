Increment review. Review **E8, E9 and E10's commit order** of
`docs/plans/active/2026-10-24-content-only-egress-design.md` **rev 2** as a design, not as prose. Round 1's findings
and how rev 2 answers them are in `docs/plans/active/reviews/2026-10-24-egress-e8e9-round-1-comparison.md` (themes
U1–U12) and the round-1 reviews beside it; `git diff f1461b6 65362b5 -- docs/` shows exactly what rev 2 changed.
E1–E7 and the content-only rule are the owner's decisions and out of scope (read them only where E8–E10 depend on
them). Check against the code: `leafi/core/storage.py` (`SCHEMA`, `SCHEMA_V5`, `migrate_file`, `_step`, `rebuild`,
`schema_of`, `Store._open_schema`, `_vacuum_into`), `leafi/core/learner_store.py`, `leafi/study/records.py`
(`forget_learner`, `_delete_session_records`, `_remember_notes`, the citation rule), `leafi/study/brain/call.py`
(`_insert`, `write_audit`, `flush_audit`), `leafi/services/tts/__init__.py` (cache layout, publish), `leafi/cli.py`
(`forget`, `migrate`), `leafi/privacy/pseudonym.py` (which learner names the lists protect), `tests/test_architecture.py`,
`tests/test_migration_6.py`, `tests/test_forget.py`. Project rules: `AGENTS.md`; ADR-0018 §1, ADR-0019 §5–§8.

1. For each of U1–U12: is it closed, partly closed (say what is left), or not closed?
2. What does rev 2 introduce that is new and wrong or underspecified? In particular: `_step(conn, 7, SCHEMA, {})` on
   the 20 dropped columns (does the differ rebuild exactly those tables and keep every index and trigger?); the
   cleanup after the commit and its rerun on a file already at the latest version (does `migrate_file`'s early
   return allow it; what does the CLI print; can it run while a `Store` is open elsewhere?); the `legacy_prov`
   bridge between commits 3 and 4; the in-statement `EXISTS` fence for `insert`, `insert_named` and `update_named`
   (write the SQL for one session-owned insert and one update and hand-execute them while N is forgetting, after
   N's session is deleted, and for M); whether `SESSION_OWNED = {activities, utterances, brain_calls}` is the right
   set and `test_architecture` can prove it; moving `alias` and linked `household_terms` into `household_terms` (a
   uniqueness or kind conflict? what `pseudonym.py` reads); the TTS cache deletion with the publish lock.
3. Anything left that makes commit 4 impossible to land with the full suite green.

Report findings as a numbered list, each with severity (High / Medium / Low), the decision or line, the concrete
failure (inputs → outcome), and a suggested fix. Say plainly what is sound. Do not edit any file.
