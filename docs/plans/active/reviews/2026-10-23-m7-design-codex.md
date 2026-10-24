# M7 design rev 1 - codex (round 1)

Reviewer: codex `gpt-6-astra`, reasoning effort high, read-only sandbox, prompt `reviews/prompts/m7-design.md`, run 2026-10-23; independent of the other two reviewers. Its final message follows unedited (163,072 tokens).

The design is **not ready to implement unchanged**. Its main mechanisms agree with the ADRs, but several interfaces can lose provenance, accounting information, or cancellation guarantees.

1. **High — D4/D11/D13: provenance is not preserved through the whole request–response path.**  
   The observation classification is sound for genuinely static `session`/`menu` fields, actual page sentences, expected candidate words, and numeric counts/confidence bands. Heard words need their original learner sources; learner notes, assessments, explanations and book notes need their stored provenance—not merely the current learner’s id.

   The dangerous transition is from these `Text` leaves into the “one user message” and then back into generated text. Egress treats ordinary strings as `system`; the existing Claude adapter wraps its entire prompt as `page`. Either pattern, reused here, bypasses learner-text gating. Similarly, D13’s “derived when the observation held learner text” must include **existing derived text**, not just raw utterances. A local Brain can copy a private learner note into an assessment or book note; relabelling that output `system`/`page` permits a later cloud call.

   **Fix:** preserve typed leaves until egress prepares the body, and propagate source unions and restrictive provenance into every generated field, stored record and spoken line. Explicitly cover `teach_items`’ error/explanation, quiz material, stored card text, translations, answers, notes and book notes. Keep learner questions under purpose `answer`; D11’s `generate(kind="answer")` must not bypass answer eligibility. Extraction for an enrolled learner with `cloud.text` off must use eligible local evidence or filtered cloud evidence; guest extraction remains skipped.

2. **High — [D6, line 49](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-23-m7-brain-design.md:49): rejection feedback can leak private output.**  
   Input: a local backend sees an off-cloud learner’s words and returns an invalid field containing them. Pydantic’s validation error includes `input_value`—confirmed with the installed version. Appending that error as a `system` rejection line to the next cloud tier bypasses `_gate`. Listed household names are still replaced, but learner words escape, and an unlisted friend’s name bypasses the learner-text detector.

   **Fix:** rejection feedback should contain bounded, static error codes and trusted field paths only, never rejected values or exception strings. Otherwise it must inherit the rejected output’s provenance and be filtered again.

3. **High — D4/D9: routing locality and egress locality currently disagree.**  
   D9 defines locality using the exact `backend:model` membership in `LOCAL_MODELS`. However, [the destination registry](/E:/GitHub/scil/Leafi/leafi/privacy/destinations.py:81) unconditionally labels Ollama `local`; `prepare` therefore skips both cloud gating and pseudonymisation. An unlisted Ollama model can be treated as cloud by routing/filtering but local by the transport. Even permitted page text containing a real household name then leaves unmasked if that endpoint forwards remotely.

   **Fix:** resolve the model and destination together and use that same effective locality for eligibility, filtering, preparation and transmission. Sharing `_gate` alone does not establish agreement. Include guests, missing school answers, forgotten/missing sources and mixed-source text in this test matrix.

4. **High — [D14, line 65](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-23-m7-brain-design.md:65): replay loses the information required to enforce privacy.**  
   The recorded observation is rendered **before filtering**, but its file shape does not preserve each leaf’s provenance and source ids. Re-preparing that string pseudonymises names; it does not remove an off-cloud learner’s words. Thus an observation recorded with `cloud.text` off—or replayed after it was switched off—can send those words to the chosen cloud tier.

   Deleting files solely by session owner also misses A’s data embedded in B’s observation. Finally, default indefinite raw replay retention conflicts with the existing opt-in, 30-day evaluation-transcript policy.

   **Fix:** retain structured provenance, reapply current source permissions through the normal call path, and index deletion by every source learner. Default raw capture to the existing opt-in retention policy. A broader retention policy needs the owner’s explicit decision.

