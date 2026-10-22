# Codex design review of ADR-0017/0018 v3 (commit 26fe561)

Reviewer: codex-cli 0.155.0, model gpt-6-astra, reasoning high, read-only sandbox, 2026-10-22. Prompt: [prompts/ai-led-v3-codex.md](prompts/ai-led-v3-codex.md). Run in parallel with, and independent of, the code-plan-review of the same commit.

tokens used
136,194
**There are High findings.** I would not implement these ADRs unchanged. The recurring difficulty is preserving guarantees across cancellation, retries, identity changes and deletion—not selecting the libraries.

The two working-tree ADRs match `26fe561`. I kept the review within the permitted material, made no edits, and used small in-memory probes for SQLite locking, executor context propagation and consent matching. The settled owner decisions, §5.1 routing and magpie’s routing trust assumption are not findings.

1. **High — Migration 5 is explicit, but still not atomic or safely restartable.** [0018 §6.2](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:168)

   Hand-execution: take the backup; rebuild and commit tables A and B; fail rebuilding C. The database now contains mixed schemas while `user_version` still says 4. Ordinary openers correctly refuse, but rerunning the migration has no specified way to distinguish this state from an untouched v4 database. Taking another backup can preserve the broken state instead of the original.

   Also, acquiring an exclusive SQLite transaction does **not** establish that no other connection is open: an idle connection can remain open. The lease covers study sessions, not every database user. Consequently, the command cannot establish its stated precondition for backup restoration using the proposed checks.

   This needs a durable migration exclusion mechanism shared by all openers, plus either one atomic migration transaction or an explicit interrupted-migration recovery protocol.

2. **High — Cleanup does not enclose everything that owns the lease.** [0017 §§1–2](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:23)

   Hand-execution: `acquire_lease()` succeeds; recovery or the guest sweep raises. Neither is inside a `try/finally`, so release never runs. Likewise, an unexpected exception during identification or an activity bypasses both `finalize` and the `finally` attached only to `deliver`.

   Cancellation adds another exit: an AnyIO deadline interrupts an await before the following `checkpoint`. Catching `Terminal` does not itself catch or translate that cancellation. The pseudocode never places finalization outside the cancelled scope or in the bounded, shielded cleanup recommended by the harness research.

   The lease-owning region needs one outer cleanup guarantee, including startup failure and native cancellation. Activity closure, stopping playback and releasing the lease must remain reachable through it.

3. **High — The text privacy boundary promises protection that the pseudonymisation pipeline does not supply.** [0018 §§2–3, §7](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:89)

   Two concrete failures:

   - A learner says “I attend Cedar Grove Primary,” but that school is absent from `household_terms`. The second detector is PERSON-only; no school detector or mandatory school registration supplies the missing protection. The text can leave despite §7’s unconditional prohibition.
   - Alice makes a correction containing her name. It immediately becomes shared `page` text, as decided. `forget --learner Alice` deletes her learner row while preserving the correction and revision. Unless her name was independently entered in `household_terms`, subsequent page payloads have lost the list entry that redacted it. PERSON detection does not run on page-class text.

   Immediate correction acceptance can stay. The missing design is how forbidden identifiers remain protected across all text classes and after identity records are deleted.

4. **Medium — Identification can finish in memory while its ownership transaction has failed.** [0017 §7.3](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:285), [0018 §1](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:24)

   Alice confirms; the session re-key gets `SQLITE_BUSY` twice. §7.3 leaves that work to recovery, but does not specify what `identify` returns or whether study may continue. Returning Alice allows learner-owned items and Alice’s privacy settings beside a guest-owned session; remaining a guest contradicts the successful confirmation. Recovery has no durable confirmation record from which to reconstruct the intended re-key.

   There is also a race with `forget`: Alice can become `forgetting` while confirmation awaits a reply. Excluding her from the initial candidate list is insufficient; the final re-key transaction must conditionally recheck that state. Successful durable re-key must precede adopting the learner in memory.

