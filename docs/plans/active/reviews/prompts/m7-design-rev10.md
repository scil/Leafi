Increment round. Review **revision 10** of `docs/plans/active/2026-10-23-m7-brain-design.md` as a design, not as prose.
`git diff 33ec0da~1 33ec0da -- docs/plans/active/2026-10-23-m7-brain-design.md` shows what rev 10 changed. Rev 10 brings
the not-yet-built steps M7d and M7e in line with content-only egress, which has landed: ADR-0021 and
`docs/plans/active/2026-10-24-content-only-egress-design.md` (E6, E8, E9, E13 are the parts that matter; the content-only
rule itself is the owner's decision and out of scope). M7a–M7c are implemented; review them only where M7d–M7e depend
on them.

1. Check rev 10's claims against the code as it is: `leafi/core/learner_store.py` (`DIRECT_OWNED`, `SESSION_OWNED`,
   `insert`, `insert_named`, `update_named`), `leafi/core/storage.py` (`SCHEMA_V6`, `SCHEMA`, `migrate_file`, `_step`,
   the cleanup on the latest version), `leafi/study/records.py` (`forget_learner`, `_delete_session_records`),
   `leafi/study/harness/guests.py` (`discard`), `leafi/study/anki.py` (`sync_outbox`, `reconcile`, `_update_status`),
   `leafi/study/brain/call.py` (audit rows, `pending_audit`), `tests/test_architecture.py` (`MAINTENANCE_COLUMNS`,
   exemptions), `tests/test_migration_7.py`.
2. What does rev 10 leave wrong or underspecified for M7d and M7e? In particular: migration 8's wiring after
   migration 7 (freezing `SCHEMA_V7`, the version advanced after each step, a file at 4, 5 or 6 reaching 8, the
   backfill of `card_ack` from `anki_outbox` now that the outbox has no card provenance columns); D22's "a refusal
   drops the row" for `item_status_events` written by `sync_outbox` / `observe_cards` outside a session, and for
   `apply_records`; D17's `forget --session` re-fold and the deletion order with foreign keys on; D19's
   `decision_records` storing unredacted leaves (is anything sent or read from it outside egress?) and
   `forget --brain-records` by owner only; any passage in D17–D22 or the M7d/M7e steps that still assumes source
   learners, `cloud.text`, `CLOUD_PARENT_TEXT`, a per-leaf filter or the provenance type.
3. Anything that makes M7d impossible to land as one commit with the full suite green.

If nothing needs to change, say so plainly. Otherwise report findings as a numbered list, each with severity
(High / Medium / Low), the decision or line, the concrete failure (inputs → outcome), and a suggested fix. Do not edit
any file.
