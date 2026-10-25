# Session panel design rev 3: codex round on D7

Reviewer: codex `gpt-6-astra`, effort high, read-only, 2026-10-25, prompt `reviews/prompts/session-panel-rev3.md`. Output as returned (the final message). Answered by rev 4.

**D7 still needs changes.** Nested cancellation is viable, but the existing `/stop` path does not establish safety for continuing the session.

I traced all activity handlers and their callees, and ran isolated, in-memory checks without hardware or file edits. The installed AnyIO is **4.14.2**, not 4.14.0; I also checked the upstream 4.14.0 cancellation implementation.

1. **High — D7:205–213: the activity being cancelled can change during `stop_speaking()`.**  
   The specified sequence reads `latch.activity_scope`, awaits speech shutdown, then reads that mutable field again. While a Mouth’s `stop()` is awaited, the old activity can finish, clear its scope, and enter negotiation or another activity. The reader then either calls `None.cancel()`—causing `Latch.spawn.guarded` to terminate the session—or cancels the new activity. Two sources issuing wants make this race easier to reach.

   **Fix:** capture the target activity/scope before yielding and make interruption target that identity. Coordinate speech shutdown with the activity’s exit so the old request cannot stop or cancel its successor. Clear the registered scope in `finally`, including exceptional exits. [D7](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-25-study-session-panel-design.md:205), [speech shutdown](/E:/GitHub/scil/Leafi/leafi/core/hub.py:277)

2. **High — D7 cancel safety: an acknowledged Anki answer can remain locally unfinished for the rest of the session.**  
   `answerCards` succeeds → `review_answers.state='acked'` → `/do` cancels either await in `_record_state()`. The next boundary’s `reconcile()` only examines `sent` answers, and `World.refresh()` normally already set `cards_observed=True`. Consequently the acknowledged answer gets no `card_state` event or item re-fold. Cancellation also bypasses the caller’s retrieval event and `answered += 1`.

   I reproduced `acked`, zero card-state events, and a subsequent `reconcile()` that repaired nothing. This interruption point is **new relative to `StaleInput`**: a stale listen cannot interrupt `anki.answer()`.

   **Fix:** preserve an explicit obligation to finish local acknowledgement processing, retry it before subsequent decisions, and define review progress separately for submitted, acknowledged and uncertain answers. Do not replay `answerCards`. [answer and state recording](/E:/GitHub/scil/Leafi/leafi/study/anki.py:262), [boundary refresh](/E:/GitHub/scil/Leafi/leafi/study/harness/world.py:50)

3. **Medium — D7:216–218: reading does not resume “as after `aborted_stale`.”**  
   `read_listen` calls `end_page_read()` in its `finally`. More importantly, `aborted_stale` triggers a **same-cycle continuation**, whereas `completed, ended_by=do` returns to a boundary. The next boundary-chosen reading calls `ensure_cycle()`, closes the previous cycle and opens a fresh page read.

   In the in-memory check, reading “The fox” from “The fox ran home” left cursors at 2 with two provisional tokens. Boundary reopening produced a new cycle/read with cursors at 0 and those tokens unattempted. Existing candidates are also settled when the old cycle closes. No sentence is directly skipped by `/do`, but partial reading and self-correction context are not resumed.

   **Fix:** explicitly decide how suspended reading resumes. Either provide the promised continuation semantics, consistently with ADR-0013’s cycle rules, or specify and test sentence restart and candidate settlement. [reading cleanup](/E:/GitHub/scil/Leafi/leafi/study/harness/activities.py:355), [cycle creation](/E:/GitHub/scil/Leafi/leafi/study/harness/world.py:273), [continuations](/E:/GitHub/scil/Leafi/leafi/study/harness/loop.py:405)

4. **Medium — D7:214–222: arbitrary-await cancellation needs step-level commit rules, not only outcome counters.**  
   Several interrupted steps leave effects that the next activity cannot reconstruct:
   
   - `acquire_page()` removes `pending` before awaiting acquisition. Cancelling OCR can forget the requested page.
   - `_reading_utterance()` persists alignment, then awaits `line_skipped`, then completes reached sentences. Cancellation leaves those completion transitions unapplied.
   - An accepted hint awaits speaking the word before recording `supply`. The word may have been delivered without its supplied-token evidence.
   - Quiz and teach/recall record an answer, then await feedback before writing retrievals/encounters. A child can hear confirmation but have no corresponding mastery evidence. Teach/recall additionally append their result before that feedback.

   These are new interruption positions relative to stale listens, except that page acquisition already has a related pending-request loss at its confirmation listen.

   **Fix:** define each step’s commit point. Perform synchronous evidence/state/progress changes together before optional feedback; retain or restore an unfinished page request; give hint delivery an explicit interrupted outcome. Shielding an entire activity would defeat `/do`. [reading transitions](/E:/GitHub/scil/Leafi/leafi/study/harness/activities.py:141), [hint](/E:/GitHub/scil/Leafi/leafi/study/harness/activities.py:225), [scored feedback](/E:/GitHub/scil/Leafi/leafi/study/harness/activities.py:816)

