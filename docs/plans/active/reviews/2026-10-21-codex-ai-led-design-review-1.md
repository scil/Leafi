# Codex design review 1: ADR-0017 / ADR-0018 (AI-led study, learners and privacy v2)

Reviewer: codex-cli 0.155.0, model gpt-6-astra, reasoning high, read-only sandbox, 2026-10-21. Prompt: [prompts/ai-led-design-round-1.md](prompts/ai-led-design-round-1.md).

**The direction implements the owner’s decisions, but the ADRs are not yet a complete executable design.** The largest risks are candidate ownership across activities, terminal controls, and privacy enforcement across all destinations. These findings concern implementation soundness, not the settled defaults.

I read only the permitted files. No files were changed or tests run.

**Hand-execution of the requested scenarios**

| Concrete input | Result under the written pseudocode |
|---|---|
| **No Brain**, no Anki due, page available | `allowed` includes `read_listen` and `read_aloud`; the empty Brain chain returns `None`; the default selects `read_listen`. After reading, candidates select `practise_errors`. But new items select `teach_items`, whose explanation must be Brain-written. Once the page is exhausted, `read_listen` remains allowed although its default “next unread range” is empty. Neither case has an executable fallback. |
| **Brain times out twice** | With `[claude, ollama]`, each returning `None` after three seconds, the default runs after roughly six seconds. With one backend, a timeout gets **no same-backend retry**: it immediately advances out of the chain. A separate failure occurs when an invalid first response triggers a retry that times out: `validate(None, obs)` is called without the first call’s `None` check. |
| **Page turn during `read_listen`, three open candidates** | Current sentence completes by ADR-0013(iii); all three candidates remain open under §8.2. `practise_errors` remains allowed for the old cycle. The design does not say whether the next observation and active `ReadingState` belong to the old page or newly identified page. Starting another `read_listen` settles all three `not_practised`; choosing practice first requires retained old-page state. |
| **Autonomy 2**, proposal `practise_errors`, learner asks for `quiz` outside the menu | Leafi says “not now.” The branch then has no specified result: the learner answered, so the “no answer within eight seconds” fallback does not apply. Reask, accept proposal, skip, or end are all unspecified. |
| **Autonomy 10**, learner says `stop` | Prose requires termination. During negotiation, however, the branch says “say …; start,” without a cancellation result. During an activity, even if `run_activity` returns a stopped result, the outer loop records it and recomputes the menu without checking terminal status. Correct termination requires an additional contract. |
| **`cloud.text=off`, `learner_questions`** | After reading, any `brain_available` makes Q&A available—even if the only backend is Claude or magpie. Sending the question violates the setting; removing it leaves the model unable to answer. Research D17’s local-only answer route is absent from the ADR’s dispatch logic. |
| **Two enrolled siblings with similar voices** | Suppose voice scores are A=.87/B=.85 with margin .05: recognition should ask. If face scores instead strongly select B, “on either” does not specify how voice ambiguity and face evidence combine. Even an unambiguous match has no explicit affirmative return: the written flow falls through to “Who is reading today?” Silence, conflicting modalities, and mistaken confirmation lack defined outcomes. |

**High findings**

1. **Deferred candidates have no complete ownership and settlement contract.**  
   [ADR-0017 §§1, 3, 8](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:147), interacting with ADR-0013 Sentence completion, Practice, `/back`, and Control precedence.

   In the three-candidate page-turn case, retaining only the current page loses the state needed to practise and settle the old candidates. Retaining the old state leaves page identification and subsequent reading ambiguous. `stop` retains *page* settlement, which is insufficient if candidates survive on an earlier page.

   There are also direct conflicts:

   - §1 ends a cycle at the next **reading activity**; §8.1 names only the next `read_listen`. `read_aloud` therefore has ambiguous settlement and cycle behavior.
   - `/back` is kept unchanged and preserves candidates for rereading, but starting another `read_listen` settles them first. Subsequent alignment cannot withdraw those now-terminal miscues as rereads.
   - Page-turn preservation is specified for `read_listen`; a page turn during deferred practice still inherits ADR-0013’s settlement behavior.

   Specify candidate ownership by cycle, page read and revision; retain the necessary reading states; define settlement reasons and token updates for every exit. This is the interaction most likely to keep producing regressions.

2. **The default policy is not executable for all states it can select.**  
   [ADR-0017 §§2–3](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:72).

   The no-Brain trace reaches `teach_items` without an explanation source, and a completed page still advertises `read_listen`. A default implementation can consequently crash, repeatedly execute an empty range, or invent undocumented behavior. With no page loaded, the menu is only `end`/`break`, and the default immediately ends; the loop contains no book/page acquisition transition.

   Each menu entry needs constructible parameters and available execution capabilities. The default needs explicit behavior for unavailable content generation, exhausted ranges, and page acquisition. Its omission of `add_cards` also needs a decision: default sessions otherwise practise items without ever selecting card creation.

