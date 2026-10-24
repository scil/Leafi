# M7 design rev 2 - codex increment review (round 2)

Reviewer: codex `gpt-6-astra`, reasoning effort high, read-only sandbox, prompt `reviews/prompts/m7-design-rev2.md`, run 2026-10-23 (127,980 tokens). Its final message follows unedited.

**Revision 2 closes many round-one findings, but is not ready to implement unchanged.** The main remaining problems are privacy constraints lost by the provenance join, admission checks separated from reservation, input handling during Brain waits, incomplete item-status reconstruction, and concurrent replay-file deletion.

“Closed” below means closed by the design, subject to implementation and tests.

| Theme | Verdict | Assessment |
|---|---|---|
| T1 | **partly** | Shared resolver is right; caller compatibility, model binding and cloud-hosted Ollama rejection remain. Finding 1. |
| T2 | **closed** | Fixed codes and trusted paths remove the error-message leak. |
| T3 | **partly** | Learner-derived outputs retain provenance; mixed parent/learner restrictions do not. Finding 2. |
| T4 | **partly** | Structured leaves, current-settings replay and source-based deletion are specified; concurrent deletion and policy amendments remain. Findings 8–9. |
| T5 | **partly** | Charging after commit fixes repeated charging; atomic admission and reservation-versus-transmission semantics remain. Finding 3. |
| T6 | **closed** | Outcome-bearing records, asynchronous reset, shielded audit and pending rows address the original failures. |
| T7 | **partly** | `controls_only` lacks safe answer ownership, overflow behaviour and voice-reader coverage. Finding 5. |
| T8 | **closed** | Owned filler task group, awaited cleanup, error isolation and epoch checks are sound. |
| T9 | **closed** | Every alternative is checked; references are scoped; open-ended answers are conservatively unavailable. Semantic answerability remains an explicitly acknowledged limitation. |
| T10 | **partly** | Durable evidence and transactional rebuild are right; the fold and migration remain incomplete. Findings 6–7. |
| T11 | **partly** | Bridge, handler gating and coordinated async conversion help; concrete integration dependencies remain. Findings 10–11. |
| T12 | **closed** | Explicit schema transformation, complexity checks, body-equivalence tests and compilation probes address it. |
| T13 | **closed** | Strict selection and independently droppable content/records are specified. |
| T14 | **partly** | Shared deadlines and minimum-time checks help; escalation now cuts off valid fallback routes. Finding 4. |
| T15 | **closed** | Larger token allowances and explicit truncation handling address the design defect; sizing remains untuned. |
| T16 | **closed** | Per-leaf substitution preserves expected words, categories and counts. |
| T17 | **closed** | Manifest, protection floor, fingerprint and Ollama gate move together. |
| T18 | **closed** | Per-boundary caching, epoch invalidation and one absolute boundary deadline are the right rules. See the trace below. |
| T19 | **closed** | Announcements use the announcement band; rationale belongs to the actual proposal. |
| T20 | **closed** | Learner questions use purpose `answer`. |
| T21 | **closed** | O5 explicitly defers YLE; O6 aligns ranking with card checks. |
| T22 | **partly** | Most omissions now have steps; several acceptance cases and runtime integrations remain unassigned. Findings 11–13. |
| T23 | **open** | Revision 2 still names neither the application’s section order nor a cache breakpoint. Finding 12. |
| T24 | **partly** | Most small fixes landed; `epoch`/`turn` terminology and mechanism-provenance annotations remain inconsistent. Finding 14. |

1. **High — D1: the resolver does not yet cover the actual `prepare` contract safely.**  
   [D1](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-23-m7-brain-design.md:30) requires a model for Brain purposes, but both retained legacy adapters call `prepare` without it. Updating only the new `call(ModelRequest)` path breaks `run(BrainRequest)` immediately.

   Tracing the other callers: edge-tts, catalog, notifications, heartbeat, operational alerts and downloads have no Brain model. The local `ollama_probe` destination also has none. Applying the model allow-list to every destination marked `local` reclassifies that probe—and potentially Gatus—without justification.

   Two privacy checks are also missing: a cloud-hosted Ollama model must remain cloud even if mistakenly allow-listed, as ADR-0018 explicitly requires; and the resolver’s `model` must match the model actually encoded in the request. Otherwise `prepare(model=listed_local, json.model=cloud_model)` can approve an unfiltered cloud-bound body.

   **Fix:** specify separate non-model destination handling; update both legacy adapters in M7a; reject cloud-hosted Ollama models as local; bind the checked model and effective locality into the prepared token/body contract.

