# Codex design review 2: ADR-0017 / ADR-0018

Reviewer: codex-cli 0.155.0, model gpt-6-astra, reasoning high, read-only sandbox, 2026-10-21. Prompt: [prompts/ai-led-design-round-2.md](prompts/ai-led-design-round-2.md). Round tally: R1 = ownership, terminal states, budgets, egress boundary; R2 = totality of construction/negotiation and controls, egress below SDK transports, consent ordering, provenance owner.

**The revisions close several round-1 gaps, but the design is not yet executable as written.** The main blockers are construction failures, cancellation, continuation across page turns, and consent enforcement. I treated the owner’s decisions as settled. No files were changed or tests run.

**1. Round-1 findings**

“Resolved” here means resolved in the design, not verified in an implementation.

| # | Status |
|---|---|
| 1 | **Resolved** — ADR-0017 §§1, 8 now specify cycle ownership, retained page-read state, settlement, `/back`, and page turns during practice; the new continuation implementation has separate defects below. |
| 2 | **Partly resolved** — Brain-only defaults are removed and acquisition is introduced, but §3.3 rejects not-yet-acquired page ranges; `add_cards` eligibility still does not guarantee constructible card text. |
| 3 | **Partly resolved** — Activity terminal results and epoch checks exist, but §§2–2.1 still lose cancellation in negotiation and reuse an old menu after an epoch change. |
| 4 | **Partly resolved** — Cumulative budgets and call reservations are specified; §3.1 still waits until an unbounded step finishes, and §3.2 does not close an expired cycle. |
| 5 | **Resolved** — ADR-0018 §2 restricts questions to local backends when cloud text is off, removes the activity when none exists, and lifts Ollama’s deferral. |
| 6 | **Partly resolved** — ADR-0018 §§2–3 specify transport mediation, endpoint locality and local identity speech; the proposed HTTP-client construction test does not establish mediation of SDK-owned transports. |
| 7 | **Partly resolved** — ADR-0018 §3 adds provenance and send-time filtering, but provenance lacks the originating learner needed for shared or mixed-learner content. |
| 8 | **Partly resolved** — ADR-0018 §4 binds hashes, destinations and expiry and separates habit snapshots, but still permits unmaskable identity and leaves consumption versus network-send ordering unsafe. |
| 9 | **Partly resolved** — ADR-0018 §1 handles recognition ambiguity, modality conflict and tentative egress; fallback-name confirmation lacks negative/timeout outcomes, and guest persistence is undefined. |
| 10 | **Partly resolved** — ADR-0017 §3.3 strengthens validation, but §2.1 can return `None` or a `Decision` where the loop requires a runnable activity. |
| 11 | **Resolved** — ADR-0017 §5 defines a five-second total budget, normalized backend failures, validation-only retries, and adapter retries off. |
| 12 | **Resolved** — ADR-0017 §§7.2, 8.5 provide running activity records, per-step atomic effects and interrupted-cycle settlement; the requested partial-practice crash has a determinate outcome. |
| 13 | **Partly resolved** — ADR-0017 §8.6 defines encounter mappings and zero weights for policy omissions, but retains ADR-0013’s existence rule that still creates `watch` rows from those omissions. |
| 14 | **Resolved** — ADR-0017 §§2, 7.1 apply independently validated records before execution, include the previous activity ID, and record terminal decisions. |
| 15 | **Partly resolved** — ADR-0018 §1 fixes learner keys and resume queries, but pre-activity Brain calls, the new egress log, and guest records lack complete ownership/deletion contracts. |
| 16 | **Partly resolved** — ADR-0018 §2 requires explicit provider/model routes, but gives no refusal rule when a gateway cannot guarantee that route or reports a different effective provider. |
| 17 | **Resolved** — ADR-0017 §§6.2, 7.2 establish Anki precedence and durable retrieval evidence; the evidence-producing activity has a separate scoring defect below. |
| 18 | **Partly resolved** — ADR-0017 §6.1 defines silence behavior and supplied-word treatment, but its exclusive speech rules conflict with the retained Reposition prompt. |

**2. Hand-execution and defects in the revised rules**

