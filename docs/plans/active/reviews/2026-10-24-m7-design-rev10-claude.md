# M7 design rev 10, increment round

- Prompt: `reviews/prompts/m7-design-rev10.md`.
- Reviewer: a fresh Claude session. Codex (`gpt-6-astra`, high) stopped at its usage limit before reading (quota back at 22:16).
- Object: rev 10 at `33ec0da`, checked against the code at that commit.
- Verdict: M7d can start once findings 1–6 are written in. Rev 11 answers all 12.

## Claims confirmed against the code

- The owner fence (`learner_store.py:25-83`).
- A refused audit row is dropped (`call.py:229-237`, `loop.py:209-213`).
- The `post_done_at` guard (`records.py:329-333`).
- `sync_outbox` skips forgetting learners.
- Cleanup also runs at the latest version.
- `knowledge_items.status` is a maintenance column.
- The `card_ack` backfill needs no outbox provenance column.

## Findings

Each finding was checked by the author before acceptance. Line references are to rev 10.

1. **High: `item_status_events` "gets no maintenance column".** This contradicts the `SET activity_id = NULL` in `_delete_session_records`. The architecture test would flag that UPDATE.
   - Fix: `activity_id` becomes its maintenance column.
2. **High: `reconcile` does not skip forgetting learners.** It selects every `sent` answer (`anki.py:308`, confirmed).
   - Failure: from M7d its `card_state` insert raises `LearnerUnavailable`. `World.refresh` catches only Anki errors (`world.py:56-60`, confirmed), so another learner's boundary crashes.
   - Fix: join `learners` with `forgetting = 0`, and catch `LearnerUnavailable` per row in every writer that runs outside a session.
3. **Medium: where the `card_ack` refusal is caught in `sync_outbox` is unspecified.**
   - Failure: if the ack and the event share one transaction, a refusal rolls back `anki_note_id`.
   - Fix: write the event after the ack, in its own statement.
4. **Medium: `test_migration_6` and `test_migration_7` hard-code 7.** `migrate_file` has no target version.
   - Fix: list both tests, and check the v7 shape from a fixture.
5. **Medium: the `knowledge_items.status` cache is not re-folded after migration 8.** `storage` (in core) cannot run the fold.
   - Fix: `leafi migrate` (CLI) runs `item_status.apply` over every item after `migrate_file`.
6. **Medium: the backfill is underspecified.**
   - `card_ids` is a JSON list.
   - The `add` and `update` rows duplicate the acks.
   - `day` needs `HOUSEHOLD_TZ`, which `migrate_file` does not receive.
7. **Medium: two passages still use source learners.** D8's audit refusal (re-render) and "Round 7 #6, #7" (`forget --brain-records` selects transcripts by source learners).
8. **Medium: the replay export (JSONL) writes unredacted leaves outside the database without a deletion step.**
9. **Low: the write time of `decision_records.record` is unspecified.** The outcome is known only after the activity ends.
10. **Low: the migration wiring wording.** Step 7 must target `SCHEMA_V7` (`storage.py:874` targets `SCHEMA`, confirmed). The "version advanced" wording is already true.
11. **Low: the deletion order names `forget_learner`'s items block instead of `_delete_owned` / `_DIRECT_DELETES`.**
12. **Low: other stale lines.** D1's test list, D4, D5's port fields and its `Text` bridge item, D10's eligibility, D11's provenance, M7e's "pruning", and "exempt from D22's write rule".