5. **High — [D5, line 47](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-23-m7-brain-design.md:47): charging is not atomic with transmission reservation.**  
   `try_charge()` changes an in-memory ledger, while [egress admission](/E:/GitHub/scil/Leafi/leafi/privacy/egress.py:498) reserves attempts in a retryable SQLite transaction. Put the hook after version checks but before the reservation, as proposed: charge succeeds → reservation/commit fails → transaction rolls back → retry charges again. Alternatively, cancellation before a successful reservation leaves a charge for an attempt that never reached transmission admission.

   **Fix:** define one rollback-safe, exactly-once charge per successfully reserved transmission, including database-busy retries. Keep transport retries chargeable individually and never add another charge when recording `brain_calls`. The per-token hook and single transport retry owner are otherwise sound.

6. **High — D1/D6/D7: cancellation and failure erase the audit information the design promises.**  
   Hand execution: standard-tier send gets 503, costing **1**; `stop` occurs during the mediator’s retry delay. The correct total is **1**, or **2** if the retry was already admitted. There must be no escalation. But cancellation produces no `ModelReply`, and ordinary failures return `None`, losing prepared payload, attempt count, usage and failure classification. D7’s after-call `busy.retry` can itself be cancelled before writing.

   **Fix:** preserve attempt metadata independently of successful replies; finish auditing through bounded cancellation-safe cleanup, then propagate the terminal status. Distinguish `timeout`, `refused`, `over_budget` and `cancelled`. Define asynchronous closure of the old mediated client: synchronous `reset()` alone does not demonstrate cleanup.

   **Sound:** a boundary `decide` has no running activity row to leave behind. Calls inside activities already have cancellation-to-status handling in `run_activity`; preserve it rather than swallowing cancellation.

7. **High — D6/M7b: a real `stop` may never reach the latch during the call.**  
   [Inputs readers are demand-driven](/E:/GitHub/scil/Leafi/leafi/study/harness/inputs.py:87). After a reading input completes, a silent Brain wait requests neither another input nor a control read. In text/no-Mouth mode, even filler speech does not request one. Typing `/stop` during the mediator’s retry can therefore remain unread until negotiation resumes.

   **Fix:** explicitly service controls throughout Brain waits without consuming ordinary answers ahead of their activity. Test through the actual input source; a test that directly invokes `latch.terminate("stop")` misses this failure.

8. **High — D8/D10: cancelling filler does not establish that it has stopped, or that output is current.**  
   Hand execution: at 0.8 s the filler wakes and enters Face/TTS work; the reply arrives concurrently; the wrapper requests cancellation and returns; negotiation starts the real line while filler cleanup is unfinished. `spawn()` currently returns no child cancellation/join handle. Existing speech cleanup contains awaits, and neither `Inputs.say` nor `Hub.say` checks the session epoch.

   D10’s echoed epoch comparison also only compares the response with the **old observation**, not with the live epoch.

   **Fix:** give filler an owned cancel scope and completion signal; cancel and await cleanup before releasing the reply. Check the captured epoch before display/synthesis/playback and before applying generated records. Preserve the listening gate during cleanup. **Camera Face-only filler is sound and already permitted by ADR-0017 §5.**

9. **Medium — D6–D8: audit work can consume the output reserve and prevent the promised escalation.**  
   Hand execution on PC: `next_activity` deadline is 6 s; reserve makes the model deadline 5 s. Standard times out at 3 s; deep gets at most the remaining 2 s. With one transmission on each tier, the charge is **1 + 3 = 4**, even if the first produced no answer. But D7’s unconstrained `busy.retry` defaults to a further five seconds, potentially consuming both escalation time and the reserved speech time.

   **Fix:** carry one absolute moment deadline through decision, generation and audit handling; bound ordinary audit retries by the remaining allowance and preserve pending audit information separately. Never restart the moment for each candidate or generation attempt.