2. **High — D2: “strongest class” is not a valid ordering for independent privacy permissions.**  
   The requested learner-note trace **works**: local input `derived_from_learner(A)` → copied assessment retains A → later cloud preparation refuses it when A’s `cloud.text` is off.

   The new failure is mixed input: local generation receives a parent note while `CLOUD_PARENT_TEXT=false`, plus learner-derived text whose source permits cloud use. D2 joins them to `derived_from_learner`. The existing [`_gate`](/E:/GitHub/scil/Leafi/leafi/privacy/egress.py:576) then checks learner permission and never checks the parent restriction. I confirmed this with isolated execution of that gate.

   **Fix:** preserve the conjunction of applicable restrictions, including parent origin and all learner sources. Changing the class ordering cannot solve this: either ordering loses one independently configurable permission. Also clarify whether raw learner input produces class `learner` or `derived_from_learner`; the current formula and explanation disagree, although both currently receive learner gating.

3. **High — D7: preserve the atomic version-check/reservation transaction.**  
   [D7](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-23-m7-brain-design.md:63) describes version checks, then affordability, then the reservation transaction. Existing `admit` deliberately checks database versions **inside** each retried `BEGIN IMMEDIATE`.

   Hand trace: check versions → reservation encounters busy → another process changes privacy → retry succeeds. If the earlier check is reused, a request filtered under obsolete permission is admitted. Affordability can likewise become obsolete if a shared budget changes during the wait.

   **Fix:** recheck versions and affordability inside every successful reservation transaction; commit; then perform exactly one synchronous, non-awaiting charge.

   Charging once after a busy retry is sound. Cancellation after commit but before `_transmit` finishes DNS resolution charges a reservation despite zero transmitted bytes. That is conservative accounting, but D7 must call it **reservation accounting**, distinguish it in audit semantics, and acknowledge the difference from ADR-0017’s “charged what it sent” wording.

4. **Medium — D8/D10/O1: timeout and failure handling truncate the configured cascade.**  
   Under O1, the route begins `fast → standard → deep`. If `fast` times out, neither later tier is “not slower”; D8 stops. Standard is never attempted, even if sufficient moment time remains. Likewise, `failed` exhausts only the current tier and stops, unlike ADR-0017’s loop over subsequent eligible tiers.

   This is more than choosing a faster fallback: it changes availability policy. A fast-provider outage can disable Brain sequencing despite working stronger backends.

   **Fix:** define fallback by outcome explicitly. Prefer faster backends after timeout, but permit another eligible backend/tier when its measured minimum fits; otherwise document the intentional early stop as an ADR change. Bound reset cleanup by the remaining moment too: its independent 0.5-second allowance can consume the output reserve after a deadline.

5. **High — D12: an unscoped parked answer can answer the wrong question or obstruct controls.**  
   [D12](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-23-m7-brain-design.md:79) says the next `listen` receives the parked utterance.

   Hand trace: the learner answers item A → `judge` runs → the learner adds or corrects an answer → `controls_only` parks it → activity advances to item B → B’s `listen` immediately receives A’s utterance. Nothing associates the parked input with the question, item or turn that produced it.

   A full one-slot queue also needs defined behaviour. Blocking the reader on a second ordinary utterance prevents it reaching a subsequent `/stop`; overwriting silently loses an answer. Finally, requesting the main reader only in **text mode** does not make spoken “stop” work when the main source is the voice listener and the control source is a console.

   **Fix:** associate parked input with its interaction/epoch, define stale-input and overflow handling, and keep control recognition progressing independently. Specify the voice-reader policy consistently with half-duplex listening. Test an answer followed by `/stop`, multiple ordinary inputs, and an item transition during `judge`.

