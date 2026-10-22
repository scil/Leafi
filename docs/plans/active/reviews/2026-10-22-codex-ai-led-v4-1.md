# Codex design review of ADR-0017/0018 v4, round 1 of 2

Reviewer: codex-cli 0.155.0, model gpt-6-astra, reasoning high, read-only sandbox, 2026-10-22. Prompt: [prompts/ai-led-v4-codex-1.md](prompts/ai-led-v4-codex-1.md).

tokens used
123,024
**There is one High finding:** the new attempt-token contract does not bind transport authorization to the prepared payload or define single-use enforcement for media. Most v3 findings are resolved; cancellation, negotiation and post-session execution still have concrete failures.

I made no edits. Small in-memory probes confirmed the cancellation and negotiation traces below.

For the **15 v3 findings**, in their original order:

| # | Assessment |
|---|---|
| 1 | **Resolved** — ADR-0018 §7.2 specifies exclusion shared by all openers, one migration transaction, rollback and schema-equivalence verification. |
| 2 | **Partly** — the lease’s outer `finally` is fixed; native-deadline mapping and finalization after unexpected exceptions remain incomplete. |
| 3 | **Resolved** — the identified failures are addressed by school enrolment, ORGANIZATION/LOCATION detection and retaining forgotten names in the all-class replacement lists. Detector recall is explicitly unproven. |
| 4 | **Resolved** — `adopt()` commits ownership before returning and conditionally rejects a learner being forgotten. |
| 5 | **Resolved** — finalization assigns early-terminal guest outcomes; recovery explicitly includes already-ended, reasonless guests. |
| 6 | **Resolved** — the `forgotten` CHECK exception and deletion of derived encounter/card fields are explicit. |
| 7 | **Resolved** — code ownership discards proposed content, and construction traverses the complete default chain. Separate negotiation failures remain below. |
| 8 | **Resolved** — session assignment, propensity, execution, override and policy version are separated; evaluation uses assignment rather than successful execution. |
| 9 | **Resolved** — confidence gates both positive and negative spoken answers; the first retrieval event explicitly causes `new → learning`. |
| 10 | **Resolved** — each transmission is charged before sending, including retries and calls subsequently cancelled. |
| 11 | **Partly** — output reserve and extraction allowance are specified, but `brain_call` still applies the ended session’s deadline, terminal checkpoint and ledger. |
| 12 | **Resolved** — answering async `getaddrinfo` in the calling task removes the specified executor-context failure. |
| 13 | **Resolved** — `media` explicitly consumes `remote_teacher` consent with the required matching fields. |
| 14 | **Resolved** — bounded study-store waits replace five-second blocking, and the inspected `Store.transaction()` rolls back failed COMMITs. |
| 15 | **Resolved** — migration includes eases 1–4, and the competing Anki queue writers are explicitly removed. |

The **new defects and remaining failures**, ranked by severity:

1. **High — An attempt token authorizes a destination, but does not explicitly authorize the transmitted body.** [ADR-0018 §§2, 4.1](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:67)

   Trace: `prepare` checks recording A, consumes A’s consent and returns token T. The adapter sends recording B to the same destination with T. The specified transport checks—live token, destination/host and budget—do not reject B. Likewise, no stated token transition prevents a second adapter submission using T; “never retries media” only addresses mediator retries.

   Bind authorization to the prepared payload, learner, purpose and recipient; define atomic first-use consumption at the transport. Any permitted text retries must remain attached to that same authorized request. This is a missing enforcement contract, not a claim that an implementation already leaks.

2. **Medium — The native session deadline does not execute the terminal setter.** [ADR-0017 §§1–2](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:23)

   The prose requires `time_up_session` to be set before cancellation, but the executable operation is plain `CancelScope(deadline=...)`. In the probe, its deadline interrupted an await while `terminal` remained `None`. The mapping function therefore has no terminal status to map.

   Specify the mechanism that connects deadline expiry to the latch—such as a deadline watcher—or explicitly recognize this scope’s deadline cancellation in the mapping function. A native scope alone does not implement the stated ordering.

