# Session panel design rev 2: codex increment round

Reviewer: codex `gpt-6-astra`, effort high, read-only, 2026-10-25, prompt `reviews/prompts/session-panel-rev2.md`. Output as returned (the final message; the run log is not kept). Answered by rev 3.

Revision 2 still needs changes. I checked T1–T24 against the code. The lease-before-start ordering, per-PID files and process identity check, explicit Anki/hint exceptions, and read-only database fallback address their core round-1 concerns.

References below use the line numbers in [revision 2](E:/GitHub/scil/Leafi/docs/plans/active/2026-10-25-study-session-panel-design.md). No files changed.

1. **High — D7:177–191: a want has two independently consumed representations.** During an announce-band line, `/do break` posts the latch slot and a stream item owned by `None`. Negotiation consumes the slot and starts `break`; its first `listen()` accepts the remaining unowned item and raises `Jump`, immediately ending the requested break. Stale wants have the converse problem: ownership filtering drops the stream item, but its already-posted slot survives. Repeated requests also leave multiple stream items despite the “one slot” rule. See [ownership filtering](E:/GitHub/scil/Leafi/leafi/study/harness/inputs.py:227).
   
   **Fix:** give each request one identity and one consumption state, carrying kind, source and owner. Consuming, replacing or rejecting it must invalidate its queued wake-up. Check ownership before changing the slot or cutting speech. Before `Run(a)`, a newer want must restart construction, not merely update `b.wanted` while returning the old `a`.

2. **High — D7:184–185: `Jump` loses completed work from the activity outcome and restores spent budgets.** Answer three quiz questions, then `/do break` during question four. `results` remains local to `quiz`; `run_activity.outcome` is still `None` because the activity never returned. Recording only `ended_by="do"` loses `questions=3`. [The ledger](E:/GitHub/scil/Leafi/leafi/study/harness/ledger.py:41) derives quiz and teaching budgets from those outcome counts, so another activity can exceed the cycle/session limits despite the evidence already written.
   
   **Fix:** retain partial outcomes as each step completes, and merge them into both normal and `Jump` finishes. Preserve completed quiz, teaching, review and reading counts—not just `panel_inputs`.

3. **High — D4/D5/D6:132–157: actions are not bound to the session displayed.** A tab displays session A; A ends and B starts before the next poll; the owner presses Stop. The action contains only `action`, `text` and `seen`, while discovery selects the newest live session. The proxy can therefore send `/stop` to B. Namespaced GET versions do not protect POSTs, and `_deliver` handles Stop before prompt ownership.
   
   **Fix:** carry the displayed session identity in every action and verify it at both hops. Reject an action for A once A is unavailable; never retarget it to B.

4. **Medium — D7:181–189: `listen()` is not a sufficient interruption boundary.** Direct `/do` during a matching quiz or `read_listen` listen can reach `run_activity` correctly, in text and voice mode, without skipping a sentence. But [controls_only](E:/GitHub/scil/Leafi/leafi/study/harness/inputs.py:253) consumes only pages/skips: a want does not interrupt the Brain call. During `learner_questions`, the answer can still be spoken and the want then dropped as belonging to the previous question. `read_aloud` never listens after opening its page, so it continues reading after cutting one line.
   
   **Fix:** define activity interruption at Brain waits and speech/step boundaries, with propagation on the main activity task. Raising from a reader would trigger `internal_error`; raising from the filler can be swallowed by its broad exception handler. Also clear speech cancellation state: cancelling a synthesising filler after `skip_current()` can leave [Hub._skip_next](E:/GitHub/scil/Leafi/leafi/core/hub.py:282) set and skip the following prompt.

5. **Medium — D7:177–183: refusing or ignoring a want can strand the demand-driven reader.** During a quiet listen, send a kind outside the menu. `_deliver` refuses it without sending an item; the panel reader returns to waiting for `_request`. A subsequent panel `/stop` remains in the device queue until another listen requests that source. Ignoring a want inside a setup listen similarly needs to request another read. [Readers do not automatically read again](E:/GitHub/scil/Leafi/leafi/study/harness/inputs.py:145).
   
   **Fix:** explicitly rearm the source whenever an input is consumed without satisfying the outstanding listen, including refusals and setup deferrals.

6. **Medium — D7:177–183: setup deferral cannot pass the stated admission test.** `/do break` at identification or book setup is supposed to remain pending for the first boundary. But `want_ok` requires membership in the *last boundary’s menu*, and [the first menu is computed only after setup](E:/GitHub/scil/Leafi/leafi/study/harness/loop.py:374). The request is refused before the setup-specific branch can retain it.
   
   **Fix:** specify separate setup admission: validate the kind syntactically, defer it, then validate constructibility against the first actual menu. Define what happens if it is unavailable then.