10. **Medium — [D3, line 43](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-23-m7-brain-design.md:43): the SDK choice works; the schema conversion is incomplete.**  
    I ran an in-memory probe using installed `anthropic 1.17.0`: `messages.create(**prepared_body)` with `output_config` preserved the JSON body exactly. That part is sound.

    Removing only six keywords is not a complete compatibility rule. For example, Pydantic `Field(gt=0)` emits `exclusiveMinimum`, and a discriminated union emits `oneOf` plus `discriminator`, rather than the promised `anyOf`. The full decision schema’s optional content, alternative and records also need checking against server complexity limits. Anthropic documents limits of 24 optional parameters and 16 union-typed parameters, plus additional compilation limits. [Structured-output documentation](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)

    **Fix:** test the exact generated schema, recursively transform or reject unsupported constructs, retain all constraints in strict local validation, and probe compilation before adopting the schema. A small SDK body-equality test does not prove full-schema acceptance.

11. **High — D11: quiz answerability and id existence are insufficient.**  
    Input: cited text says “The fox is red”; question asks “What colour is the rabbit?”; keyword sets are `["red"]` and `["blue"]`. The proposed test passes because one set occurs in the evidence, although the question is unsupported and the second accepted answer is wrong.

    Separately, an existing but unrelated item id can receive retrieval credit. Sentence numbers can refer to different pages/revisions across a cycle, and current `_selection` accepts a positive ordered range without checking its endpoints exist.

    **Fix:** validate every accepted answer alternative and its relationship to the question; require nonempty evidence and keyword sets. Bind references to learner, item type, page read/revision and current cycle—not just integer existence. Validate the question-to-item association before writing retrieval events, and reject/deduplicate repeated ids. Keep the existing Anki card checks after generated-card validation.

12. **Medium — D3/D10/D13: whole-output validation can defeat independent record rejection.**  
    Input: valid proposed activity plus an assessment longer than 500 characters. If `Decision.records` contains fully constrained Pydantic models, validation rejects the entire decision before `apply_records` can drop only the bad assessment. Invalid optional activity content can similarly trigger decision escalation instead of D10’s generation fallback.

    **Fix:** validate the decision envelope and executable selection separately from independently droppable records and replaceable content. ADR-0017 §7.1 explicitly requires an invalid record not to affect the decision.

13. **High — [D13, line 63](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-23-m7-brain-design.md:63): the proposed evidence cannot reconstruct all item statuses.**  
    Derivation is the right approach, but current storage lacks essential evidence. `retrieval_events` contains only success/fail and timestamps; `review_answers` has ease/acknowledgement but no observed interval or session/activity link. Anki interval is currently transient input to `_update_status`. There is also no durable ignore event.

    Consequently, replay cannot reliably reconstruct Anki `known`/`lapsed`, preserve an explicit ignore, or distinguish which Anki evidence belonged to a forgotten session. Routing `_update_status` through `apply` does not repair the missing evidence.

    **Fix:** specify durable Anki state/acknowledgement evidence and explicit ignore evidence, with ownership and deletion semantics. Apply the first card acknowledgement immediately. In **both** mastery modes, acknowledged cards must follow Anki; retrieval thresholds apply only where the ADR permits them. Include normal acknowledgement and reconciliation paths.

14. **Medium — D13/M7d: forgetting and recall need a rebuild operation, including empty history.**  
    Input: an item becomes known from six successes; forgetting removes its last qualifying session—or all its events. Calling `apply` “over what is left” can preserve the old status if the reducer starts from that status; with zero remaining events, it may never run at all. Recall dates have the same problem.

    The existing retrieval writer also uses `date.today()`, rather than the configured household timezone, which can count the wrong distinct mastery days.

    **Fix:** collect affected item ids before deletion, rebuild each from a defined baseline and ordered surviving evidence, and write the result in the forget transaction. Derive dates using `HOUSEHOLD_TZ`; cover first failure, success spacing, failure reset, unavailable answers, empty history, acknowledgements and ignored items.

15. **Medium — D13: ranking silently changes accepted policy.**  
    The owner chose optional YLE download, with CYP-LEX fallback **when YLE is absent**. D13 makes CYP-LEX unconditional because no parser is installed. A downloaded matching YLE headword is therefore ignored, contrary to ADR-0017 §6.2 and the Decision Log.

    Also, treating `learning` as “known” conflicts with the current card checker, which treats it as unknown. A single failed retrieval makes an item `learning`, so this choice can immediately make difficult sentences appear to contain only one unknown word.

    **Fix:** implement the accepted YLE fallback rule or obtain an explicit deferral. Define and share the ranking/card-check vocabulary; the new “learning means known” policy needs justification and owner agreement.

