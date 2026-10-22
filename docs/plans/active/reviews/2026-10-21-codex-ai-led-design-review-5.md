# Codex design review 5: ADR-0017 / ADR-0018

Reviewer: codex-cli 0.155.0, model gpt-6-astra, reasoning high, read-only sandbox, 2026-10-21. Prompt: [prompts/ai-led-design-round-5.md](prompts/ai-led-design-round-5.md). Tally: R5 = recognised identity downgraded to unknown, correction-lineage replay (second round on the same decision), skip during construction, closing speech after lease release, identity transition, guest counts. Structural move after R5: the correction-lineage replay is dropped; forget unlinks a learner's corrections and keeps their spans local-only.

**Two High findings remain:** audio containing a recognized identity can take the `unknown` consent path, and forgetting A still lacks a valid correction-replay operation when B has edited A’s descendant revision.

“Resolved” means resolved in the design, not verified in implementation. No files were edited or tests run. I treated the owner’s decisions, routing policy, and magpie trust assumption as settled.

**1. Round-4 findings**

| Round-4 finding | Status |
|---|---|
| 1. Freshness after asynchronous construction | **Resolved** — `settle()` checks the epoch after construction, including named-choice and refusal generation, before returning `Run`. |
| 2. Audio classified from expected words | **Partly resolved** — failed ASR now produces `unknown`; recognized protected words in the actual recording still lack a refusal rule that takes precedence over uncertainty. |
| 3. Unaffordable preferred tier blocks fallback | **Resolved** — unaffordable tiers are skipped; reservation failure leaves that tier instead of ending the chain. |
| 4. Refusal repeats the announced alternative | **Resolved** — proposal candidates and the default now exclude the selected activity’s kind. |
| 5. Terminal cleanup during identification | **Resolved** — the session already owns a guest, and local finalization precedes optional delivery with checkpoints disabled; delivery introduces a separate lease problem below. |
| 6. Forgetting correction lineage | **Partly resolved** — historical deletion is explicitly permitted, but choosing the replay base, rebasing B’s correction, and handling surviving revision references remain incomplete. |
| Recurring: control consumption versus epoch invalidation | **Partly resolved** — listening-time skip is consumed before freshness checking; skip arriving during `settle()` can still escape into an activity. |
| Recurring: two meanings of “verified correction” | **Resolved** — `parent_approved_at` and `spans_verified` are explicitly distinct. |
| Recurring: invariants exceed executable transitions | **Partly resolved** — freshness now follows from the branches; control consumption, media classification and correction deletion still have uncovered transitions. |

**2. Hand-execution and defects**

The requested paths behave as follows:

| Scenario | Execution |
|---|---|
| Page turn during generation inside a named choice | Listen returns `quiz` → `settle()` awaits generation → page turn changes epoch → construction finishes, possibly falling through to `END` → checkpoint → epoch mismatch → `Reobserve`. No stale activity or accidental end executes. |
| “No” to an announced alternative | Primary rejected → alternative `read_aloud` announced → “no” → refusal removes every `read_aloud` proposal and excludes it from the default menu → another constructible kind or `end`. |
| 0.5 budget units left | Normal route `standard → deep → fast`: skip costs 1 and 3 → reserve 0.25 for an eligible fast backend → call. A successful call leaves 0.25. Deadline and failure handling still apply. |
| `/stop` during identification | Guest G already owns the session → confirmation await reaches checkpoint → `Terminal` → local finalization with no activity/book required → guest cleanup → optional delivery. The former tentative-owner failure is repaired. |
| Guest confirms learner L | The stated transition transfers the session and its rows G→L and deletes G. Its implementation must also reconcile provenance and in-memory identity, discussed below. |
| Forget A: rev1 book, rev2 A, rev3 A, rev4 B | Revisions 2–4 must disappear, but rev4 also satisfies “last revision no A-correction created.” Even choosing rev1 instead does not define how to replay B’s revision-3 coordinates or preserve dependent evidence. |
| Failed ASR on an ordinary practice target | Empty/gapped ASR now yields warned `unknown`. However, a recognized protected name **plus** a gap also satisfies that rule, exposing finding 1. |