5. **Medium — The guest end-state table still leaves a clean early termination dependent on unspecified recovery behaviour.** [0018 §1](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:48), [0017 §2](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:56)

   The hand-executed states are:

   | Path | Result |
   |---|---|
   | Learner confirmed and re-key committed | Session belongs to learner; empty guest deleted. |
   | Explicitly declined | Finalization deletes guest history and retains anonymous counts. |
   | Unconfirmed after two attempts | Expiry is persisted; sweep can delete after seven days. |
   | Crash before identification returns | Open session can be recovered and assigned expiry from session start. |
   | Stop/deadline/lease loss before identification returns, with successful finalization | Session becomes ended, but the table assigns missing reason/expiry repair to **startup recovery**. |

   The existing [`close_stale_sessions`](/E:/GitHub/scil/Leafi/leafi/study/records.py:17) selects only open sessions. Following that selection leaves the last case with NULL expiry; the daily sweep never matches it. Either finalization must assign these fields, or recovery must explicitly include already-ended, reasonless guests.

   The startup ordering itself is correct. Sweeping before recovery would have spared expired guests whose sessions were still open; v3 fixes that.

6. **Medium — “Forget” conflicts with its correction constraint and does not cover every derived copy.** [0018 §§1, 3](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:91)

   A voice/text correction requires non-NULL `source_learner_id`, but forgetting its learner explicitly sets that field to NULL. Enforcing the stated constraint makes forgetting fail; the constraint needs an explicit `forgotten` exception.

   Separately, suppose B’s encounter explanation or generated Anki card derives from A’s answer and carries sources `[A, B]`. Cross-source deletion names notes, assessments and Brain calls, but not those encounter/card fields. They survive forgetting A. Unknown-source filtering prevents subsequent cloud transmission, but does not fulfill deletion of the local derived content.

7. **Medium — Construction can bypass content ownership, and fallback does not advance through the default policy.** [0017 §§2.1, 3.3](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:145)

   With `policy.content.read_aloud=code`, a Brain decision can nevertheless supply `translate`, range and other parameters: construction uses parameters **from the spec first**, consulting the content owner only for missing ones. That makes ownership a default-filling rule rather than the declared owner of parameters and text.

   A second trace: reordered policy is `teach_items → read_listen → end`; generation is routable but times out. `default_spec` returns teaching, construction rejects it, and `first_constructible` proceeds to the appended `END`. It never asks for the next default-policy step, although reading remains runnable.

   The explicit **no Brain** case is covered: a Brain-owned default step is skipped. The unresolved case is a Brain that exists but cannot produce usable content within this negotiation.

8. **Medium — Exploration state and actual execution are not distinguished well enough for reliable evaluation.** [0017 §§3.3, 7.2, 9](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:147)

   Hand-execution: the first random draw explores and sets `s.explored=True`; the next draw selects the Brain. Nothing resets the flag. The logging contract does not specify another boundary-local assignment record.

   Further, Brain failure can execute the default policy, and learner refusal can execute a different choice. One `decided_by` value cannot preserve both randomized assignment and actual execution.

   Reordering the default to put reading before practice also has a real consequence: selecting another boundary reading closes the previous cycle and settles its unpractised candidates. That is allowed, but evaluation must record which policy version produced it.

   Keep the exploration share; record assignment, assignment probability, policy version, executed choice and override reason separately. Comparing whole-session outcomes also needs a defined treatment of the multiple randomized boundaries within that session.

9. **Medium — Teaching can record a low-confidence recognition as a confident retrieval success.** [0017 §§3.4, 7.2](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:174)

   Expected word: “through.” ASR returns “through” with confidence 0.3. `item_said` passes its matching test, and `cloze_word` also passes. There is no stated confidence gate on success, yet the event must use `typed`, `heard_confident` or `acoustic` evidence.

   The confidence rule currently protects against a spoken answer judged **no**, not against false positive retrievals. Repeated low-confidence matches can therefore promote mastery.

   There is also no specified `new → learning` transition for retrieval-only items. The retained implementation obtains that transition from an Anki review, while the new mastery rule only defines `learning → known`.