| Requested scenario | Execution under the written rules |
|---|---|
| **No Brain** | `brain=False`; teaching, quiz and Q&A disappear. `brain_decide` returns `None`; the default selects reading, then practice when candidates exist. This works with an already acquired, nonempty range. At initial acquisition or `page: next`, §3.3 requires sentence IDs belonging to the current page read before §3.1 acquires the target page. Construction has no specified successful path, and negotiation does not handle `None`. |
| **Two timeouts** | With two eligible backends: reserve call 1 → timeout after at most 3 seconds; reserve call 2 → timeout within the roughly 2 seconds remaining; return `None` → default. Two calls are charged. One backend timing out gets no same-backend retry, intentionally. This trace is repaired. |
| **Page turn during `read_listen`, three candidates, learner keeps reading** | Finish the current sentence; retain the three candidates and their original page-read states; finish with `page_turned`; run one continuation on the new page in the same cycle. If that continuation completes, the three remain practisable. If it also returns `page_turned`, the loop checks only terminal status and then calls the Brain at the next iteration: continuous reading is no longer followed automatically. |
| **Autonomy 2, out-of-menu request** | Explain why unavailable and listen once more. Silence/yes/unrecognized input returns the original activity; an available named choice is constructed. But `stop` on that second listen also returns the original activity because the final expression recognizes only an available named choice. |
| **Autonomy 10, stop during negotiation** | `construct` → `say` → unconditional `return act, None`. There is no propagation of a stop received during `say`. The prose promises cancellation, but this branch does not implement it; dropping stale work alone would cause re-observation rather than termination. |
| **Cloud text off, Q&A, only Claude configured** | Claude remains eligible for filtered `decide` calls, but no backend is eligible for `answer`. `learner_questions` is absent. A Brain proposal for it fails menu validation; a learner request follows the unavailable-choice branch. No question is dispatched to Claude. |
| **Siblings within the margin** | Voice A=.87/B=.85 with margin .05 yields ambiguity. Without an accepted face match, ask who is reading; no profile-dependent egress yet. An accepted face match for B permits a tentative B guess, followed by confirmation. Fallback name selection says “confirm once,” but does not define what a negative or timed-out confirmation returns. |
| **Crash after practice settles one of three candidates** | The first candidate’s effects, activity progress and ledger update commit together. Recovery marks the running activity interrupted, closes the cycle and settles the remaining two `unsure(interrupted)`; the first candidate retains its settled result. Retained ADR-0013 recovery also settles their tokens. This trace is repaired. |

The following are concrete failures or new interactions in the revision.

1. **High — Construction and negotiation are not total.**  
   [ADR-0017 §§2.1, 3.3](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:55).

   A response can pass `check_shape` while containing a reversed sentence range. `construct` correctly returns `None`, but negotiation then describes or returns it, and `run_session` reads `act.kind`. The promised fallback “as shown” is absent. Separately, rejecting a proposal without a valid alternative returns `default_decision(...)` directly—a `Decision`, not an activity.

   Acquisition exposes the same failure even without a model: `page: next` cannot satisfy validation against the current page’s concrete sentence IDs. Define separate acquisition and resolved-range validation, and make every negotiation exit return either a validated activity or a control outcome.

2. **High — The new negotiation branches swallow terminal controls.**  
   [ADR-0017 §§2–2.1](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:49).

   Two deterministic examples are `/stop` during the autonomy-10 announcement and spoken `stop` during the autonomy-2 second listen. Both branches return `ctl=None`. `skip` also has no explicit parsed branch. Controls during `brain_decide` have no return channel in its `Decision | None` contract.

   A latched terminal state or explicit cancellable result must survive every await and be checked before speech, construction and start. An epoch mismatch is not a substitute for termination.

3. **High — Continuation follows only one page turn and conflicts with the activity limit.**  
   [ADR-0017 §2, §3.2, §8.2](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:42).

   Let page A create three candidates, turn to B, then turn to C while continuing to read. The A→B transition uses `run_continuation`; B→C falls back into the Brain loop. A boundary-selected reading then closes the cycle and settles those candidates `not_practised`, contrary to the continuous-reading rule.

   At six activities, `allowed` retains reading because boundary reading opens a new cycle. A continuation is reading that **does not** open a new cycle. “Ledger checks still apply” therefore needs a distinct continuation rule and an explicit limit outcome.

4. **High — “After the current step” cannot enforce the hard deadline.**  
   [ADR-0017 §§3.1–3.2](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:91); ADR-0013 Practice and CHECK outcomes.

   Start a text-mode practice retry at minute 29:59. Retained Practice waits indefinitely for text, so the current candidate never finishes and the session can exceed 30 minutes indefinitely. The same problem exists for text CHECK.

   Also, `time_up_cycle` is nonterminal, while `allowed` has no cycle-time test. It can choose another practice activity against the already expired deadline. Bound waits by the deadline and define the transition that closes an expired cycle.

