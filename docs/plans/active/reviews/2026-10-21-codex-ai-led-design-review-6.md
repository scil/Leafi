# Codex design review 6 (confirming): ADR-0017 / ADR-0018

Reviewer: codex-cli 0.155.0, model gpt-6-astra, reasoning high, read-only sandbox, 2026-10-21. Prompt: [prompts/ai-led-design-round-6.md](prompts/ai-led-design-round-6.md). Result: no High; three local Medium findings, fixed in place after this round (refused_of defined before first use; a skip while refusing ends the choice at nd; clean audio needs confident full coverage).

**No High findings remain. Three Medium defects remain in the written transitions.** “Resolved” below means resolved in the design, not verified in implementation. No files were edited or tests run.

| Round-5 finding | Status |
|---|---|
| 1. Recognised identity downgraded to uncertainty | **Resolved** — protected recognised words now trigger `unmaskable` before uncertainty is considered. |
| 2. Correction deletion lacks executable reconstruction | **Resolved by the accepted policy change** — revisions remain; corrections are unlinked and unapproved spans remain local-only. Reconstruction is unnecessary. |
| 3. Skip during construction escapes negotiation | **Partly resolved** — construction now consumes skips, but initial construction calls an uninitialised helper, and nested refusal handling can reselect a refused activity. |
| 4. Closing speech after lease release | **Resolved** — delivery retains ownership, forbids closing playback after `lease_lost`, and releases the lease afterward in `finally`. |
| Recurring: identity-transition contract | **Resolved** — identification utterances are never stored; session ownership transfer, guest deletion and epoch advancement are transactional. |
| Recurring: retained guest counts | **Resolved** — the counts-only session survives under permanent learner `anonymous`; guest export and parent notification are prohibited. |
| Recurring: interacting-condition tests | **Resolved at the design level** — Confirmation now names skip injection across negotiation awaits, recognised-name-plus-uncertainty audio, and surviving B revisions with referential integrity. |

1. **Medium — Initial-construction skip calls `refused_of` before assignment.**  
   [ADR-0017 §2.1, lines 61–74](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:61)

   Hand-execution: `first = settle(...)` starts constructing a quiz → generation awaits → skip is queued → construction finishes → `checkpoint` passes → `take_skip` consumes it → `refusing` is false, so execution calls `refused_of(a)`.

   But `refused_of` is assigned only **after** `first` returns and the announcement runs. This path has no defined result; a direct Python transcription raises an unbound-closure error. Because `run_session` catches only `Terminal`, it also bypasses the shown finalization and lease-release path.

   Define `refused_of` before the first `settle` invocation.

2. **Medium — The nested refusal path forgets its refusal state and can restart the originally refused activity.**  
   [ADR-0017 §2.1, lines 64–75](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:64)

   With **one skip inside a refusal**, the requested trace succeeds: announce quiz → learner says “no” → `refused_of(quiz)` constructs teaching with `refusing=True` → skip arrives during generation → consume skip → `settle([END])` → no further skip → `Run(end)`, provided the epoch remains current.

   With **two skips queued during that same generation**, however:

   - The refusal construction consumes the first skip and calls `settle([END])`.
   - That call defaults back to `refusing=False`.
   - It constructs `END`, consumes the second skip, and calls `refused_of(END)`.
   - `refused_of(END)` excludes only `end` from the original proposals. The originally refused quiz is eligible again and can return as `Run(quiz)`.

   Both events are consumed, but the “refusal never re-selects the refused kind” invariant fails. Preserve the refusal state and excluded kinds through nested settlement; additional skips while selecting `END` must not reopen the proposal list.

3. **Medium — Complete but low-confidence ASR takes `clean` before reaching `unknown`.**  
   [ADR-0018 §4, ordered audio rules](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:81)

   Concrete scenario: local ASR returns words covering the whole practice segment, including a low-confidence guessed word. No recognised word matches `PROTECTED`. Local clarification fails.

   Preparation checks, in order:

   - Protected term: no.
   - “Local ASR produced words for the whole segment”: yes → **`clean`**.
   - “Any … low-confidence stretch”: never reached.

   The consent question therefore omits the uncertainty warning even though the recording satisfies the stated `unknown` condition. Require complete **and sufficiently confident** coverage for `clean`, or evaluate uncertainty before that branch while keeping recognised protected content first.

The other requested hand-executions pass under the revised contracts:

| Scenario | Hand-execution |
|---|---|
| **Finalize/deliver after `lease_lost`** | The terminal checkpoint exits execution; any running activity receives its terminal status. `finalize` performs local settlement and persistence with checkpoints disabled. `deliver` omits closing playback because ownership was lost; optional non-speech delivery remains best effort. `release_lease(s)` runs in `finally`. |
| **Recognised name plus unclear stretch** | Expected target is *through*; actual recognition includes household name *Mia* plus an unclear stretch. The first audio rule matches the recognised name → `unmaskable` → local refusal → return before destination selection, consent insertion or transmission. The unclear stretch cannot downgrade that result. |
| **Forget A: rev1 book, rev2 A, rev3 A, rev4 B** | Assume both A corrections are unapproved: rev1 `The cat sat.`; rev2 adds `My secret. `; rev3 changes that prefix to `My diary. `; rev4 changes `cat` to `dog`. Forgetting A retains all four revisions and their edit maps, clears A corrections’ `utterance_id`, marks their source `forgotten`, and deletes A-owned evidence plus the specified cross-source notes/assessments/payloads. A’s retained spans remain local-only, including the prefix inherited by rev4. B’s correction still addresses `[14,17)` in rev3; B’s surviving revision references remain valid. No rebase or reconstruction is needed. |

Low findings:

- None.