3. **`stop`, cancellation and stale-result rejection do not compose with the new loop.**  
   [ADR-0017 §§2, 2.1, 5, 8](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:20); ADR-0013 Async guard and Control precedence.

   A stopped activity can return into a loop that starts another activity. A Brain response computed before a page turn or correction can still pass `every id ∈ obs`, because it is validated against its old observation.

   Keeping ADR-0013’s guard “as written” is insufficient without specifying where the new negotiation, Brain calls and record writes capture and check it. Require terminal/cancelled outcomes, control handling while deciding and negotiating, and freshness checks immediately before speech, execution and writes. Activity changes and learner/privacy changes also need invalidation semantics.

   Spoken `stop` during playback remains constrained by the retained half-duplex rule; the design should preserve the existing console/Face cancellation distinction explicitly.

4. **The advertised hard limits are not enforced by the shown rules.**  
   [ADR-0017 §§3, 5, 6.3](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:128).

   At minute 19:59, a long `break` or text-mode activity can run past the 30-minute ceiling because time is checked only at boundaries. After six activities, `learner_questions`, `break` and both reading modes remain available. Nothing shown charges retries or Q&A calls against the 40-call budget.

   Likewise, “counts ≤ limits” does not establish remaining budgets: two practice decisions of five candidates each can pass a per-decision check while violating five per cycle.

   Define runtime deadlines, cumulative counters, bounds for `seconds`/`max_turns`/`max_cards`, and call-budget reservation before every backend attempt.

5. **`cloud.text=off` has no safe, functional Q&A route.**  
   [ADR-0017 §§3–5](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:67), [ADR-0018 §2](E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:27); research §8 D17.

   A globally available Brain is not necessarily eligible to receive this question. Q&A needs local-only backend selection with **no cloud fallback**, plus an unavailable outcome when no local model works. Also resolve ADR-0018’s retention of ADR-0011’s v1 scope, which still defers the local Brain.

6. **Pseudonymisation is asserted to be unbypassable without defining an unbypassable boundary.**  
   [ADR-0018 §§2–3](E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:38).

   The concrete conflict is reply handling: alias → real name happens before speech, while edge-tts receives text to speak. Reapplying pseudonymisation protects the name but speaks the alias; omitting it leaks the real name. The recognition greeting “Hi Mia?” has the same problem.

   The checked Brain adapters also construct and send requests directly; the Ollama adapter accepts a configured URL. Calling an adapter “local” does not establish that its endpoint is local.

   Require mediation at every outbound transport, endpoint-based locality checks, and a local synthesis path for restored identity. The observation builder alone cannot cover TTS, notifications, media, retries and other calls.

7. **Stored text can bypass `cloud.text=off` through memory and reclassification.**  
   [ADR-0017 §§4, 7](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:90), [ADR-0018 §§2–3](E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:31).

   Example: a locally generated `learner_note` quotes the learner’s answer. The next observation sends it under `memory`, despite omitting `last_activity.heard`. Parent notes, assessments, local-model answers sent to edge-tts, and learner-entered page corrections present similar paths.

   There is no provenance/classification rule for derived text or for changing the setting after notes were created. Known-value replacement also misses identities introduced in free text: “My sister Bea attends Oak School” is not covered merely by replacing the current learner’s enrolled profile.

   Define which derived fields inherit learner-text restrictions and how all household identities are handled. The policy needs this distinction; testing whether *any heard word* occurs outbound is insufficient because expected page words may legitimately occur in both places.

8. **Media consent does not yet bind a transmission tightly enough, and text pseudonymisation cannot sanitise media.**  
   [ADR-0018 §§2, 4–5](E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:46).

   For an unresolved recording, “yes → row → send” has the right ordering. But requiring a row **ID** does not specify verification of its learner, exact bytes, destination, consumption status or current request. A failed request followed by a fallback provider can otherwise reuse consent; concurrent sends can consume the same row twice.

   A consented image may contain a handwritten real name or school, and a clip may say the learner’s identity. “Pseudonymised context only” does not remove these from the attachment, despite the separate “never send real name/age/school” rule.

   Define a bound, single-use consent lifecycle and what happens when identifying media cannot be sanitised. Resolve the separate explicit exception: §2 retains habit snapshots without per-item rows, while §§4–5 state that all cloud media requires them.

9. **Recognition uncertainty can select another learner’s privacy policy.**  
   [ADR-0018 §1](E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:17).

   If similar-voiced sibling A has `cloud.text=off` and B has it on, a mistaken assignment affects egress immediately, not just learning history. The pseudocode lacks explicit yes/no/timeout outcomes, modality-conflict resolution and missing-Eye behavior. “Recognition on for any learner” also invokes both matchers without expressing per-learner voice/face exclusions.

   Recognition should produce a tentative identity, with a defined confirmation transition before profile-dependent egress. A misheard unfamiliar name must not automatically create a new default-on learner without an enrolment confirmation.

**Medium findings**

10. **Negotiation and validation can produce an activity that was never validly constructed.**  
    [ADR-0017 §§2.1, 5](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:40).

    The autonomy-2 out-of-menu answer has no transition. At middle autonomy, `alternative` contains only a kind: switching from practice to `read_aloud` supplies no page/range. A learner’s valid alternative has the same parameter problem, and the resulting `act` is not revalidated.

    ID membership alone also permits wrong relationships—for example, sentence IDs from the wrong page, reversed ranges, duplicate candidate IDs, or candidates no longer open. Validate a fully constructed final activity against current ownership and remaining budgets.

