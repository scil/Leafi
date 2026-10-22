# Codex design review 3: ADR-0017 / ADR-0018

Reviewer: codex-cli 0.155.0, model gpt-6-astra, reasoning high, read-only sandbox, 2026-10-21. Prompt: [prompts/ai-led-design-round-3.md](prompts/ai-led-design-round-3.md). Tally: R1 ownership, terminal states, budgets, egress boundary; R2 totality, egress below SDKs, consent order, provenance owner; R3 stale negotiation, connection-level grants vs requests, deadlines outside activities, media identity check, route exhaustion. R2 and R3 rhyme on two shapes, so R4 restates both structurally (restartable negotiation with one absolute deadline; request-level mediation owning every client, socket guard as backstop).

The revisions repair several concrete failures, but the design still has blocking gaps in negotiation and egress enforcement. I treated the owner’s decisions and routing requirement as settled. No files were changed or tests run.

**1. Round-2 findings**

“Resolved” means resolved in the design, not verified in an implementation.

| Round-2 numbered defect | Status |
|---|---|
| 1. Construction and negotiation not total | **Partly resolved** — acquisition and the initial fallback chain work; the named-choice branch can still exhaust both candidates without returning an Activity after a state change (§2.1). |
| 2. Terminal controls swallowed | **Partly resolved** — both requested `stop` cases now terminate; the new `skip` latch has no consumption operation in negotiation, and terminal precedence between latch writers is unspecified (§§1–2.1). |
| 3. One-page continuation and activity-limit conflict | **Resolved** — continuation repeats for every turn and does not consume the boundary-activity allowance (§§2, 8.2). |
| 4. Hard deadline not enforced | **Partly resolved** — activity waits are bounded and `time_up_cycle` is removed; Brain calls and negotiation outside activities can still exceed the session deadline (§§2.1, 3.1, 5). |
| 5. Forbidden identity allowed in media | **Partly resolved** — known unmaskable identity now causes refusal; failed recognition and the narrower media masking vocabulary still lack a safe classification contract (ADR-0018 §4). |
| 6. Unsafe consent consumption ordering | **Resolved** — consumption and the attempt row commit before transmission; uncertain delivery remains consumed, and purpose is matched (ADR-0018 §4). |
| 7. Provenance loses source learner | **Partly resolved** — mixed-source notes now honor every source learner; applied corrections explicitly become source-free `page` text, leaving the original correction scenario open (ADR-0018 §3). |
| 8. Generated construction/scoring incomplete | **Partly resolved** — generation and stored-card eligibility are specified; `item_used` now accepts answers that mention the word without using or recalling it correctly (§§3.1–3.3). |

| Round-2 “Problems likely to recur” bullet | Status |
|---|---|
| Ownership of pre-activity calls and guests | **Partly resolved** — session ownership and log deletion are specified; pre-identification egress ownership and guest crash cleanup remain missing (ADR-0018 §1). |
| Difficulty eligibility versus weights | **Resolved** — policy-only outcomes are excluded from both weight and row existence (§8.6). |
| Competing speech rules | **Resolved** — recovery dialogue explicitly sits outside the interruption table (§6.1). |
| Dependency bypasses egress | **Partly resolved** — fresh unauthorized connections fail closed, but connection checks cannot mediate pooled requests, and loopback magpie remains an exception without an enforcement mechanism (ADR-0018 §2). |
| Magpie route-binding failure contract | **Resolved within the stated trust boundary** — honoring the explicit provider is now an explicit trust assumption, with an incident response for reported mismatch; it is not independently verified before delivery (ADR-0018 §2). |

**2. Hand-execution and new defects**

The requested scenarios produce these results:

| Scenario | Execution |
|---|---|
| **No Brain** | `brain_call` traverses empty eligible lists and returns `None`. Generated kinds and Q&A disappear. The default constructs reading with `page: next` without sentence IDs; acquisition resolves the range afterward. Existing candidates permit practice. This fixes the previous acquisition failure. |
| **Autonomy 2: “quiz” outside menu, then “stop”** | Construct default → ask → first listen returns `quiz` → explain unavailable → second listen sets `stop` → `checkpoint` raises `Terminal` → outer catch → wrap. The activity does not start. |
| **Autonomy 10: `/stop` during announcement** | Construct → announce while console sets latch → checkpoint raises → wrap. The requested termination path is repaired. |
| **A→B→C, three candidates from A** | A finishes `page_turned`; B and C run through the repeated continuation loop in the same cycle. A’s page-read states and candidates remain available for practice. Continuations do not exhaust the six-boundary limit. |
| **A cloud text off; B on; A’s note in B’s memory** | The note carries source A. Send-time filtering consults A’s setting and removes it, despite B’s setting. This path is repaired. |
| **High-difficulty question; only fast local tier configured** | Difficulty becomes high → route is `[deep]` → no eligible backend → `None`. The existing fast local model is never called. Q&A has no specified behavior for this result. |
| **Identification, including guest** | Accepted guess + yes returns that learner. Otherwise, either fallback attempt can confirm an enrolled learner or enroll a confirmed new name. Two failed attempts return an off-by-default guest. Normal wrap deletes guest rows; crash cleanup is unspecified. |
| **Grant through executor and SDK** | An explicitly copied context carries the host grant into that executor job. An SDK-created worker without that propagation fails closed on a fresh connection. An already-open SDK connection can transmit without another connect check. |
| **Crash between consume and send** | Consent is already `used`, with a durable attempt. Restart cannot reuse it because the conditional update requires `granted`. A new attempt requires another confirmation. This is safe against duplicate authorization. |

For **every negotiation return path**: initial construction has the final `end` fallback; autonomy ≥8 returns its constructed activity after a checkpoint; silence/yes returns the original activity; no/skip constructs an alternative/default/end; an available named choice tries `[learner_spec, act]`; two unavailable named choices return the original activity. The last three paths expose the defects below.

1. **High — The new named-choice fallback is still not total, and stale negotiation has no restart transition.**  
   [ADR-0017 §§2.1, 3.3](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:51)

   Construct reading on A, then listen. The learner chooses an available quiz; while `generate` runs, a page turn or correction changes the epoch. The generated work must be dropped under §1. The fallback `act` also belongs to the old epoch. Unlike the initial chain and refusal branch, `[learner_spec(...), act]` has no terminal fallback: `first_constructible` finds nothing, although the caller requires an Activity.

   Silence/yes and the final `return act` similarly return an activity constructed before listening. The epoch invariant correctly forbids using stale work, but there is no specified result that returns negotiation to fresh observation. Implementers must invent that transition or violate the invariant.

   There is also an action/announcement mismatch: when the proposed activity is rejected and an alternative/default succeeds, autonomy ≥4 still speaks `prop.say_before`.

2. **High — Socket grants authorize connections, not filtered requests or single consented attempts.**  
   [ADR-0018 §2](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:40), [netguard connection hooks](/E:/GitHub/scil/Leafi/leafi/core/netguard.py:44)

   An SDK opens a persistent connection under an authorized call. A subsequent call bypasses `egress.send` but reuses that connection. No connect or resolve occurs, so the guard neither checks the new payload nor writes an attempt. The existing Claude adapter retains its SDK client, making connection reuse a relevant implementation path.

   Three related gaps remain:

   - A direct connection to loopback magpie passes the general loopback exemption. Saying magpie “needs a grant” does not specify how the socket guard distinguishes that forwarding endpoint from ordinary loopback services.
   - A host grant permits multiple requests to that host. It cannot itself prevent an SDK from retrying a consented upload within one transport invocation.
   - A copied context can outlive the caller’s `with grant(host)` scope. If a timed-out executor job continues, leaving the original context does not revoke its copy; no expiry or revocation contract is specified.

   Request mediation must remain authoritative, with connection checks as an additional boundary. The current confirmation tests predominantly exercise fresh connections and miss these paths.

3. **Medium — Routing exposes unanswered questions and does not consistently implement the promised invalid-response escalation.**  
   [ADR-0017 §§3.2, 5–5.1](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:140)

   With only `fast` configured, a “why” question routes exclusively to empty `deep` and returns `None`. `routable(s, purpose="answer")` receives no question or difficulty, so its relationship to this actual route is undefined. The design needs an explicit outcome: unavailable feedback, configured fallback, or another defined transition.

   Separately, an invalid **normal `decide`** response executes `break`, but its default route contains only `standard`. There is no next tier. Thus “invalid → escalates one tier” in Confirmation is false for this default route.

   The routing request is sound; the missing pieces are route exhaustion and the distinction between a preferred tier and a complete fallback chain.

