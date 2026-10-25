Confirming round. Review **E8, E9 and E10's commit order** of
`docs/plans/active/2026-10-24-content-only-egress-design.md` **rev 3** as a design, not as prose. The previous
round is `docs/plans/active/reviews/2026-10-24-egress-e8e9-rev2-codex.md` (findings V1–V8); `git diff 65362b5 61a0ae6
-- docs/plans/active/2026-10-24-content-only-egress-design.md` shows what rev 3 changed. Round 1's themes are in
`reviews/2026-10-24-egress-e8e9-round-1-comparison.md` (U1–U12). E1–E7 and the content-only rule are the owner's
decisions and out of scope. Check against the code: `leafi/core/storage.py` (`_PROV`, `SCHEMA_V5`, `SCHEMA`,
`migrate_file`, `_step`, `_truncate`, `_FileLock`), `leafi/core/lease.py` and its callers (`leafi/runner.py`,
`leafi/cli.py`), `leafi/core/learner_store.py`, `leafi/study/records.py`, `leafi/study/brain/call.py`,
`leafi/services/tts/__init__.py`, `leafi/services/tts/edge.py`, `leafi/services/tts/kokoro.py`,
`leafi/privacy/pseudonym.py`, `tests/test_architecture.py`, `tests/test_forget.py`. Project rules: `AGENTS.md`.

1. For each of V1–V8: closed, partly closed (what is left), or not closed?
2. What does rev 3 introduce that is new and wrong or underspecified? In particular: the cleanup on the
   already-current path under the `.users` lock (can the CLI take that lock while the supervisor or a study
   process holds a `Store`? what does it print?); the TTS purge under the study lease (does `lease.py` support a
   short take by `forget` and a check at session start; what if `forget` runs while no lease exists but a second
   `forget` or the supervisor touches the cache; is the cache path the same one the runner uses?); the fence's
   UPDATE scope by text column (is the column list complete against the schema? can `test_architecture` detect a
   raw UPDATE writing one of them?); the session tables' exclusion by `LearnerBusy` (is there any write to
   `miscues`, `observations`, `practices`, `page_reads` or `cycles` after `post_done_at` is set, e.g. recovery or
   `close_cycle` at a later session?); name preservation (does it match how `pseudonym.py` builds surrogates for a
   former learner?).
3. Anything left that makes commit 3 impossible to land with the full suite green.

If nothing in E8–E10 needs to change, say so plainly. Otherwise report findings as a numbered list, each with
severity (High / Medium / Low), the decision or line, the concrete failure (inputs → outcome), and a suggested fix.
Do not edit any file.