5. **Medium — D7:226–231: boundary waits are outside the activity scope and have no wake-up.**  
   `generate` runs during `construct()`, before `run_activity`; `sequence` is also boundary work. A want there merely sets the slot: it cancels neither the Brain call nor its filler. During boundary playback or listening, it similarly waits for playback and/or the listen timeout.

   In the low autonomy bands, a want arriving during the last permitted silence can reach `return wait_or_end(s)` without another pass. Checking `return Run(a)` alone does not cover that exit; an unnecessary wait—or session end after a previous wait—can win over the request. Also, `scoring.item_used()` lacks `controls_only`: after a console answer, that console reader need not be armed during the judge call.

   **Fix:** give boundary waits an explicit interruption/wake mechanism, check pending wants before **every** boundary exit, including wait/end and named-choice construction, and keep control readers armed during judge calls. Retain the single `Want` payload; a wake signal need not duplicate it. [negotiation](/E:/GitHub/scil/Leafi/leafi/study/harness/negotiate.py:121), [boundary generation](/E:/GitHub/scil/Leafi/leafi/study/brain/generate.py:77), [judge](/E:/GitHub/scil/Leafi/leafi/study/brain/scoring.py:71)

6. **Medium — D7 Brain cancellation loses page controls already collected by `controls_only`.**  
   During an answer wait: `/page 12` is queued → `/do break` cancels → `controls_only` moves the page into `taken` in its `finally` → cancellation bypasses `_answer`’s subsequent loop over `taken`. The page exists in neither the input queue nor `late` nor `World.pending`.

   I reproduced that exact state. Ordinary `StaleInput` is consumed later by `listen()`, after this dispatch would have run, so this loss is new.

   **Fix:** on exceptional exit, preserve collected page controls in a session-owned queue or dispatch them in cancellation-safe cleanup. Define skip disposal separately. [collector cleanup](/E:/GitHub/scil/Leafi/leafi/study/harness/inputs.py:253), [caller dispatch](/E:/GitHub/scil/Leafi/leafi/study/harness/activities.py:708)

7. **High — D7 “both finish paths” does not yet guarantee durable or budget-visible progress.**  
   There are two gaps in the existing finish machinery:

   - The normal end’s `await busy.retry(...)` is outside the cancellation handler. `/stop` during a busy retry leaves the row `running`, with no outcome and no `pending_rows` entry. I reproduced this. `finalize()` does not repair that row.
   - When either finish path puts an outcome in `pending_rows`, the next boundary’s Ledger still reads the old database outcome. `_flush_pending()` runs when starting the **already constructed** next activity, too late to constrain its selection. A three-question quiz can therefore leave another quiz constructed against an unspent budget.

   These are existing weaknesses that D7’s new progress guarantee relies upon.

   **Fix:** retain the complete finish record before any cancellable retry; make cancellation leave it flushable; and make pending completed outcomes visible to budgeting before menu construction. Ensure the log, queued finish and stored outcome use the same snapshot. [finish paths](/E:/GitHub/scil/Leafi/leafi/study/harness/loop.py:160), [Ledger](/E:/GitHub/scil/Leafi/leafi/study/harness/ledger.py:41)

8. **Medium — D7:219–222: the stated summary consumer does not exist, and other consumed outcome fields are omitted.**  
   `records.summary()` never reads activity outcomes. Merging `progress` cannot make quiz, teaching, recall or card counts appear there. Also omitted from progress are reading/read-aloud `sentences` and `page_read_id`, and learner-question `questions`/`answered`; these scalar fields are consumed by `notes._activity_leaves()`.

   **Fix:** specify the intended summary aggregation explicitly and preserve all completed scalar outcomes used downstream, not just budget counters. Keep mastery evidence distinct: `item_status` reads retrieval/status-event rows, so progress cannot substitute for missing evidence. [summary](/E:/GitHub/scil/Leafi/leafi/study/records.py:88), [notes](/E:/GitHub/scil/Leafi/leafi/study/brain/notes.py:97)