4. **Medium — The new latch can apply one skip twice, and can lose a terminal control unless writers enforce precedence.**  
   [ADR-0017 §§1, 2.1](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:20)

   The Listener parses “skip” and sets `s.control=skip`. Negotiation also receives `c=="skip"` and returns an alternative. Nothing clears the latch, so the alternative activity can consume the same skip again.

   A console skip during an announcement is worse: negotiation never inspects the latch, so it can return the original activity and leave that activity to interpret the skip.

   The latch is also a single writable value. `/stop` followed by a skip event before the next checkpoint can overwrite termination unless setting it preserves terminal precedence. Define one control-consumption operation and monotonic terminal latching.

5. **Medium — The revised teaching scorer produces false mastery evidence.**  
   [ADR-0017 §§3.1, 6.2](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:85)

   For `expect=item_used`, ask the learner to use *through* in a sentence. “I don’t know what through means” contains the lemma and therefore succeeds. Repeating this on two days can make an uncarded item `known`.

   The change fixes the previous false rejection of a valid sentence, but substitutes word presence for successful use. The scoring contract also lacks an explicit unavailable outcome for silence, skip, or inability to judge, despite writing durable retrieval evidence.

6. **Medium — The guest lifecycle does not cover identification, setup failure, or restart.**  
   [ADR-0017 §2](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:25), [ADR-0018 §1](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:24)

   `identify()` runs before `Session` exists; `identify_book()` runs before the `try`. Consequently, the new session latch and wrap cleanup do not cover those operations.

   Concrete consequences:

   - An identity prompt synthesized through cloud TTS needs an egress log with a non-null learner, before one has been selected.
   - `/stop` during identification has no specified terminal path.
   - A crash after creating the guest, or during its session, leaves guest rows behind. Startup recovery closes interrupted sessions but does not invoke guest deletion.
   - `confirm` has an eight-second timeout; the preceding `ask("Who is reading today?")` has none specified, so “silence twice → guest” is not executable without another timeout rule.

7. **Medium — Logging every payload creates a new persistent audio/image store without a retention contract.**  
   [ADR-0018 §2](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:44), [data-model retention](/E:/GitHub/scil/Leafi/docs/architecture/data-model.md)

   An audio clip approved for one remote attempt is written into `egress_log.payload bytes` before sending. It is therefore persisted even when `AUDIO_KEEP_CLIPS=false`. An image copied into the log also survives expiration of its original page-image file.

   Learner deletion eventually covers the log, but normal retention, failed attempts, and crash leftovers do not. Either store audit metadata instead of attachment bodies or explicitly amend retention for this new store.

**3. Problems that will keep recurring**

- **High — Deadline enforcement still stops at activity boundaries.**  
  [ADR-0017 §§2.1, 3.1, 5](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:77). At 29:59, a five-second decision call can cross the hard ceiling. Construction may then select `end`, but low-autonomy negotiation can still wait for answers before wrapping. Brain deadlines use `now + TOTAL_S`, and negotiation uses `ASK_S`; neither is capped by the session deadline. All blocking phases need the same absolute deadline and expiry transition.

- **High — Failed local recognition cannot silently mean “media contains no identity.”**  
  [ADR-0018 §4](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:70). ASR failure is a trigger for remote help, yet its transcript is also used to check identity. A clip saying the learner’s name can have an empty transcript. The preparation steps additionally name `household_terms`, while text pseudonymisation separately includes every enrolled learner’s name. A known learner omitted from the parent’s term list must still be protected. Preparation needs explicit clean/masked/unknown/unmaskable outcomes and the same protected-identity vocabulary as text filtering.

- **Medium — Correction reclassification remains an unrestricted declassification step.**  
  [ADR-0018 §3](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:63). A supplies personal text through a spoken correction while cloud text is off; the resulting revision becomes `page` with empty sources, and B can send it. Legitimate corrected book text may be exportable, but the design gives no condition distinguishing it from arbitrary learner text entered through that channel. This needs a bounded declassification rule or an explicit narrowing of the `cloud.text` guarantee.

- **Medium — Row ownership and source-subject ownership are different deletion problems.**  
  [ADR-0018 §§1, 3](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:16). If B owns a note containing A’s words, forgetting A does not delete B’s note or B’s previously logged payload. Its provenance can then reference a nonexistent learner whose current setting cannot be consulted. Shared corrections may also reference deleted utterances. Specify how deletion handles cross-source material and missing source learners; foreign keys and session ownership alone do not settle this.

The highest-value implementation checks are therefore state-changing negotiation, pooled SDK requests, executor work surviving cancellation, absent routing tiers, and guest recovery after crashes. These exercise the remaining design gaps more directly than additional happy-path session tests.