5. **High — Media preparation explicitly permits a forbidden identity transmission.**  
   [ADR-0018 §§2, 4–5](E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:70).

   Suppose failed ASR produces a clip containing “My name is Mia.” `prepare` keeps the clip; if identity cannot be masked, the rule merely mentions this in the question. A yes then authorizes sending those bytes. That contradicts §§2 and 5’s unconditional prohibition on real household identity.

   The same happens with an unmaskable handwritten school name. Text pseudonymisation earlier in the pipeline cannot sanitize those attachments. The design needs an explicit reject/reprepare outcome for identity that cannot be removed; mentioning it in the consent question does not resolve the contradiction.

6. **High — Consent consumption has no safe ordering relative to an irreversible send.**  
   [ADR-0018 §§2, 4](E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:44).

   The rule says send and mark used “in the same transaction.” If the remote service receives the upload and the process crashes before SQLite commits, the consent can remain granted and permit another send. A database transaction cannot roll back the network side effect. Likewise, `send → log` can leave a successful disclosure unlogged.

   Atomically consume the consent and persist an attempt **before** network I/O; an uncertain delivery must remain consumed. Match `purpose` as well—the row stores it, but the displayed matching rule checks only learner, hash and destination.

7. **High — Provenance loses whose privacy setting governs shared text.**  
   [ADR-0018 §§1, 3](E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:63).

   Learner A has cloud text off and supplies a correction to a shared page. Even if its provenance correctly remains `learner`, learner B’s later session has cloud text on. The filter consults “the learner’s current setting,” and the provenance enum carries no source learner ID. It cannot determine that A’s restriction still applies.

   This affects shared corrections and revisions, and any derived text combining learners’ inputs. Classification needs source ownership and a defined rule for multiple source owners, not only a restrictive category.

8. **Medium — Generated activities are offered without a complete construction or scoring contract.**  
   [ADR-0017 §§3.1–3.3, 6.2](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:84).

   A learner can choose `quiz` from the menu, but `default_params` has no specified question-generation operation when no questions are stored. Having a backend available does not supply a runnable question object. Similarly, `add_cards` can be allowed with neither a Brain nor stored explanations.

   For `teach_items(method=use_in_sentence)`, “The bird flew through the window” is a valid response for *through*, but whole-response match/fuzzy comparison against the item fails. Comparing against something else is undefined because no expected-answer contract is provided. Incorrect retrieval evidence then feeds the newly specified mastery rules.

**3. Problems likely to recur during implementation**

- **Medium — Ownership must be represented for calls that precede activities and for guests.**  
  [ADR-0017 §7.2](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:184), [ADR-0018 §1](E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:14).  
  The listed `brain_calls` fields contain nullable `activity_id`, but no `session_id`, despite ownership supposedly being inherited through a session. A terminal decision never starts an activity to supply that link. `egress_log` is absent from the deletion inventory. Meanwhile, an anonymous guest enters a loop that writes records requiring a non-null learner. Specify ownership for pre-activity/terminal calls, guest storage and crash cleanup, and deletion of payload-bearing logs.

- **Medium — The Difficulty amendment changes weights but not eligibility.**  
  [ADR-0017 §8.6](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:200), ADR-0013 Difficulties.  
  Three sessions containing only `unsure(not_practised)` still satisfy “unsure evidence in ≥3 distinct sessions.” They create a zero-weight `watch` row. Both the contribution formula and the row-existence predicate must exclude policy-only outcomes; changing one leaves the original semantic defect.

- **Medium — Speech permissions still have two owners.**  
  [ADR-0017 §§6.1, 8](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:154), ADR-0013 Reposition.  
  With `interrupt=never`, two unanchored utterances followed by failed page-wide alignment enter retained REPOSITION, which asks for the learner’s first words. Section 6.1 says no such line is allowed inside reading. Implementers must choose which rule to violate. Explicitly place recovery dialogue inside or outside the interruption policy.

- **High — The egress test can pass while a dependency sends directly.**  
  [ADR-0018 §2 and Confirmation](E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:44); [existing edge adapter](E:/GitHub/scil/Leafi/leafi/services/tts/edge.py:28).  
  The existing adapter calls `edge_tts.Communicate(...).save(...)`; it does not construct an HTTP client in repository code. A test forbidding HTTP-client construction outside `egress` therefore does not establish that this transport passes through the filter. Define how SDK-owned transports are mediated or prohibited, and verify actual outbound traffic.

- **Medium — Magpie route binding needs a failure contract, not only a requested model.**  
  [ADR-0018 §§2, 4](E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:57).  
  If a gateway cannot guarantee the requested provider or changes routing, discovering the effective provider in the response is too late for media consent. Require the approved route to be guaranteed before sending, with no unapproved provider fallback. This preserves the owner’s choice of any provider while making that particular consent meaningful.