11. **The fallback procedure lacks a total error contract and an overall deadline.**  
    [ADR-0017 §5](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:104).

    Besides `validate(None)` after a repair timeout, backend exceptions are not handled in this pseudocode despite §2’s “never raises.” Each backend may consume two independent three-second calls; three backends can take approximately 18 seconds before defaulting.

    Define total validation on missing/malformed responses, exception normalization, retry ownership and a deadline for the entire decision. The existing Claude adapter already owns retries and an overall deadline, so composition needs an explicit contract.

12. **Interrupted-session recovery lacks the new durable state.**  
    [ADR-0017 §§7–8](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:138); ADR-0013 Interrupted session; [data model](E:/GitHub/scil/Leafi/docs/architecture/data-model.md:14).

    Crash after a page turn but before practice: which page is “the last page read,” which cycle owns the candidates, and which page should resume? Crash after an activity changes miscues but before `record`: the history may omit work already performed.

    Preserve ADR-0013’s stale-candidate settlement, but define transactional boundaries and durable cycle/activity status, page associations, cursors and idempotency. Activity rows written only after execution cannot distinguish “never started” from “partially completed.”

13. **Difficulties will include policy omissions, and new activities lack encounter semantics.**  
    [ADR-0017 §§3, 8](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:149); ADR-0013 Difficulties and CHECK outcomes.

    If the Brain skips practising the same candidate in three sessions, `unsure(not_practised)` contributes to a `watch` Difficulty under the retained formula—even though the learner never failed a retry. This existed for unpractised candidates before, but the new discretionary policy makes it a recurring source of policy-driven “difficulty.”

    Separately, `teach_items` has outcomes but no defined `encounters` mapping; `quiz` specifies keyword answers without requiring the item association needed for an incorrect CHECK encounter. Without these, knowledge Difficulties may disappear or attach to arbitrary items.

    Define these mappings and explicitly accept or amend the treatment of `not_practised`. Preserve acoustic evidence for `confirmed`.

14. **Records can be lost, rejected inconsistently or applied after their basis changes.**  
    [ADR-0017 §§2, 5, 7](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:29).

    A final `end` decision carrying an assessment breaks before `record` and `apply_records`, losing that assessment. Records about the previous activity are applied only after the *next* activity; a correction during that activity can invalidate their basis.

    §5 rejects decisions with invalid records, whereas §7.1 says invalid records never block decisions. Also, the observation does not explicitly supply the last activity’s ID despite requiring assessments to reference it.

    Separate action validation from record validation, bind records to evidence and freshness, and specify terminal-decision logging and application order.

15. **Learner isolation requires keys and query rules, not only added columns.**  
    [ADR-0018 §1](E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:13), [data model](E:/GitHub/scil/Leafi/docs/architecture/data-model.md:20).

    `knowledge_items` currently has global uniqueness on `(kind, language, key, sense_hint)`. Adding `learner_id` without changing that constraint prevents siblings from having independent rows for the same word. Lemma-only card deduplication and same-book interrupted-session lookup can similarly cross learners.

    Specify learner-scoped uniqueness, joins, resume queries, Anki identities and deletion ownership. Session-linked records can inherit ownership; every table need not duplicate the column, but that inheritance must be enforced.

16. **Magpie is correctly treated as cloud, but the downstream destination is not bound.**  
    [ADR-0018 §§2, 4](E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:38).

    Allowing any provider is consistent with the owner’s decision. The missing rule is what happens when magpie changes the actual provider: consent and auditing cannot identify only `localhost` or “magpie” if media is approved for a particular destination.

    Record the effective provider/model and bind media permission to the actual route. If routing is unknown or changes, define the resulting refusal or renewed consent. Telemetry-off and permitted local gateway logs do not answer this routing question.

**Low findings**

17. **Item mastery has competing authorities and no retrieval-evidence record.**  
    [ADR-0017 §§6.2, 7.1](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:124); data model `knowledge_items`.

    Two successful retrieval days can mark an item known, while the existing Anki rules derive status from interval/lapse. An ensuing sync may reverse the Brain-mediated change. Specify precedence and persist retrieval events with item, learner, date, outcome and evidence; a Brain assertion cannot establish two successful days.

18. **Reading interruption settings do not determine the actual timing behavior.**  
    [ADR-0017 §§1, 6.1, Confirmation](E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:120).

    With `reading.interrupt=never`, six seconds of silence still has a separately specified word prompt. The confirmation replay expects no line inside reading, while defaults permit backchannels and encouragement. Define which utterances each setting allows, and how help is recorded so a prompted word is distinguishable from independent reading.

The implementation needs explicit records for **cycle ownership, activity terminal states, cumulative budgets, retrieval evidence, text provenance, confirmed learner selection, and consumed media consent tied to an actual destination**. Without them, the same ambiguities will recur in recovery, validation and privacy tests.