16. **Medium — D10: the announcement threshold is wrong.**  
    With defaults, autonomy 5 is above `bands.argue` but below `bands.announce`. D10 can therefore speak `say_before` as an announcement before the learner’s opportunity to object. “When the decided activity is the one that runs” cannot be known before that negotiation completes.

    **Fix:** use `rationale.strategy` for the actual offered proposal; use announcement text at `autonomy >= bands.announce`, or after acceptance where appropriate. Never reuse the rejected primary proposal’s rationale for an alternative/default activity.

17. **Medium — D2/D9: renamed routing keys need the existing privacy protections.**  
    Adding `BRAIN_TIER_*` and `BRAIN_ROUTES` only to the manifest would bypass protections currently attached to `STUDY_BRAIN_MODEL`. The new keys are absent from both `PRIVACY_FLOOR` and the policy fingerprint. Tier syntax could also bypass the existing Ollama release gate by avoiding `BRAIN_BACKEND=ollama`.

    **Fix:** migrate manifest, protection floor, policy fingerprint, validation and release gates together. Require explicit provider/model routing where ADR-0018 requires it. Restart-only household configuration is reasonable, but it does not remove these obligations.

18. **High — [M7a–M7e, lines 71–75](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-23-m7-brain-design.md:71): the proposed commit boundaries are not independently safe yet.**  
    M7a replaces backend interfaces while existing callers/tests still use `.run(BrainRequest)`. M7b enables Brain sequencing before M7c installs several activity handlers: after reading, a valid inline quiz proposal can construct successfully and then hit the missing `KINDS["quiz"]`. Construction is currently synchronous throughout `first_constructible` and negotiation, so awaiting generation requires a coordinated change.

    M7e also cannot simply delete `coach.py`: reading, practice and read-aloud still call its page helpers. M7d needs to populate `World.facts()`’ new-item and recall fields, currently left at defaults, and add saveable mastery/extraction settings.

    **Fix:** name the compatibility bridge or atomically migrate callers; gate activity availability until handlers exist; convert construction callers together; relocate retained coach helpers before deletion. Assign these dependencies to specific commits.

19. **Medium — D14/D15/M7 acceptance: several guarantees remain unassigned or overstated.**  
    Existing M6 work explicitly left the full-session settings-reload test and `voice-diag.wav` replay outstanding; neither gets an M7 step. Real extraction after stop/deadline/budget exhaustion also needs coverage beyond today’s no-op extraction tests. Add explicit acceptance cases for busy/cancelled call auditing, retry charges, stale filler, independent record rejection and provenance-preserving replay.

    D15’s schema checks cannot establish resistance to an injected “choose end”: `end` is a valid activity. Likewise, a system-prompt quotation can fit a valid reply string. Separate deterministic structural enforcement from measured model-behaviour tests.

    Finally, D14 removes the “smoke check” qualification after `review_after` sessions. ADR-0017 §9 still calls 200 sessions a smoke check and requires an effect size and sample-size plan before conclusions.

    **Fix:** map every outstanding Confirmation requirement to a step/test or explicit owner-present check, and retain the evaluation qualification until its stated evidentiary conditions are met.

The **sound additions beyond the ADR** are D1’s core port/`Text` move, D2’s explicit tier configuration, D3’s raw SDK call with local validation, D4’s shared gate, D5’s token-specific budget hook, D7’s cloud payload logging after pseudonymisation, and D8’s camera Face-only filler—subject to the integration fixes above. D12’s confidence rule and conservative `unavailable` result also agree with the ADR. D7 must qualify “never real names”: approved local destinations intentionally receive unpseudonymised text.

No files were edited. Verification was source inspection and an in-memory SDK/Pydantic probe; no live model call or full pytest run was performed.
