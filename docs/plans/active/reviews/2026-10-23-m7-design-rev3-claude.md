# M7 design rev 3 — fresh Claude, fallback for codex (round 3)

Reviewer: a fresh Claude agent on `reviews/prompts/m7-design-rev3.md`, run 2026-10-23 because codex stopped at its usage limit (`2026-10-23-m7-design-rev3-codex-aborted.md`). It read `egress.py`, `versions.py`, `privacy/settings.py`, `destinations.py`, `learner_store.py`, `records.py`, `anki.py`, the harness (`inputs.py`, `menu.py`, `construct.py`, `loop.py`, `activities.py`), `asr/__init__.py`, `hub.ListeningGate` and both brain adapters, and probed `versions.snapshot` / `stale` and the fence SQL in memory. No file edited.

## Verdicts

| Item | Verdict | Remaining |
|---|---|---|
| R1 | closed | Low remarks (9) |
| R2 | partly | source `0` refused at `admit` by `versions.stale` (1) |
| R3 | closed | the household fingerprint still checked once before the retry loop (10) |
| R4 | partly | reset and audit spend the moment between tiers; the design's own example falls on the boundary (4) |
| R5 | partly | ownership covers only the parked slot; a late voice read bypasses it (2) |
| R6 | closed | rule 2 departs from ADR-0017 in `retrievals` mode (5) |
| R7 | closed | a card deleted in Anki undefined (8) |
| R8 | partly | "sent vs all leaves", `DIRECT` membership, foreign-key order on deletion (3, 7) |
| R9 | closed | — |
| R10 | partly | menu gating has no commit; `brain_local_model` unmapped (6) |
| R11–R14 | closed | — |
| T23 | closed | — |

## Findings

1. **High · D2 — source `0` makes every mixed output unsendable.** `prepare` puts every text source into `versions.snapshot`; `snapshot(c, [0, 1])` gives `Source(0, kind=None)` and `admit`'s `stale` returns "source learner 0 is gone", for local destinations too; the whole request is refused, and a stored mixed note in `memory` makes the Brain unavailable for that learner. `privacy_settings.from_row(0, None)` is a non-learner, so `_gate`'s rule must come before the per-source loop. Fix: `PARENT_SOURCE` handled at every reader of sources (`prepare`'s set, `snapshot`/`stale`, the privacy map, `_gate`, `stated_sources`); a `test_privacy` case through `admit`, local and cloud. *(Matches the aborted codex round's probe.)*
2. **High · D12 — ownership only on the parked slot.** Readers are demand-driven and a pending read delivers to the next caller; ASR keeps `_recognising` shielded across pause; a learner speaking during A's `judge`, transcribed after `controls_only` exits, reaches B's `listen` through `_send` with no `interaction` check. The follow-up id is unspecified; `_SWITCHED` and `_TIMEOUT` during a wait unhandled. Fix: stamp each utterance in `_deliver` with `Inputs.current_interaction` and the epoch; filter stream items in `listen`; follow-up id = the parent prompt's; re-raise `_SWITCHED`, drop `_TIMEOUT` inside `controls_only`; test a late voice recognition across an item change.
3. **Medium · D19 — which leaves set `source_learners`.** "Of all leaves" vs "D2's output rule" (sent leaves); a withheld note of A stored without A in `source_learners` survives `forget --learner A`. Fix: union over every stored leaf, withheld included; test it.
4. **Medium · D8 — the O1 example fails at the boundary** (≈ 1.99 s left after `fail_after` at 3 s → `standard` skipped); reset (≤ 0.5 s) and audit (≤ 0.3 s) run between tiers. Fix: reset and audit outside the walk, or deduct their bounds; choose `PER_CALL_S[decide]` so `fast` leaves `MIN_TIER_S[standard]` plus a margin; a real-clock test.
5. **Medium · D17 rule 2 contradicts ADR-0017 §6.2 in `retrievals` mode** (the ADR reaches `known` by retrievals; only re-asking is limited to card-less items): a `known` item drops to `learning` on its card's acknowledgement. The hand-run is inconsistent (after `unignore` → `new`, it later forgets "the session of the only retrieval"). Fix: rule 4 applies in `retrievals` mode even with a card, only the recall day suppressed; or mark the departure; repair the hand-run. *(Author's check: the contradiction is a false positive — ADR-0017 §6.2 states "In both modes an item with an acknowledged Anki card follows Anki's state", which rule 2 implements. The hand-run inconsistency is real.)*
6. **Medium · menu gating has no commit.** `menu.allowed` adds `quiz` when `s.generate` is set and `learner_questions` when `s.routable_answer`; `loop.py` does `KINDS[act.kind]` and `KINDS` has neither (nor `teach_items`, `recall_items`): once the bridge computes them from `s.brain`, a learner saying "questions" → `KeyError`. In M7b, `construct` takes `spec.content` unvalidated for a `brain`-owned `read_aloud`/`add_cards`. `brain_local_model` unmapped. Fix: the `KINDS` gate in `menu.allowed` in M7a; `Rejected` for `brain`-owned content until M7c; name `brain_local_model`'s value.
7. **Medium · `forget --learner` foreign-key order and fence membership.** `item_status_events` and A's own `decision_records` must go before `knowledge_items` and A's sessions; a page-only observation has `source_learners` `[]`, so delete by `session_id` too; `decision_records` must join `DIRECT` and `PROVENANCE`; a `LearnerUnavailable` in B's session needs non-fatal handling; `forget --session S` leaves S-derived text in later sessions' `decision_records` (as in `brain_calls`) — state it or delete them.
8. **Low · D17 — a card deleted in Anki is followed forever.** Fix: a `card_gone` event, or "missing from `cardsInfo`" leaves rule 2. (An outbox row later `failed`: sound.)
9. **Low · D1 details.** Magpie is registered `cloud`, so "magpie when it exists" contradicts `model_bound`; a hostname's "this machine" check at prepare time vs `_transmit`'s own resolution (use the granted addresses or require a literal/loopback host); `qwen3` vs `qwen3:latest` fails safe (document); cloud-model detection by name is heuristic (consider a `doctor` probe of `/api/show`, unverified).
10. **Low · D7.** The household fingerprint checked once before the busy loop: move it inside each attempt. The post-session `Budget` counts calls but `charge` runs per transmission: a mediator retry spends 2 of 2.
11. **Low · D9.** An import that writes `.env` makes `PolicyWatch` stale and refuses study egress until restart: make it a read-time fallback or a CLI step.
12. **Low · D12 — `skip` during the filler** goes to the skip queue (the filler does not set `Inputs.speaking`) and skips the next activity; define it.

Step order: M7a green only with 6's gate; M7b needs 2 and 6; M7c sound; M7d needs 5 and 7 (and the owner's backup and migrate for migration 7); M7e needs 3 and 7.

## Sound

`core/provenance.py` breaks the cycle; the conjunction rule, with the fence and `json_each` handling `0` once excluded from the count; D1's model binding for both adapters; D7's in-transaction `can_cover`, commit, one synchronous charge, and the honest reservation accounting; D8's `fast` failure → `standard`; T23's single breakpoint; the fold is total and correct under forget; `observe_cards`, the backfill and the `−ivl/86400` conversion; moving the replay set into the database.