3. **Medium — Lease release is guaranteed; session finalization still is not.** [ADR-0017 §2](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:29)

   Trace: identification or an activity raises an unexpected `ValueError`. It bypasses `except Terminal`, skips `finalize`, `deliver` and extraction, then releases the lease. The probe produced exactly that path. A running activity remains unfinished until another startup.

   Put finalization and resource shutdown in an exception-safe cleanup path once a session exists. Also isolate delivery failure from extraction: `move_on_after` bounds cancellation, but does not swallow arbitrary exceptions from `deliver`.

4. **Medium — Extraction’s independent scope does not make `brain_call` independent of the session.** [ADR-0017 §§2, 5, 7.1](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:207)

   Trace: the hard deadline expires; finalization succeeds; extraction starts inside its new 20-second shield. Its required `generate` call still computes `deadline ≤ s.hard_deadline`, so immediately returns `None`. After an earlier `stop`, its `checkpoint(s)` still raises `Terminal`. An exhausted `s.ledger` supplies a third refusal path.

   Pass an explicit post-session call context containing its own deadline, allowance and cancellation policy. The outer shield and prose allowance do not override these reads.

5. **Medium — Refusal can reselect the refused kind.** [ADR-0017 §2.1](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:71)

   Use the permitted custom policy containing only `read_listen`; `END` is already appended separately. The learner refuses reading. `refused_of` computes a restricted chain without reading, then calls `settle`, which appends the original menu’s full chain. Reading is selected again. The probe confirmed this.

   Carry the restricted menu or excluded-kind set through `settle` and construction, including fallback.

6. **Medium — Low-autonomy negotiation still starts activities without an accepted choice.** [ADR-0017 §§2.1, 3.2](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:99)

   Two concrete traces:

   - At the cycle activity cap, the menu excludes `break`. Two silences select `wait_spec`, construction rejects it, and `settle` falls through to reading. The probe confirmed this.
   - At autonomy 0–3, two named but unavailable choices execute `why_not` twice, exhaust the loop and return the original activity.

   Waiting/end must be a guaranteed negotiation outcome when consent was not obtained, rather than an ordinary candidate followed by productive fallback. The short-list branch works for a valid named selection, but inherits both failures.

7. **Medium — `finish_activity` permits new activities after the soft deadline.** [ADR-0017 §§2, 2.1, 6.3](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:49)

   Construct an activity just before the soft deadline, then spend eight seconds awaiting confirmation. Neither time passage nor the soft deadline changes the epoch. A “yes” returns the already-constructed activity, and `run_session` starts it during grace.

   Separately, a page turn during grace enters the continuation loop and starts another activity without consulting `allowed()`.

   Enforce the soft deadline at every activity start. Explicitly decide how continuations fit that rule; the current wording says no new activity starts.

8. **Medium — `END` is not guaranteed constructible.** [ADR-0017 §§3.1, 3.3, 5](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:182)

   `end` has a content field, `say`, and no exception to configurable content ownership. Set its owner to `brain`, then exhaust the generation budget. At the soft deadline the menu contains only `end`; both the policy step and appended `END` require unavailable generation and are rejected.

   Make ending unconditional, with an optional generated closing line and a code fallback. Appending another specification of the same unconstructible kind does not guarantee termination.

9. **Medium — Session assignment happens before the learner’s policy is known.** [ADR-0017 §§2, 6.3, 9](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:33)

   `assign_arm()` runs while constructing a guest session, before `identify`. Suppose Alice configures `policy.sequencer=default`, while the guest configuration selects Brain sequencing. Alice’s session has already received its immutable arm.

   Assign after identification using the adopted learner’s settings, or define a provisional assignment that is finalized before the first boundary. Otherwise both behavior and logged propensity can describe the wrong policy.