9. **Medium — D7:223–225: clearing `_skip_next` on the generation bump is insufficient; clearing it after shutdown can lose a valid skip.**  
   Clearing at the bump is followed by `stop_speaking()` calling `skip_current()`. If synthesis holds the lock and nothing is playing, that call sets `_skip_next=True` again. Cancelling synthesis then bypasses the playback `finally` that clears it; the next prompt is skipped. The in-memory check confirmed the flag is rearmed.

   Moving the clear after the awaited shutdown introduces another race: a new-generation prompt can start, receive a console skip during synthesis, and then have that valid skip erased by the older shutdown.

   **Fix:** separate “invalidate/stop this generation” from “skip the current clip,” or associate the pending skip with its generation/utterance. Clearing an **old-generation** skip at the bump itself is safe; an unconditional late clear is not. [Hub implementation](/E:/GitHub/scil/Leafi/leafi/core/hub.py:277)

The complete suspension-point inventory follows. “Existing” means reachable through `StaleInput` at a listen; “new” means cancellation can interrupt earlier work that previously ran through to that listen.

| Activity/path | Write sequence across suspension; what the next activity sees | Existing versus new |
|---|---|---|
| Both reading kinds: `_open` / acquisition | Close previous cycle and open new cycle → consume pending request → await camera/OCR, confirmation or page input → open page read. Cancellation can leave an empty new cycle, old `World` page state and no pending request. | Confirmation/page-input listens: existing, not fully repaired. OCR and prompt playback: new. |
| `read_listen`: ordinary alignment | Utterance + observations + candidates + state are written synchronously; later listens see that state. | Existing and handled by same-cycle stale continuation. D7’s boundary reopening differs, finding 3. |
| `read_listen`: recovery speech | Persist alignment → await `reposition` or `line_skipped`. Reposition has no later completion work; `line_skipped` precedes `_complete_reached` and typed line-end completion. | New intra-step cut; finding 4. |
| `read_listen`: hint | Await offer/listen, then await word delivery → write control utterance, supplied token/candidate and sentence completion synchronously. | Stale at hint listen writes nothing. Cancellation during word delivery is new. |
| `read_listen`: explain | Store question → await two lines → upsert item + encounter synchronously. Cancellation leaves the question without the encounter. | New intra-step cut; abandonment needs an explicit policy. No cancellation between the two synchronous knowledge writes. |
| `read_listen`: correction/back/page | Correction writes revision, invalidation, state and epoch before thanks; unlocated correction is written between two feedback lines. Page request is set synchronously before return. Back normally changes state synchronously; its empty-page warning precedes the change. | New cuts can omit feedback or an unfinished operation; completed synchronous changes remain coherent. |
| `read_listen`: cleanup | Synchronously clears `page_open`, optionally completes the current sentence **only for terminal `stop`**, and persists page-read counts/state. | `/do` does not invoke stop’s sentence completion. Cleanup also runs on stale input. |
| `practise_errors`: scoring | Store practice utterance → await pronunciation score → write practice result → possibly await second-try prompt/listen → settle candidate/token and optionally create pronunciation knowledge. | Cancellation inside scoring is new: utterance but no practice row. Between attempts, a recorded first attempt with an open candidate is already stale-reachable. |
| `practise_errors`: settlement | Last practice row → `_finish_candidate` → token settlement → `done` update are synchronous, then feedback is awaited. | There is **no cancellable await** between the final attempt row and settlement. An earlier unfinished candidate consumes the budget; it resumes only if selectable, otherwise cycle closure settles it. |
| `review_anki`: fetching | `deck_for` may persist settings → await due-card queries. | New cut, but the deck setting is a complete reusable write. |
| `review_anki`: answering | Answer utterance + pending/sent review row → await `answerCards` → ack → await review/card details → state/re-fold → retrieval + count. | `sent` uncertainty has reconciliation. The ack-to-state gap does not; finding 2. |
| `read_aloud` | Open cycle/read → await intro and each sentence → increment local `said`. Reading state is not advanced by speaking. | Stale cannot interrupt the sentence loop because it never listens. `/do` can, but completed speech counts need progress. |
| `quiz` | Previous question effects → await next prompt/listen; current answer → await feedback → retrievals/encounters + result append. | Completed prior questions are stale-reachable and recoverable through progress. Current feedback cut is new. |
| `teach_items` / `recall_items` | Await teaching/prompt/listen; store answer → optional judge → append result → await feedback → retrieval/encounter. `/know` writes ignore before acknowledgement. | Prior completed items: existing. Judge/feedback cuts: new. Ignore remains committed even if acknowledgement is cut. |
| `learner_questions` | Store question and increment asked → await Brain/filler → await answer speech → increment answered. | Prior completed turns: existing. Current question/answer cuts: new; retain separate asked/answered counts. |
| `add_cards` | Check and queue all accepted outbox rows synchronously → await acknowledgement line → return counts/flags/rejections. | New cut after durable queuing. Cards remain excluded from future cardable selection; progress must already contain their count. |
| `break` / `wait` / `end` | Break/wait have no domain writes across their speech/listens. End returns synchronously. | No additional domain repair; lifecycle/outcome writing still matters. |
| Brain generation/calls/filler | Boundary generation updates cache only after return. Calls retain transmission charges; cancellation marks backend reset and writes audit under bounded shielding, retaining busy audit rows. Filler joins its task group on exit. | Call audit/reset handling is already designed for cancellation. Boundary scope coverage and collected controls remain findings 5–6. |