7. **High — D8:201–211: `_explain` is an omitted evidence-writing path.** D1’s authenticated `/input` endpoint accepts `/explain fox`; `parse_typed` recognizes it. During reading, [the explain branch](E:/GitHub/scil/Leafi/leafi/study/harness/activities.py:336) calls `_explain`, which creates a knowledge item and an `explain` encounter. D8 excludes free panel reading but does not exclude this control, and the scoring predicate is never consulted.
   
   **Fix:** enforce the action allow-list at the device boundary, or explicitly refuse panel explanations before this writer. Make `/say` payloads remain answer data through every downstream parser; unwrapping and reparsing them would reopen this path and spoken-command paths such as `good`.

8. **Medium — D8:214–217: `_store_utterance` cannot provide the promised complete records.** Panel `/do` raises before an activity calls `_store_utterance`; Stop and playback Skip return inside `_deliver`; negotiation never calls it; reading skips and several refusal/noop paths also bypass it. Those lines therefore get neither the promised utterance row nor the proposed count. Additionally, [finalize](E:/GitHub/scil/Leafi/leafi/study/harness/loop.py:218) replaces the session summary, so an independently written boundary count would be lost unless merged.
   
   **Fix:** specify one exactly-once panel recording path with activity/boundary attribution, independent of evidence writers. Preserve boundary counts through finalization and avoid double-counting lines that later reach existing storage calls.

9. **Medium — D8:198–199: the unified predicate changes existing voice scoring.** For `Utterance(text="fox", words=[], typed=False)`, current `scoring.confident` returns false; the proposed “every word confident” expression returns true because `all([])` is true. This can turn an unavailable teach/recall response into scored evidence or a `judge` call. I confirmed the predicate difference locally. [The existing scoring guard](E:/GitHub/scil/Leafi/leafi/study/brain/scoring.py:28) deliberately includes `bool(u.words)`.
   
   **Fix:** require nonempty words for voice evidence. State the resulting tightening of the activities predicate explicitly; ordinary typed console answers remain eligible.

10. **Medium — D1/D3/D5:56–58, 111–126, 146–152: refresh hooks omit important transitions, especially ending.** A trailing refresh scheduled at speech start can fire while a long line is still speaking; [the eventual `speaking=False`](E:/GitHub/scil/Leafi/leafi/study/harness/inputs.py:319) schedules nothing. During `deliver`, all input-reader tasks have already been cancelled, yet the server remains live until runner cleanup. A normal end also leaves `latch.terminal=None`. The panel can show actionable controls and accept `/do` with 202 although nobody will consume it.
    
    **Fix:** publish explicit lifecycle and input-acceptance state before cancelling readers; reject actions during finalization/delivery. Mark dirty on speech completion, listening transitions and panel-fate changes, rather than relying on a later display to reveal them.

11. **Medium — D3:102–128: the memory snapshot is missing both a field and a synchronization rule.** `World` and `Revision` do not hold the printed page number; current callers SELECT it. More significantly, practice settlement updates serialized reading state through [rows._settle_token](E:/GitHub/scil/Leafi/leafi/study/harness/rows.py:76), leaving `w.state` unchanged. After practice resolves a candidate, a fresh memory-only snapshot can still display that token as a candidate. Republishing does not fix stale source state.
    
    **Fix:** cache the printed number during page acquisition/opening, and synchronize the in-memory reading state when practice or cycle closure settles tokens. Add snapshot checks after settlement, not only activity start/end.

12. **Medium — D1:50–52: the fault-reporting path can itself terminate the session.** A bind/file failure is supposed to become `alerts.insert(...)`, but [alerts.insert](E:/GitHub/scil/Leafi/leafi/core/alerts.py:85) is a fallible database write. If the store is busy, reporting the panel fault can raise out of `on_built` or a reader. Reporting directly from a serving thread would also violate the proposed thread boundary.
    
    **Fix:** marshal fault handling to the loop, disable the device first, and make alert insertion independently best-effort with logging fallback. Include failure of the alert write in the containment test.

13. **Medium — D2:86–91: excluding the panel from selection does not ensure a usable main listener exists.** With the panel as the only configured Listener/Face, [app.build’s console fallback](E:/GitHub/scil/Leafi/leafi/app.py:71) sees nonempty slots and creates no console. Skipping the panel during selection then either leaves no candidate or allows [Hub.listener’s fallback](E:/GitHub/scil/Leafi/leafi/core/hub.py:167) to select it anyway.
    
    **Fix:** base console fallback on the existence of a *main-capable* listener, and enforce the invariant at the final Hub selection path. Test panel-only configuration as well as console-plus-panel ordering.
