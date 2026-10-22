# Codex design review 4: ADR-0017 / ADR-0018

Reviewer: codex-cli 0.155.0, model gpt-6-astra, reasoning high, read-only sandbox, 2026-10-21. Prompt: [prompts/ai-led-design-round-4.md](prompts/ai-led-design-round-4.md). Tally: R4 = freshness after construction, audio identity from expected text, tier affordability, refusal of the alternative, terminal-safe wrap, correction lineage on forget; the structural restatements of R3 held (egress mediation, routing, deadline resolved).

I found **two High findings**: negotiation still has unchecked construction paths, and uncertain audio can be classified as clean from the expected text alone. The revisions otherwise close several substantial round-3 gaps.

“Resolved” below means resolved in the design, not verified in code. No files were changed or tests run.

1. Round-3 findings

| Numbered defect | Status |
|---|---|
| 1. Stale negotiation and incomplete fallback | **Partly resolved** — `END` makes construction total and `Reobserve` handles changes during listening, but construction inside return expressions can await generation after the last epoch check (§2.1). |
| 2. Connection grants versus request authorization | **Resolved** — egress owns clients and pools, mediates each request, disables client retries, guards loopback magpie, and expires copied grants (ADR-0018 §2). |
| 3. Incomplete routing and unanswered questions | **Resolved** — full tier chains, degraded answers and explicit exhaustion outcomes are specified; a separate budget interaction remains below (§§5–5.1). |
| 4. Repeated skip and overwritten terminal controls | **Partly resolved** — the monotonic terminal latch fixes `/stop` followed by skip; queue consumption is explicit, but the retained skip-induced epoch change can defer that skip into the next negotiation (§§1–2.1; ADR-0013 Async guard). |
| 5. False mastery from merely mentioning an item | **Resolved** — `item_used` requires a correctness judgement; unavailable results write no retrieval event (§3.1). |
| 6. Identification and guest lifecycle | **Partly resolved** — identification is inside the session, prompts are local and bounded, and guest recovery exists; terminal cleanup before learner confirmation remains unspecified (§2; ADR-0018 §1). |
| 7. Egress log becomes an uncontrolled media store | **Resolved** — the log stores metadata and hashes, not attachment bodies (ADR-0018 §2). |

| “Problems that will keep recurring” bullet | Status |
|---|---|
| Deadline enforcement outside activities | **Resolved for active execution** — Brain calls and negotiation share the absolute session deadline; terminal cleanup needs a distinct contract, described below (§§1–2, 5). |
| Failed recognition classified as identity-free media | **Partly resolved** — unreadable images become warned `unknown`, and the protected vocabulary is unified; audio still derives `clean` from expected words rather than actual contents (ADR-0018 §4). |
| Unrestricted correction declassification | **Resolved** — an unverified correction retains its source learner; only parent verification makes it source-free book text (ADR-0018 §3). |
| Ownership versus source-based deletion | **Partly resolved** — B’s A-sourced notes and payloads are deleted and missing sources fail closed; correction rollback and retained correction history remain incomplete (ADR-0018 §3). |

2. Remaining defects and new interactions introduced by the revision

1. **High — The new `Reobserve` result is still missing after asynchronous construction.**  
   [ADR-0017 §§2.1, 3.3](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:55)

   Hand-execute the learner-chosen quiz:

   - Construct reading on page A; ask; receive `quiz`.
   - `checkpoint` passes and the epoch still matches.
   - The named-choice return calls `first_constructible(...)`; generating questions awaits the Brain.
   - The learner turns to page B.
   - There is **no subsequent epoch check before returning `Run(...)`**.

   If construction correctly rejects the generated questions and the old `act`, the final `END` constructs successfully. The session then **ends instead of reobserving**. If construction accepts stale content, execution violates §1 instead.

   The refusal branch and final queued-skip branch have the same unchecked construction return. Initial construction also precedes the first freshness check, so generation can invalidate the epoch before the announcement is spoken.

   Construction must finish before a common terminal/freshness check; stale construction needs to produce `Reobserve`, rather than becoming an ordinary rejection that falls through to `END`.

