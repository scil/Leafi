# M7 design rev 4 — fresh Claude, fallback for codex (round 4)

Reviewer: a fresh Claude agent on `reviews/prompts/m7-design-rev4.md`, run 2026-10-23 while codex's quota was out (until 2026-10-24 02:00). It read the design, the rev-3 review, the aborted codex probe, ADR-0017 §5 and §6.2, and `egress.py`, `versions.py`, `destinations.py`, `config.py`, `learner_store.py`, `records.py`, `anki.py`, the harness (`inputs.py`, `latch.py`, `construct.py`, `menu.py`, `rows.py`, `settings.py`), both brain adapters, `envprotect.py`, `tests/test_construct.py`; one in-memory probe of the real `Inputs` with a fake source. No file edited.

## Verdicts

| Item | Verdict | Remaining |
|---|---|---|
| S1 | closed | a learner-class leaf whose only source is `0` (10) |
| S2 | partly | per-request stamping fails when the reader is busy (1); page turns unstamped (6) |
| S3 | closed | — |
| S4 | closed | new timing hazard (5) |
| S5 | closed | the author's false-positive call is right (ADR-0017 §6.2); the hand-run is consistent |
| S6 | closed | one existing test to port in M7a (11) |
| S7 | partly | `item_status_events` not fenced, deletion order not placed (3); `brain_calls` and assessment UPDATEs not fenced (2) |
| S8 | partly | no evidence path when a card comes back (7) |
| S9, S10, S12 | closed | — |
| S11 | partly | a settings-page save still makes running processes refuse; backend prefix undefined (8, 9) |

## Findings

1. **High · D12 — a request made while the reader is busy is lost.** `Inputs._request` does nothing while `_busy[name]`; `listen` requests a read only when the buffer is empty. Probe: A's read still running when B listens → B gets A's late line and no second read starts. If the stamp is per reader and B overwrites it, A's line reaches B (S2 reopens); if it stays with A's request, B drops it and then waits with no read outstanding (hangs until its timeout, or forever with `timeout_s=None`). Fix: the stamp belongs to the read in flight; after every dropped item, and when the buffer holds only stale items, `listen` requests a read again with its remaining time; test a reader busy for A, then B's own input reaching B.
2. **High · D11/D18/D19 — rows in B's session that quote A are written without the forget fence.** The fence covers inserts into `DIRECT` tables only; `brain_calls` has no `learner_id` and is not in `DIRECT`; `apply_records` writes `assessment` as an UPDATE of an existing `activities` row (as `rows.finish_activity` already does). M7 makes B's rows quote A; a row written after `forget --learner A`'s final rescan survives with A's text (real text for a local backend, D11); `s.pending_audit` written at `finalize` widens the window. Fix: a fenced `brain_calls` insert (`INSERT … SELECT … WHERE (SELECT COUNT(*) …) = ?` over its stated sources), a fenced UPDATE for the assessment columns, a refused audit row dropped, not left pending; test A marked between the walk and `finalize`.
3. **Medium · D17/D19 — `item_status_events` unfenced; its deletion order does not fit the code.** `sync_outbox` and `reconcile` process every learner's rows, so B's session writes A's `card_ack`/`card_state` while `forget --learner A` runs; an insert after A's items are deleted raises `IntegrityError` there, uncaught. `forget_learner` deletes each session's activities and `reading_sessions` row in its per-session loop before the items block, so the session-bound events and the `activity_id` NULLing must be in `_delete_session_records`. Fix: `item_status_events` in `DIRECT`; `sync_outbox`/`reconcile` skip learners marked `forgetting` and catch `LearnerUnavailable`; session-bound handling in `_delete_session_records`.
4. **Medium · D5/D8 — a cancelled call cannot return its `CallRecord`;** inside the backend, `fail_after` and the latch's cancel both arrive as cancellation; the prepared payload and attempt id exist only inside the backend. Fix: the walk passes a mutable attempt record the backend fills right after `prepare`; the walk classifies (`TimeoutError` → `timeout`, the outer cancel → `cancelled`) and reads `transmitted_attempts` from `egress_log` by attempt id.
5. **Medium · D8 — `prepare` is synchronous on the event loop;** the first cloud call with learner text loads spaCy (seconds) inside `fast`'s `fail_after(2.0)`, blocking the deadline, the filler and stop/skip. Fix: load the detector at session start with `anyio.to_thread`; bound `prepare` in the real-clock test.
6. **Medium · D12 — page turns are never stamped:** `_watch_page` sends `/page` straight into `_send`, bypassing `_deliver`. Fix: stamp it, or exempt page turns explicitly and say which listens accept them.
7. **Medium · D17 — a card that comes back is never followed again:** `card_ack` only on the first acknowledgement; `observe_cards` writes only on a changed interval or lapses. Fix: a `card_state` for any tracked id whose latest event is `card_gone` and which `cardsInfo` returns; `card_ack` per (item, card id) not yet live; lapses compared within one card id; never `card_gone` on `AnkiUnavailable`.
8. **Low · D9 — a settings-page save makes running processes refuse** (the fingerprint changes although effective values did not); commenting out `STUDY_BRAIN_MODEL` is a `PRIVACY_FLOOR` edit needing a confirmation; the legacy keys are not in `POLICY_KEYS` while the fallback is in use. Fix: fingerprint the effective tier values; migrate only on an explicit owner edit.
9. **Low · D9 — the fallback is underspecified:** no backend prefix for a bare `STUDY_BRAIN_MODEL`; "set" indistinguishable from the pydantic default (`model_fields_set` or default None); the fallback bypasses `GATE_FLOOR`'s save check; `GATE_FLOOR` gates exact values, so "`ollama:*` per entry" is a new gate kind in `envedit`; `brain_local_model` ignores an existing `BRAIN_LOCAL_MODEL`. Fix: prefix `claude:`, refuse a non-Claude legacy value, `doctor` names it.
10. **Low · D2 — a learner-class leaf whose only source is `0` passes** (`if not t.sources` sees `(0,)`). Fix: refuse when no non-zero source remains; strip `0` from `insert`'s `sources=` too.
11. **Low · M7a — `test_construct::test_a_kind_outside_the_menu_and_a_url_are_rejected` breaks** (it sets `s2.generate` and expects "no URLs"): port it in M7a. D7's post-session `Budget` reads `limits.extract_calls`, which enters `SPEC` only in M7d.
12. **Low · editorial** — D2 and D8 each repeat a sentence; D17's "`forget --learner` … then calls `apply` for each" runs on items it has just deleted.

Step order: M7a green once 11 is ported; M7b needs 1 and 6; M7c sound; M7d needs 3 and 7 (and the owner's backup and migrate); M7e needs 2.

## Sound

`core/provenance.py` and the conjunction rule with source `0` handled at `prepare`, `_gate`, the fence and `json_each` (hand-run for a `[A, 0]` leaf, local and cloud); D1's model binding with loopback literals; D7 inside each busy attempt with one synchronous charge; D8's walk and per-(purpose, tier) limits with reset and audit outside the walk (worked example holds); the single cache breakpoint; `decision_records` in the database behind the fence, sources over every stored leaf, its own deletion order; the total fold and the S5 call; the handler gate and `construct`'s `Rejected` until M7c.

**Readiness: not ready.** First D12's reader requests (1) and the fence on B's writes that quote A (2, 3); 4–7 can be fixed in their steps; 8–12 are small edits.