6. **High — D17: the fold is not total, and surviving card evidence can become ineffective.**  
   [D17](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-23-m7-brain-design.md:114) has conflicting rules:

   - `ignore → unignore`, with no retrieval/card evidence, should return to `new`; the unconditional “Anki mode without a card yet: learning” instead produces `learning`.
   - First `card_ack` must produce `learning`, but the next instruction reads the “latest `card_state`”, which may not exist yet.
   - Forgetting the only evidentiary session should produce `new`; the same Anki-mode branch again produces `learning`.
   - If that session held `card_ack`, but a later sessionless `card_state` survives, the fold ignores that state because it requires a surviving acknowledgement. The item can stop following a card that still exists.

   There is also no specified writer for `unignore`, despite the event and tests.

   **Fix:** give empty history an explicit first rule; define acknowledgement-without-state; define card membership independently of disposable session observations; expose an actual unignore operation. Hand-test the complete ignore/unignore/card/forget sequence in both mastery modes, including surviving external observations.

7. **Medium — D17: Anki observation and migration leave evidence gaps.**  
   `World.refresh` reads only due cards, capped at 20. A card reviewed successfully in Anki becomes non-due and can disappear from this query before Leafi observes its new interval. Thus “reviews done in Anki itself are seen” is not generally true.

   Migration 7 also creates an empty event table without specifying evidence for existing acknowledged cards. Those cards will not receive a *first* acknowledgement again. Merely keeping existing rows does not make their status reconstructible.

   The interval conversion has a literal error: negative `ivl` represents a positive duration in seconds, so days should be `-ivl / 86400`, not `ivl / 86400`.

   **Fix:** define refresh coverage for tracked cards beyond the due queue; specify migration/backfill or an explicit conservative reconciliation policy; correct the sign. Test pre-existing acknowledged cards and a review performed outside Leafi that makes a card non-due.

8. **High — D19: rewriting JSONL files races an active session’s append.**  
   [D19](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-23-m7-brain-design.md:130) correctly deletes by source learner, but lacks ADR-0018’s derived-write fence.

   Hand trace: learner B’s session has an observation containing A’s note. `forget --learner A` scans and rewrites B’s file. B then appends its already-built line containing A. A’s own-session exclusion does not block B. Deletion reports completion while A’s text survives. A read/rewrite can also lose unrelated concurrent appends.

   **Fix:** serialize append, rewrite and prune across processes, and check every source’s existence/`forgetting` state within that same serialization boundary before appending. Include an atomic replacement/recovery policy and final source rescan, or use transactional storage for the replay records. Test both “append just before rewrite” and “append after source deletion”.

9. **Medium — O1/O2: owner authorization is clear, but governing-document changes are incomplete.**  
   **O1 is acknowledged**, not hidden: revision 2 explicitly says Haiku-first replaces ADR-0017’s default. ADR-0017 already allows route overrides, so the owner’s choice does not itself violate privacy policy. Deferring the corresponding ADR note until M10 nevertheless leaves the implemented default undocumented during M7–M9.

   **O2 acknowledges the `security.md` exception but omits ADR-0018 §4.3**, which expressly retains evaluation transcripts as opt-in. These replay observations can contain the same learner text before filtering. Calling the store a replay set does not resolve that policy relationship.

   **Fix:** record O1’s temporary default in M7a. Amend ADR-0018’s retention table and `security.md` together when O2 lands, explicitly distinguishing default-on decision records from opt-in transcripts. No renewed owner approval is needed for the choices already recorded.

10. **High — M7a/D2/D5/D9: the compatibility bridge is incomplete.**  
    Retaining `.run()` alone does not preserve existing callers. M7a removes `BRAIN_DEADLINE_S` while both legacy backend constructors still read `settings.brain_deadline_s`; it retires model settings while legacy Claude reads `study_brain_model`; D1 changes their `prepare` calls; D2 changes the existing `Text(value, class, sources)` constructor.

    Moving `Provenance` into `core.text` also introduces a circular-import hazard: [`core.text`](/E:/GitHub/scil/Leafi/leafi/core/text.py:16) already imports `Utterance` and `Word` from `ports`, which would now re-export `Provenance` from `text`.

    **Fix:** enumerate the compatibility surface in M7a: legacy configuration, constructors, `Text` callers and backend calls. Retain compatibility properties until M7e or migrate those users atomically. Place shared provenance types where the import graph remains acyclic.