`pages`, `knowledge`, `rows` and the local scoring functions contain no awaits inside their write groups. They can fail for database reasons, but activity cancellation cannot split those synchronous groups. `sync_outbox()` runs after the session, outside the proposed activity scope.

For the requested hand executions:

| Scenario | Result under D7 as written |
|---|---|
| Boundary, autonomy below `bands.ask` | Want during choices playback/listen sets the slot; speech/listen continues. A later pass takes it, but the final-silence wait/end exit needs protection. |
| Boundary, ask band | Same, potentially including both rationale and question playback before the slot is reconsidered. |
| Boundary, argue band | Playback/listen continues; the proposed check prevents the old no-objection activity from starting once the listen returns. |
| Boundary, announce band | Announcement continues; the proposed final check restarts construction afterward. No listen is involved. |
| Quiz question four after three completed answers | Correct if progress was updated after each committed question and the finish record becomes budget-visible. The fourth question contributes nothing if interrupted before its commit point. |
| Mid-sentence reading, text or voice, silent child | Cancellation ends the listen without a skip or idle timeout. State is saved; subsequent boundary reading restarts the sentence rather than using stale continuation semantics. |
| Activity answer wait or its filler | Cancellation reaches the call and filler; backend reset/audit handling applies. Collected page controls can be lost. |
| Boundary generation or its filler | No activity scope exists; the call/filler continues. |
| `read_aloud` sentence playback | Can be interrupted without another listen, subject to the scope/speech race. Already spoken sentence counts are currently omitted from progress. |
| Two wants | Two received before consumption reduce to the latest slot. During speech shutdown or wanted-activity construction, target identity and checks on every exit are required to prevent an earlier request from starting/cancelling the wrong activity. |
| Setup prompt | Deferral works: kind validation and rearming leave setup waiting for its real answer. Constructibility is checked at the first boundary. |
| `/stop` immediately afterward | Once the terminal latch is set, session cancellation must win. Rearming is necessary to receive it; a blocked speech-shutdown await can delay same-source delivery. |
| Want during `finish_now` | Its synchronous database write cannot interleave with another loop task. Delivery occurs afterward and should target the boundary. |
| Want during normal finish retry | Scope is cleared, so it becomes a boundary want. A following `/stop` exposes finding 7. |
| Session cancellation already underway | Inner cancellation must not be converted to successful `/do` completion. |

The nested-scope mechanism itself passes the AnyIO check. An inner scope absorbs its own cancellation only when no cancelled parent is visible; ordinary errors remain errors, including within exception groups. This rule is present in both the installed code and [AnyIO 4.14.0](https://raw.githubusercontent.com/agronholm/anyio/4.14.0/src/anyio/_backends/_asyncio.py).

Placement matters: the activity scope must exit **before** the existing `except (Terminal, cancelled)` handler sees an activity-only cancellation. Otherwise that handler calls `finish_now(latch.status())` with no terminal reason, producing `internal_error`. Keep terminal handling outside the inner scope; let session cancellation propagate to the session scope. `except* Terminal` handles grouped terminal exceptions, while `except* Exception` must continue handling genuine failures. `latch.terminal is None` alone is not proof that an outer scope has not been cancelled.

Finally, the exact progress consumers are:

| Proposed progress | Ledger | `records.summary()` |
|---|---|---|
| Quiz `questions` | Cycle quiz budget | Not read |
| Quiz `results` | Not read | Not read |
| Teach `items` | Cycle and session new-item budgets | Not read |
| Recall `items` | Not read | Not read |
| Add-card `cards` | Session card budget | Not read |
| Review `cards` | Not read | Not read |

Both finish paths must persist these consistently, but persistence alone does not add summary consumers. Notes read scalar outcome fields; sequence currently reads the last activity’s ID/kind/status and gains D8’s two fields; mastery reads evidence rows. These are separate obligations.

No files were edited.
