# Codex implementation review, round 1 (gpt-6-astra, reasoning high, read-only)

Run 2026-10-20 over the diff 3e0b52c..2c2a52c (the first Opus implementation run; the /back fix in 31e30bc landed after the snapshot, so finding 12 was already resolved). Prompt: prompts/impl-round-1.md. Each finding is verified with a failing test before it is fixed (codex-review skill).

Findings refer to the supplied diff snapshot. Its 25 alignment tests pass; targeted in-memory reproductions exposed the failures below. I did not run the full suite.

1. **[P1] Cloud TTS bypasses redaction — `leafi/services/tts/edge.py:29`.**  
   Edge receives raw speech text without applying `REDACT_TERMS` or checking its origin. With `TTS_BACKEND_EN=edge`, explanation prompts and correction acknowledgements can upload learner names or learner-supplied text despite correct Brain redaction.

   **Repro:** Configure a name for redaction, include it on the page, and request its explanation; `explain_wait` sends the unredacted name to TTS. **Fix:** Enforce privacy at the cloud speech boundary, keeping learner-originated content local; extend the privacy test beyond its current mouthless, `httpx`-only setup.

2. **[P1] A rejected second launch modifies the active session — `leafi/study/session.py:140`.**  
   Startup closes every unfinished session before acquiring the speech lease. Consequently, a second process that is subsequently rejected has already ended the live session and changed its candidates to `unsure(interrupted)`, potentially making ongoing practice raise `IllegalTransition`.

   **Repro:** Leave a session with an open candidate, make lease acquisition raise `LeaseHeld`, and call `run()` again; the original session and miscue are nevertheless modified. **Fix:** Establish exclusive ownership before stale-session cleanup and distinguish live owners from interrupted sessions.

3. **[P1] Corrections disconnect candidates from their evidence — `leafi/study/miscues.py:55`.**  
   Candidate lookup compares current token indexes with immutable indexes from the miscue’s original revision. A correction that changes earlier token counts therefore makes later candidates disappear from lookup or associates them with another word’s miscue.

   **Repro:** Read “The dog red” against “The dog ran far,” then replace “The” with “The small”; `ran` moves to index 3 while its row remains at index 2, and a correct reread leaves that row open. **Fix:** Resolve candidates through their revision and mapped character spans, or preserve stable miscue references in reading state.

4. **[P1] Lost-add recovery adopts parent edits as Leafi’s baseline — `leafi/study/anki.py:109`.**  
   On a dedupe hit, the code records every current remote field as `last_acked_fields`, including edits made by the parent after the original add. A subsequent update then regards those parent edits as Leafi-owned values and overwrites them.

   **Repro:** Lose the `addNote` acknowledgement, edit the remote back field, retry synchronization, then add a new explanation; the parent’s wording is overwritten without a conflict. **Fix:** Persist the attempted field values before sending and preserve differing remote values during dedupe recovery.

5. **[P1] CHECK records commands as incorrect answers — `leafi/study/session.py:726`.**  
   Parsed controls outside the explicitly handled subset fall through into answer storage and grading. Commands such as `/explain fox` consequently create an incorrect-comprehension encounter without the learner having supplied an answer.

   **Repro:** At a CHECK question, enter `/explain fox`; an answer row and `trigger='check'` encounter are written. **Fix:** Dispatch every control before grading, giving inapplicable controls the required no-op response and continuing to await an answer.

6. **[P1] Cancelling speech leaves playback running — `leafi/core/hub.py:227`.**  
   Cancellation of `Hub.say()` while awaiting playback bypasses all child-task and device cleanup. Its lock is released and `ListeningGate` resumes with zero drain while the original playback task remains active, allowing feedback and overlapping speech.

   **Repro:** Start `gate.speak()` with a hanging fake Mouth and cancel its task; the gate opens, `stop()` is never called, and playback remains pending. **Fix:** Put bounded device shutdown and child-task cleanup in cancellation-safe `finally` handling before releasing speech ownership or reopening listening.