11. **High — M7b–M7d: handlers, facts and settings still have no complete landing sequence.**  
    Handler gating prevents the original missing-quiz crash; that part is sound. But [`World.facts()`](/E:/GitHub/scil/Leafi/leafi/study/harness/world.py:63) still leaves `new_item_candidates` and `recall_due` empty. Revision 2 never explicitly assigns their population. M7c’s handler list also omits `recall_items`.

    Mastery settings and `limits.extract_calls` are referenced by the design but absent from the current settings specification. The existing validator rejects unknown keys. Finally, changing `Session.generate` to `s.brain` in M7a precedes migration of its consumers in `menu` and `construct`.

    **Fix:** assign the Session compatibility transition, facts queries, recall handler and saveable settings to named commits. Gate each feature on all its prerequisites. Add a real harness test demonstrating that teaching and recall become available and execute; synthetic `Facts` fixtures alone can conceal disconnected features.

12. **Low — D6/T23: stable schema bytes do not specify prompt caching.**  
    Revision 2 discusses schema compilation caching and constant prompt components, but omits the stable-first observation ordering and explicit prompt-cache breakpoint requested in round one. A changing session section can still precede otherwise reusable material.

    **Fix:** name one rendering order and one cache-control placement, and test the rendered request. Keep schema-compilation reuse and prompt-prefix caching separate in the explanation.

13. **Medium — M7 acceptance: some Confirmation obligations still lack explicit checks or prerequisites.**  
    ADR-0017’s Brain-call cancellation requirement includes **deadline expiry**, whereas M7b specifically names stop/retry cancellation. M7c names answer-score tests without explicitly carrying forward the negative-sentence and low-confidence quiz/no-encounter cases. M7a’s schema tests check transformation/body equivalence but do not explicitly test rejection by local validation of constraints stripped from the API schema.

    The Ollama memory/latency measurement remains required by D9 and ADR-0018, but has no assigned owner-present step or explicit deferral; “Ollama on the port” does not supply that measurement.

    **Fix:** assign these cases explicitly. Move the `security.md` egress-policy update to the commit that first enables expanded Brain payloads, rather than leaving it until M7e. The documented M9 magpie and M10 camera/console deferrals are otherwise clear.

14. **Low — D6/D12/T24 and D19: resolve remaining contract ambiguities.**  
    D6’s strict envelope still requires `epoch`; D12 specifies `turn`. Several mechanisms marked beyond the ADR still lack the promised individual provenance annotation. Also, pruning only at session start does not enforce a strict 30-day retention ceiling when no later session starts.

    **Fix:** use one wire field consistently; finish the mechanism annotations; either define retention as cleanup on next use or assign pruning independently of new study sessions.

D14’s requested `Reobserve` trace is **sound as specified**: content cached under epoch E1 must be discarded after E2; a replacement may generate only within the original boundary deadline. Exclusions and offer counts survive. A same-epoch silence re-ask should reuse the constructed offer without another generation charge. Tests should lock down these distinctions, including reuse after the generation allowance is spent.

The five commits are therefore not yet independently demonstrable as green:

| Step | Assessment |
|---|---|
| **M7a** | Blocked by compatibility and admission/provenance issues above. |
| **M7b** | Handler gating fixes the original crash; input handling and Session integration remain incomplete. |
| **M7c** | Coordinated async conversion is sound; recall and facts dependencies need assignment. |
| **M7d** | Evidence-table direction is sound; fold, backfill and complete deletion semantics need correction. |
| **M7e** | Helper relocation is sound; replay concurrency and policy changes must be resolved before capture is enabled. |

The strongest improvements are codes-only rejection feedback, per-leaf filtering, independent record validation, scoped references, conservative quiz scoring, filler cleanup, explicit policy-setting protections, and the move toward evidence-derived status.

No files were edited. Verification comprised source inspection, hand execution of the requested traces, and an isolated in-memory `_gate` probe; no full pytest suite or live model calls were run.