2. **High — The new audio preparation rule mistakes expected content for evidence about recorded content.**  
   [ADR-0018 §4](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:74)

   Suppose a practice target is *through*, but the learner says their name during the attempt and local ASR fails. The expected page word contains no protected term, so the specified audio rule labels the clip `clean` and asks the ordinary consent question without the uncertainty warning.

   Cutting audio to an expected-word interval does not establish what was spoken there. With empty ASR, the timestamps needed to establish that interval may themselves be unavailable. Forced alignment cannot prove that the learner said the expected word.

   This is a new mechanism for the recurring recognition failure: an uncertain recording bypasses the `unknown` outcome. Preparation needs evidence about the actual segment; otherwise it must return `unknown` with the warned-consent path, or refuse preparation where the “never free speech” restriction cannot be established.

3. **Medium — An unaffordable preferred tier prevents an affordable fallback.**  
   [ADR-0017 §§5–5.1](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:150)

   With **0.5 units remaining**, a normal generation call routes `standard → deep → fast`. Standard costs 1, so `reserve_brain_call(standard)` fails and the function immediately returns `None`. Fast costs 0.25 and is eligible, but is never attempted.

   Consequently, `allowed()` can advertise a quiz because budget remains and generation is routable, while construction rejects it despite an affordable backend. The full fallback chain needs to skip an unaffordable tier, or explicitly define affordability as part of eligibility. Deadline exhaustion and reservation failure cannot share this unconditional whole-chain return.

4. **Medium — Refusal can select the exact activity just refused.**  
   [ADR-0017 §2.1](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:57)

   Let the Brain’s primary proposal fail construction and its alternative, `read_aloud`, succeed. Negotiation correctly announces `read_aloud`. The learner says “no.”

   The refusal branch tries `prop.alternative` first—**the same `read_aloud` just refused**—and immediately runs it. Only the default’s menu excludes `act.kind`; the alternative is unaffected.

   This consumes skip once mechanically but does not implement the refusal. The fallback needs to exclude the selected/refused activity, including when that activity originally came from the alternative.

5. **Medium — Moving identification inside the session exposes an undefined terminal-cleanup state.**  
   [ADR-0017 §§1–2](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:20), [ADR-0018 §1](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:16)

   `/stop` during the first identity confirmation now correctly raises `Terminal`. But `wrap(s)` receives `learner=TENTATIVE`, possibly without a book, while persistent sessions require a non-null learner. There is no specified tentative-session wrap outcome.

   More generally, wrap runs outside the `try`, with the terminal latch still set. Any summary playback or other awaited wrap operation encounters the rule that every await is followed by `checkpoint`, which raises again. At the deadline, it also has no remaining wait budget. Guest deletion is specified **after** parent export, so an interrupted export can prevent normal cleanup.

   Define terminal-safe local finalization separately from optional summary/export delivery, including the no-confirmed-learner case. Startup recovery helps after a crash; it does not define successful normal termination.

6. **Medium — “Revert to the previous revision” is not a complete source-deletion operation.**  
   [ADR-0018 §3](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:67), [data-model revision and correction lifecycle](/E:/GitHub/scil/Leafi/docs/architecture/data-model.md:9)

   Let revision 1 contain book text, revision 2 contain A’s unverified personal correction, and revision 3 contain another unverified correction by A to the same span. Forgetting A and restoring revision 3’s previous text restores **A’s revision-2 text**.

   Furthermore, appending a restoring revision leaves A’s words in immutable historical revisions and `corrections.new_text`; overwriting or deleting those records conflicts with the retained append-only rules unless an explicit deletion exception is defined. Lexicon rebuilding can also encounter those historical correction texts.

   Missing-source filtering prevents a straightforward subsequent cloud disclosure if provenance survives, but it does not complete deletion. Specify lineage-aware removal/restoration, treatment of historical copies, and the corresponding edit-map, reading-state and miscue invalidation transaction.

The requested hand-executions give these additional results:

| Path or scenario | Result |
|---|---|
| **No Brain at all** | Empty eligible chains return `None`; generated activities and Q&A disappear. Defaults can review, practise, add cards with stored text, or read. `page: next` acquires before resolving ranges. No new failure in this path. |
| **Identification inside the session** | Confirmed guesses/names return an enrolled learner; two failed attempts produce a guest. Prompts are local and bounded. Stop now reaches wrap; its tentative-state issue is finding 5. |
| **Autonomy ≥8** | Announcement → checkpoint → epoch check → queued-skip construction or `Run(act)`. The ordinary return is guarded; initial generation and skip-triggered construction have finding 1’s gaps. |
| **Silence or yes at lower autonomy** | Break from the listening loop → final checkpoint and epoch check → `Run(act)`, absent a queued skip. This path is guarded. |
| **Skip or no** | Construct alternative/default/end and return directly. Construction is total, but freshness and refusal semantics have findings 1 and 4. |
| **Available named choice** | Construct learner choice/old activity/end and return directly. Generation can change the epoch after its last check. |
| **Two unavailable named choices** | Explain each rejection, then pass through the final checks and return the original activity. |
| **Epoch changes while asking/listening** | The next explicit epoch check returns `Reobserve`; `run_session` recomputes menu and observation. |
| **`/stop`, then spoken skip before checkpoint** | Under the monotonic-latch rule, stop remains terminal; checkpoint raises before skip can select another activity. |
| **29:58, decide call, autonomy 2, 30-minute limit** | The call gets at most two seconds. If it consumes those seconds, checkpoint raises before negotiation. If it returns earlier, negotiation receives only the remaining time, then terminates at the deadline. Wrap remains finding 5. |
| **Full route chain, only fast configured, high-difficulty answer** | Empty preferred/escalation tiers are skipped; fast answers as `degraded`, with the specified preface. Exhaustion produces the grown-up-later response. Finding 3 concerns affordability, not absent tiers. |
| **Pooled egress client** | Each new request enters `egress.send` and repeats filtering, logging and consent checks. Pool reuse no longer bypasses mediation. |
| **Copied grant in a thread past its deadline** | A fresh connection is refused. Already-established I/O is not cancelled by a connect guard; a timed-out delivery must remain potentially delivered/`unknown`, with media consent consumed. |
| **A’s unverified correction read by B** | A remains a source. If A has cloud text off, the span is masked regardless of B’s setting. Parent verification is the explicit declassification boundary. |
| **Unreadable photo** | Insufficient OCR → `unknown` → warning included in consent question → one bound, consumed attempt. This path is now explicit. |
| **Practice clip** | Protected expected word → `unmaskable` and refusal; other expected words → `clean`, even when actual speech is uncertain—the failure in finding 2. |
| **Forget A while B holds a note quoting A** | B’s A-sourced note and corresponding A-sourced Brain payloads are explicitly deleted. Correction-history handling remains finding 6. |

3. Issues likely to recur during implementation

- **Medium — Control consumption and epoch invalidation need one ordering contract.**  
  [ADR-0017 §§1–2.1](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:19) retains [ADR-0013’s Async guard](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md), where skip increments `turn_id`. A skip while listening therefore causes `Reobserve` **before** `take_skip`; the queued event can subsequently reject a fresh proposal. Bind controls to the interaction they affect and settle consumption before deciding whether an epoch change requires restarting.

- **Medium — “Verified correction” now has two different meanings.**  
  [ADR-0018 §3](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:65) requires parent verification for declassification, whereas the [data model](/E:/GitHub/scil/Leafi/docs/architecture/data-model.md:9) marks each applied correction’s span verified against later OCR. Reusing `spans_verified` for privacy approval would immediately recreate the A-to-B leak. These must be distinct states.

- **Medium — Invariants and promised tests still exceed the executable transitions.**  
  [ADR-0017 §2.1 and Confirmation](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:80) promise that every return is current and that generation-time page turns produce `Reobserve`, but the displayed branches do not establish either. Verification should inject changes at each await and exercise each return branch, including fallback construction; happy-path tests of the invariant’s wording will miss the remaining failures.