7. **[P1] The advertised console playback cancellation is unwired — `leafi/study/session.py:107`.**  
   The session awaits speech synchronously and has no concurrent console-control consumer. `Hub.stop_speaking()` is only exercised directly by tests, so typing `/stop` during playback cannot perform the cancellation promised by ADR-0013 and the spoken hint.

   **Repro:** Start a voice session with a slow fake Mouth and submit `/stop` through its Console device during playback; speech continues and the selected voice Listener never consumes that console command. **Fix:** Add a persistent console/Face control dispatcher that interrupts playback and routes stop through settlement and WRAP.

8. **[P1] A listening timeout permanently closes capture — `leafi/services/asr/__init__.py:79`.**  
   `wait_for()` cancels the pending `__anext__()` on timeout, closing an async-generator Ear such as `LocalPcDevice.listen()`. The closed iterator remains cached, so subsequent listening calls return immediately without accepting new speech.

   **Repro:** Use a queue-backed async-generator Ear, let one call time out, enqueue speech, and listen again; the generator is closed and the speech remains queued. **Fix:** Keep capture in a persistent producer task and apply input deadlines to queue reads without cancelling the capture iterator.

9. **[P1] Concurrent speech reopens the listening gate prematurely — `leafi/core/hub.py:276`.**  
   Each caller pauses before entering the Hub serializer and independently resumes after its own speech finishes. Thus the first caller reopens listening while the second caller’s queued speech starts, allowing that speech to be recognized as learner input.

   **Repro:** Run two `gate.speak()` calls concurrently with the second clip longer than the drain delay; the event order is pause, pause, first playback, resume, second playback. **Fix:** Serialize the complete pause/speak/drain/resume operation or maintain shared gate ownership across queued speech.

10. **[P1] Expected words override stop and skip — `leafi/study/session.py:376`, `leafi/study/session.py:577`.**  
    READ suppresses spoken controls that resemble nearby page text, and PRACTICE suppresses controls matching the practised word. This contradicts ADR-0013’s control precedence and “skip always,” making an attempted escape count as reading or a successful retry.

    **Repro:** Say “stop” on a page beginning “Stop and look,” or “skip” while practising `skip`; the latter becomes `withdrawn(practice)` rather than `unsure(skipped)`. **Fix:** Apply control precedence before reading/retry interpretation and replace the test that currently endorses page-text precedence.

11. **[P2] Insertion boundaries corrupt cross-revision spans — `leafi/study/pages.py:31`.**  
    A span starting exactly at an insertion point maps to the insertion’s start instead of following the inserted text. Later corrections to that inserted text therefore overlap—and invalidate—unrelated historical miscues.

    **Repro:** Record a miscue for `cat` in “The cat ran,” insert “big ” at offset 4, then correct `big`; the old `cat` span maps to `[4,11)` instead of `[8,11)` and is invalidated. **Fix:** Give span boundaries explicit insertion affinity and test cross-revision invalidation across insertions.

12. **[P2] `/back` selects the next sentence at a boundary — `leafi/study/alignment.py:413`.**  
    At an interior sentence start, `back()` selects the sentence containing `pcur` rather than the required sentence containing `pcur - 1`. Immediately after completing a sentence, `/back 1` consequently leaves that sentence completed and fails to reopen it.

    **Repro:** Complete “The dog ran” in “The dog ran. The cat sat,” then call `back(state, 1)`; the cursor stays at 3 instead of returning to 0. **Fix:** Implement ADR-0013’s boundary rule and correct `tests/test_alignment.py:125`, which currently asserts the opposite behavior.

13. **[P2] Empty typed lines cannot complete a sentence — `leafi/study/session.py:474`.**  
    Empty input reaches alignment first and returns through the unanchored branch before typed-line completion is considered. Pressing Enter therefore fails to finish a near-complete sentence, and pressing it twice can incorrectly enter REPOSITION.

    **Repro:** On “The dog ran far,” enter “The dog” and then an empty line; sentence 1 remains incomplete despite satisfying the pause-completion condition. **Fix:** Process empty typed sentence-ending input before unanchored alignment handling.