10. **Medium — Charging transmitted attempts after the call does not enforce the budget.** [0017 §5](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:193), [0018 §2](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:65)

    With one unit remaining, `standard` passes `can_afford`. Egress transmits, gets a retryable failure, and transmits again. The caller then charges two units—after exceeding the limit.

    If cancellation interrupts the call after transmission, the `(response, attempts)` return never arrives and the charge line is skipped entirely.

    The existing 0.5-unit example does correctly skip standard and reach fast. What is missing is authorization/accounting at **each transmission**, including retries and cancelled calls.

11. **Medium — The moment deadline bounds model work, but does not ensure timely fallback or post-session extraction.** [0017 §§5.2, 7.1](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:229)

    Even granting that callers pass the same absolute deadline as the prose requires: decision finishes at 4.8 seconds; generation runs until the six-second PC deadline. There is now no time left for TTS and Mouth startup. If the default policy’s next step also requires generation, it cannot be constructed within that exhausted budget.

    Separately, learner-note extraction is required **after finalization**. A session ending at its deadline cannot use the defined `brain_call`: `min(..., s.deadline)` is already expired. A stopped session retains its terminal latch too.

    The design needs reserved output/fallback time and a separately bounded post-session job, with explicit behaviour when extraction cannot run.

12. **Medium — Recorded DNS addresses do not by themselves solve lost grant context.** [0018 §2](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:69)

    Hand-execution: egress resolves using `to_thread` and installs a context-local grant. The SDK subsequently resolves through `run_in_executor`. That worker has no grant context—I reproduced this locally.

    Returning recorded addresses avoids a second DNS lookup, but the worker still needs a specified way to **find the correct recorded addresses**. A process-wide registry could supply that; an explicit resolver adapter could also do so. Neither is defined, including concurrent sends, expiry and cleanup.

    This is an implementation gap, not proof the approach is impossible. Keep address discovery separate from the context-local authorization checked at connect.

13. **Medium — A correctly granted media consent fails the stated consumption check.** [0018 §4.1](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:123)

    The consent is inserted with `purpose="remote_teacher"`, then used by `egress.send(..., "media", ...)`. Consumption requires the purpose to match. Literal execution changes zero rows and refuses every such request.

    Define the relationship between transport/data purpose and consent purpose, rather than weakening purpose matching. Once that mismatch is resolved, the atomic consumption plus attempt insertion correctly prevents reuse; failed or uncertain delivery correctly leaves consent used.

14. **Medium — The BUSY strategy conflicts with the retained transaction implementation and latency guarantees.** [0017 §7.3](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:285), [storage.py](/E:/GitHub/scil/Leafi/leafi/core/storage.py:157)

    The store has a synchronous five-second busy timeout. One retry can block for roughly ten seconds, including operations described as “never blocks”; an AnyIO deadline cannot interrupt that synchronous wait on the event-loop thread.

    More seriously, if `COMMIT` returns BUSY, `Store.transaction()` resets `_depth` without rolling back—the exception occurs outside its rollback handler. Retrying with `BEGIN IMMEDIATE` then encounters an already-open transaction.

    The proposed retry policy needs compatible transaction cleanup and bounded database waiting, not merely a second attempt.

15. **Medium — The retained Anki paths contradict two new guarantees.** [0017 §§3.1, 7.2](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:110), [0018 §§6.1–6.2](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:164)

    - Selecting **hard** or **easy** cannot be recorded: [`review_answers.ease`](/E:/GitHub/scil/Leafi/leafi/core/storage.py:105) permits only 1 and 3, and [`anki.answer`](/E:/GitHub/scil/Leafi/leafi/study/anki.py:194) rejects other values. Migration 5’s enumerated CHECK changes omit this one.
    - `add_cards` is declared the only outbox writer, but §6.1 retains and learner-scopes [`_queue_update_if_pushed`](/E:/GitHub/scil/Leafi/leafi/study/knowledge.py:56). A new encounter for an existing card still queues an update outside `add_cards`, bypassing that activity’s checks and generated-field ownership.

    Both need explicit migration/writer decisions; they are not merely outdated documentation.

The intended changes to the old cloud boundary are explicitly scheduled in 0018 §6.5, and 0017 explicitly requires ADR-0013 v2 before the reading changes. I have not counted those planned replacements—or the settled owner choices—as contradictions.
