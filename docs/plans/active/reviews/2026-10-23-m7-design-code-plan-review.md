# M7 design rev 1 — code-plan-review (round 1)

Reviewer: a fresh Claude agent running `code-plan-review`, independent of the other two reviewers. Object: `docs/plans/active/2026-10-23-m7-brain-design.md` rev 1. Date: 2026-10-23.

## Findings

1. **High · D9 / D4 — two definitions of "local".** D9: local only when `backend:model` is on `LOCAL_MODELS`; egress decides per destination (`destinations.py` registers `ollama` as `local` whatever the model; `prepare` reads `dest.locality`; `Settings.local_model_list()` has no caller). An `ollama:<cloud-hosted model>` tier passes egress with no gate, pseudonymisation or detector. Fix: `prepare` / `may_send` take the model and decide locality from `LOCAL_MODELS`; `test_privacy` case.
2. **High · D14 — the replay set as a data path.** "Never leaves the PC" contradicts `replay_decisions.py` sending lines to a tier; lines stored as rendered strings lose provenance, so a re-prepare sends learner words as `system` strings past `_gate` and the detector; the filter is in `brain_call`, not `prepare`; no ADR-0018 §3 provenance and no §5 retention row for `data/evals/`; `forget --learner` cannot reach another learner's file holding this learner's derived text. Fix: store `Text` leaves `{value, provenance, sources}`, replay through the same filter, retention row, forget scans sources.
3. **High · D6 — the rejection reason as a `system` line.** A Pydantic error echoes `input_value=…` (reversed model output, may hold real names or the learner's words) and as `system` skips `_gate` and the detector. Fix: a fixed reason code, or the line carries the payload's provenance.
4. **Medium · D4 — filter granularity.** Dropping whole sections removes `last_activity`'s kinds and counts and `memory`'s difficulty keys for a learner with `cloud.text` off; ADR-0018 says "removed; observations carry expected words + category". Fix: drop leaves, keep the category; test.
5. **Medium · D4 — section order stated twice; no cache breakpoint named.**
6. **Medium · D1 / D7 — `ModelReply | None` cannot carry D7's outcomes.** Fix: an outcome on every return.
7. **Medium · D6 / D7 — the `brain_calls` row on cancellation** is written with `busy.retry` (anyio sleeps) inside the cancelled scope, so it is lost. Fix: a bounded shielded write, or reconciliation from `egress_log` in `finalize`; `test_cancellation` case.
8. **Medium · D5 — order in `admit`.** Code checks fingerprint, then budget, then versions with the reservation; `try_charge` can charge a transmission the version check or a busy store then refuses. Fix: charge at the reservation, or refund on refusal; test.
9. **Medium · D13 — derived status lacks evidence.** `* → ignored` is in no event table; Anki-mode `known` reads the interval live; `forget --session` cannot reproduce either. Fix: an item-status event shape (migration, regression test).
10. **Medium · D2 vs ADR-0018 §1/§5 — one rule in two places.** ADR-0018 names `BRAIN_TIERS` and a `household_settings_version`; D2 has three keys and version 0; the new keys are not in `versions.POLICY_KEYS` though a tier change moves learner text between backends. Fix: amend the ADR; decide on `POLICY_KEYS`.
11. **Medium · D11 — `answer` listed as a `generate` kind;** it is its own purpose with its own eligibility.
12. **Medium · D10 — construction becomes async and may call `generate` per candidate and per re-offer;** moment per offer unstated. Fix: async construction, content cached per boundary keyed by epoch.
13. **Low · D7 — response provenance unspecified;** "surrogates" false for local backends.
14. **Low · D3 — `max_tokens` with thinking always on (Opus 5.5) may truncate;** `anthropic.lib._parse._transform.transform_schema` exists (private) — adopt behind the adapter or say why not.
15. **Low · D1 — two provenance types in core** (`ports.Provenance` and the moved `Text`). Fix: `Text` holds a `Provenance`.
16. **Low · H7 — provenance lines missing** for the [beyond ADR] mechanisms.
17. **Medium · steps with no Confirmation test:** D14 forget / guests / re-pseudonymisation; `extract_notes` drops and guest skip; filler cancel and camera Face text; stripped keywords enforced; mismatched epoch dropped; the `STUDY_BRAIN_MODEL` import; the Ollama probe. Also: is `limits.extract_calls = 2` in calls or tier-weighted units (tier-weighted makes `deep` unaffordable)?

## Decisions for the owner

1. Replay to the cloud: local backends only until the owner opts in (recommended), or cloud for learners with `cloud.text` on.
2. Tier keys: amend ADR-0018 to three keys and add them to `POLICY_KEYS` (recommended), or keep `BRAIN_TIERS`.
3. The design's three questions stand; on the replay set, off by default (because of 2).

## Sound

Egress reuse (gate made public, budget on the token, `messages.create` with the exact-body comparison); routing per the ADR with no same-tier re-ask; one `decide` schema per session; quiz answerability, confidence-gated answers, `cannot_tell` → `unavailable`; camera filler moved to M10; console buttons in M10; dated vendor facts.