14. **[P2] Page commands lose their text file in PRACTICE and CHECK — `leafi/study/session.py:584`, `leafi/study/session.py:718`.**  
    These branches construct `PageRequest` without reading `ctl.path`, unlike the READ handler. The CHECK branch additionally leaves the previous page read unfinished, so identical page commands behave differently depending on timing.

    **Repro:** During practice or a CHECK question, enter `/page 2 --text <valid-file>`; the request reaches FIND_PAGE with `text=None`, and CHECK leaves the old `ended_at` null. **Fix:** Share page-command parsing and departure handling across states.

15. **[P2] Valid long page text crashes enrichment — `leafi/study/session.py:706`.**  
    `page_window()` limits sentence count but not character count, while `BrainRequest` rejects windows exceeding 900 characters. Construction occurs outside `enrich()`’s exception handling, so ordinary page text can abort CHECK or EXPLAIN instead of falling back.

    **Repro:** Supply one sentence containing 110 repetitions of “elephant” and reach CHECK; request construction raises `ValueError`. **Fix:** Bound the selected window and handle request-validation failure through the unavailable fallback.

16. **[P2] Item creation and outbox creation are not atomic — `leafi/study/knowledge.py:33`.**  
    The knowledge-item insert and its outbox insert are separate autocommit statements. Failure between them leaves a permanent unscheduled item because subsequent `upsert_item()` calls return the existing row without repairing its missing outbox operation.

    **Repro:** Use SQLite’s authorizer to reject the outbox insert, restore permission, and retry; one item remains with zero outbox rows. **Fix:** Create the item and initial outbox operation in one transaction.

17. **[P2] Difficulty updates are deferred beyond their evidence transaction — `leafi/study/miscues.py:51`, `leafi/study/knowledge.py:47`.**  
    Normal miscue transitions and encounter writes do not recompute Difficulties in the transaction changing their inputs. Practice consequently uses stale weights until wrap, and the tests conceal this integration defect by explicitly calling recomputation themselves.

    **Repro:** Create the third distinct session’s unsure evidence and immediately inspect practice ordering; its watch row is absent until an explicit recomputation. **Fix:** Update evidence, dependent Difficulties, and associated state atomically, then test ordering through the actual mutation path.

18. **[P2] Reconciled reviews never update knowledge status — `leafi/study/anki.py:243`.**  
    Lost-response reconciliation changes `review_answers` to `acked` without applying the knowledge-item transition performed by the normal acknowledgement path. An acknowledged first review can therefore leave an item `new`, and a reconciled lapse can leave it `known`.

    **Repro:** Lose the first successful `answerCards` response for a linked item and reconcile; the answer becomes `acked` while the item remains `new`. **Fix:** Apply an idempotent knowledge-status transition when reconciliation establishes the review outcome.

19. **[P2] Alignment omits the boundary cost for wholly deleted sentences — `leafi/study/alignment.py:206`.**  
    Boundary penalties apply only when `c == 1`, although ADR-0013 requires them for every entered sentence with fewer than two aligned tokens. A sentence crossed entirely by deletions has `c == 0`, making some paths artificially cheaper and changing observations and candidates.

    **Repro:** Align `b d a b b a c` against `b a d. c. c a c.`; the implementation selects an insertion/deletion path whose missing boundary charge changes the required tie-break result. **Fix:** Charge the boundary penalty for entered zero-alignment sentences and add an exact-cost/path regression.

20. **[P2] Physical page turns never reach session settlement — `leafi/study/session.py:380`.**  
    READ only awaits utterances and never observes camera page-change events. `PageTracker.changed()` has no session caller, so turning the physical page leaves the old revision active and assesses subsequent speech against it.

    **Repro:** In a voice session, change a fake Eye to another page during READ and continue speaking; no settlement or FIND_PAGE transition occurs. **Fix:** Wire local page-change detection into session control dispatch, settling open candidates and invalidating stale asynchronous work before finding the new page.

**Verdict: not ready for the owner’s first text-mode session.**