10. **Medium — The chosen HTTP seam does not cover the retained edge-tts client.** [ADR-0018 §2](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:67), [edge.py](/E:/GitHub/scil/Leafi/leafi/services/tts/edge.py:29)

    The ADR requires adapters to transmit through `egress.client(destination)` and its `httpx2` transport. The retained adapter invokes `edge_tts.Communicate(...).save(...)`; the supplied libraries research identifies its transport as aiohttp WebSockets.

    A prepared token therefore has no specified path into the mediator that creates grants and accounts for transmissions. Calling `prepare` alone either leaves the socket denied or requires an additional, undefined authorization path.

    Specify an aiohttp/WebSocket mediation seam or an explicit replacement adapter. Aliasing `httpx` does not address aiohttp.

11. **Medium — The full pipeline removes the answer from the permitted local fallback.** [ADR-0018 §§2–3](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:73)

    With `cloud.text=off`, an `item_used` answer selects an eligible local Ollama judge. But all study purposes run the full pipeline, whose provenance filter removes learner text when that setting is off. The local judge receives no answer to judge.

    State which filtering stages depend on destination locality. Local eligibility currently promises a usable path that the universal pipeline strips of its input.

12. **Medium — Zero-day guest retention does not delete at wrap.** [ADR-0018 §§1, 5](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:49)

    Set `guest.keep_days=0`. Identification records an already-expiring unconfirmed guest. Finalization follows the `unconfirmed` row, which leaves deletion to the sweep. That sweep already ran before the session and otherwise runs daily. History survives wrap despite the setting’s stated meaning.

    Finalization needs an explicit zero-retention branch. It must also prevent subsequent extraction from recreating guest-derived records after that purge.

13. **Medium — Recall has no schedule for an item whose first retrieval fails.** [ADR-0017 §6.2](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:270)

    A new, uncarded item receives its first counted `fail`, becoming `learning`. Recall spacing is measured after the last success, but none exists. Teaching selects new items; recall depends on a due time that cannot be calculated from the stated rule.

    Define initial and failure scheduling, including which evidence advances the 1/2/4-day spacing.

14. **Medium — Forgetting is not fenced against new cross-learner derived writes.** [ADR-0018 §§1, 3](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:24)

    B has an active session using material sourced from `[A, B]`. Forgetting A is allowed because A owns no open session. The purge deletes B’s existing A-derived rows; before the remaining deletion transactions finish, B’s in-flight generation writes another `[A, B]` assessment. Only B owns that row, and no write-time source check or final rescan is specified.

    Checking A’s `forgetting` state transactionally when persisting derived material closes this race. Treating a deleted source as cloud-off prevents later transmission, but does not delete the newly retained local copy.

There are also these **explicit contradictions**, beyond those already demonstrated above:

| Severity | Sections | Concrete conflict |
|---|---|---|
| Medium | ADR-0017 §3.4 versus §8.6 | §3.4 names encounters “for teaching”; §8.6 requires encounters from both teaching and recall. A failed recall either contributes to Difficulties or does not, depending on which rule implements it. |
| Low | ADR-0017 §1 versus §2 | Setting the terminal latch is declared the only stopping mechanism, but `idle_session` is terminal in the loop and absent from the latch’s permitted values. An idle activity can end the session with no mapped terminal reason. |
| Medium | ADR-0017 §§2/7.1 versus §5 | Extraction has its own deadline and allowance, while its specified call primitive still reads the session’s expired deadline, latch and ledger—finding 4. |
| Medium | ADR-0017 §§1/6.3 versus §§2/2.1 | Grace permits finishing the running activity only, while delayed negotiation and continuations can start new ones—finding 7. |
| Medium | ADR-0018 §2 eligibility versus §§2–3 pipeline | Local judging is allowed with cloud text disabled, but the common filter removes its learner input—finding 11. |

The normal migration trace, durable adoption, ordinary guest end states, per-transmission charging, code-content discard, async DNS answer, configured gateway-port protection, allowed download redirects and consent-purpose matching now have coherent design paths. I have not counted scheduled replacements of the old ADRs/code, the settled owner decisions, routing policy or magpie’s trust assumption as contradictions.