1. **High — Recognized identity can be downgraded to uncertainty.**  
   [ADR-0018 §4](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:77)

   Expected word: *through*. Actual attempt: “Mia … [unclear speech].” Local ASR confidently recognizes the household learner’s name but cannot transcribe the remainder.

   The written rules produce:

   - Expected words contain no protected term, so the explicit `unmaskable` condition does not fire.
   - The uncertain stretch makes the clip `unknown`.
   - A warned confirmation permits transmission of the entire clip, including the **already recognized name**.

   There is also no specified outcome for a fully transcribed segment containing a protected term absent from the expected text: it cannot be `clean`, but neither remaining audio condition applies.

   Actual protected-content detection needs an explicit refusal or verified masking outcome, with precedence over `unknown`. Uncertainty elsewhere must not override known identifying content.

2. **High — Correction deletion is still not an executable reconstruction operation.**  
   [ADR-0018 §3](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:67), [ADR-0010 correction coordinates](/E:/GitHub/scil/Leafi/docs/adr/0010-page-text-revisions-and-auditable-corrections.md:25)

   Use this chain:

   - rev1: `The cat sat.`
   - rev2, A: prepend `My secret. `
   - rev3, A: change that prefix to `My diary. `
   - rev4, B: change `cat` to `dog`.

   Rev4 was created by B, but still contains A’s prefix. Thus “last revision no A-correction created” can select a contaminated revision that the preceding deletion rule also deletes. The base must precede the **earliest removed correction**, rather than merely have another author.

   Even with rev1 selected, B’s correction addresses `[14,17)` in rev3; its intended target is `[4,7)` in rev1. “New edit maps” does not specify this rebase. If B instead edited text introduced by A, the target has no surviving counterpart at all; a conflict outcome is required.

   Finally, invalidating a miscue does not remove its reference to the deleted revision or its copied `expected` text. The [existing schema](/E:/GitHub/scil/Leafi/leafi/core/storage.py:62) requires that revision reference; surviving B utterances and corrections can reference deleted revisions too. The transaction can therefore fail on foreign keys, or an improvised migration can preserve A’s text or falsify historical coordinates.

   Specify the surviving ancestor, rebase/conflict rules, and deletion or redaction of every dependent reference and text copy. Atomicity alone cannot define those operations.

3. **Medium — A skip during construction is not consumed by the negotiation that owns it.**  
   [ADR-0017 §§1, 2.1](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:60)

   The learner chooses `quiz`. While `settle()` awaits generation, the console posts skip. Under §1, this skip belongs to negotiation and does **not** change the epoch.

   Construction completes → checkpoint sees no terminal → epoch matches → `Run(quiz)` returns. `settle()` never calls `take_skip`. The quiz can start with the old negotiation’s skip still queued, causing immediate activity cancellation or rejection of a later interaction.

   Every construction return needs a control-consumption decision as well as terminal and freshness checks. The repaired listening branch does not cover this await.

4. **Medium — Closing speech happens after speech ownership is released.**  
   [ADR-0017 §2](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:51)

   Session A finalizes and releases its speech lease. Session B acquires that lease and begins speaking. A then enters `deliver()` and speaks its closing line.

   Either A speaks without ownership, violating the single-speaker rule, or lease enforcement rejects its closing speech. The design specifies neither reacquisition nor a lease-aware omission.

   Keep speech ownership through optional closing playback with unconditional release afterward, or make delivery explicitly acquire ownership and skip playback when unavailable. Delivery after `lease_lost` needs the same rule.

**3. What will keep going wrong in implementation**

- **Medium — Learner ownership and text provenance require one identity-transition contract.**  
  [ADR-0018 §§1, 3](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:22). If identification utterances are retained with `source_learners={G}`, transferring their session to L and deleting G leaves a nonexistent source. Send-time filtering then permanently removes those texts even when L permits them. Define whether identification text is discarded or its provenance is transferred, and commit persistent ownership, confirmation state and the epoch transition together.

- **Medium — Guest cleanup still needs a concrete home for retained counts.**  
  [ADR-0018 §1](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:16), [ADR-0017 §2](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:51). `/stop` before confirmation must delete G and G’s session rows while retaining counts. Keeping the existing session summary leaves a row requiring a non-null learner; deleting the session removes that summary. Specify a detached counts record or another explicit ownership exception. Guest delivery must also enforce the stated “no export” rule.

- **Medium — Tests need to cover interacting conditions, not only individual safeguards.**  
  The listed cases test page-turn freshness, uncertain audio and source deletion separately. The failures above require **skip during generation**, **recognized name plus uncertain speech**, and **B’s surviving correction/evidence on A’s deleted revision chain**. For deletion, assert both referential integrity and absence of A’s text in retained fields; checking only current page text or miscue status will miss the defect.
