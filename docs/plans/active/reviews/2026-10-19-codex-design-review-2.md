# Codex design review, round 2 (gpt-6-astra, reasoning high, read-only)

Run 2026-10-19 against commit d52fac3. Prompt: see prompts/round-2.md. Resolutions: ADR-0012 and amendments to ADR-0004/0006/0009/0010/0011.

## 1. Status of the five pre-coding priorities

| Priority | Status | Resolving text and remaining limitation |
|---|---|---|
| Privacy contradictions | **Partially resolved** | [ADR-0011](/E:/GitHub/scil/Leafi/docs/adr/0011-egress-policy-and-v1-scope.md:17) enumerates outbound destinations; §32 requires offline reference synthesis and provisioned checkpoints. However, its habit-image exception contradicts the repository boundary, and payload/redaction rules still differ between documents. |
| Assessment semantics | **Partially resolved** | [ADR-0009 §1–6](/E:/GitHub/scil/Leafi/docs/adr/0009-assessment-observations-vs-judgements.md:21) explicitly separates observations from judgements, bounds alignment, defines commitment, and excludes acoustic evidence in text mode. The commitment and candidate rules still mishandle ordinary reading sequences; see section 4. |
| Versioned page text and evidence | **Partially resolved** | [ADR-0010 §1–5](/E:/GitHub/scil/Leafi/docs/adr/0010-page-text-revisions-and-auditable-corrections.md:14) specifies internal page IDs, immutable revisions, revision-relative corrections, assessment references, and invalidation. Missing are the transformations of verified spans, cursors, and assessment references across length-changing revisions. |
| Runtime contracts | **Partially resolved** | [Overview](/E:/GitHub/scil/Leafi/docs/architecture/overview.md:21) names `leafi/app.py` as composition root and introduces `AudioRef`; [device routing](/E:/GitHub/scil/Leafi/docs/architecture/flows/device-routing.md:32) defines half-duplex operation, cancellation, serialization, selection, and the lease. Remaining inconsistencies concern the actual port sketch, playback controls, drain ownership, and cancellation of delayed results. |
| Decisive prototypes before dependent implementation | **Resolved for the narrowed S1, at design level** | [ADR-0011](/E:/GitHub/scil/Leafi/docs/adr/0011-egress-policy-and-v1-scope.md:38) makes S1 static/mock speech; [the prototype schedule](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-19-leafi-book-study.md:84) puts P-3 before real OCR, P-1/P-5/P-6 before S3, and P-4 before automatic judgement. These measurements need not precede text-mode implementation. This is a sequencing resolution, not evidence that the prototypes passed; the stale acceptance clauses below still need reconciliation. |

## 2. Problems introduced or left inconsistent by the resolutions

1. **High — The image exception has incompatible authority and status.**  
   [ADR-0011 §30](/E:/GitHub/scil/Leafi/docs/adr/0011-egress-policy-and-v1-scope.md:30) calls cloud habit snapshots an **accepted exception**. [AGENTS.md](/E:/GitHub/scil/Leafi/AGENTS.md:9) prohibits images reaching any cloud service, while [product T3](/E:/GitHub/scil/Leafi/docs/product.md:61) calls the exception an **open, Candidate decision**. These cannot all govern implementation. The new ADR records permission that the current repository boundary does not grant.

2. **High — The privacy resolution specifies two different Brain payloads and no reliable default redaction setup.**  
   [ADR-0011 §28](/E:/GitHub/scil/Leafi/docs/adr/0011-egress-policy-and-v1-scope.md:28) permits redacted free-form questions; [security red line 3](/E:/GitHub/scil/Leafi/docs/architecture/quality-attributes/security.md:7) permits them **only as intent + target**. The ADR also says learner name and school are redacted by default, but [configuration](/E:/GitHub/scil/Leafi/docs/architecture/config.md:72) defaults `REDACT_TERMS` to empty without specifying how those identifiers are populated. An implementer can follow one document and violate another.

3. **High — The S0 port sketch still exposes the capability the resolution removes.**  
   [The plan’s Notifier protocol](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-19-leafi-book-study.md:42) still accepts `frame`; [ADR-0011](/E:/GitHub/scil/Leafi/docs/adr/0011-egress-policy-and-v1-scope.md:30) explicitly says it has no frame parameter. The same [port sketch](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-19-leafi-book-study.md:34) omits `Mouth.stop()`, which [device routing](/E:/GitHub/scil/Leafi/docs/architecture/flows/device-routing.md:34) requires. These are implementation contracts, not merely historical descriptions.

4. **High — Playback controls promise a spoken path that half-duplex capture removes.**  
   [Reading-session global transitions](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md:29) include spoken `stop` and cancellation during playback; [device routing](/E:/GitHub/scil/Leafi/docs/architecture/flows/device-routing.md:14) stops capture and discards buffered audio. Console controls provide a viable cancellation path, but spoken cancellation cannot work through that paused Listener. Specify that playback cancellation uses console/Face controls in v1, or design a separate listening path.

5. **High — S3 acceptance would enforce the superseded assessment model.**  
   [The S3 acceptance clause](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-19-leafi-book-study.md:80) requires a synthesized substituted word to become `mispronounced`. [ADR-0009 §1/§4](/E:/GitHub/scil/Leafi/docs/adr/0009-assessment-observations-vs-judgements.md:21) requires an observation and candidate, with separate confirmation. An implementation passing that acceptance test would violate the resolution.

6. **Medium — Text-mode acceptance names a nonexistent miscue state.**  
   [S1 acceptance](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-19-leafi-book-study.md:68) asserts `candidate→practiced` transitions. [The data model](/E:/GitHub/scil/Leafi/docs/architecture/data-model.md:18) puts `practiced` exclusively on a **practice record**, outside the miscue status enum. ADR-0009 §6 specifies the practice outcome but never specifies the resulting text-mode miscue status.

7. **High — ADR-0006 remains accepted with incompatible correction and learning-loop rules.**  
   [ADR-0006](/E:/GitHub/scil/Leafi/docs/adr/0006-self-improvement-is-data-not-weights.md:21) specifies `pages.text_truth`, distrust of the entire corrected page, active lexical rewriting/biasing, and transcripts appended every session. [ADR-0010 §2](/E:/GitHub/scil/Leafi/docs/adr/0010-page-text-revisions-and-auditable-corrections.md:15) instead preserves verified spans within revisions; [ADR-0011 §40](/E:/GitHub/scil/Leafi/docs/adr/0011-egress-policy-and-v1-scope.md:40) makes lexical changes advisory; [configuration](/E:/GitHub/scil/Leafi/docs/architecture/config.md:75) makes evaluation transcripts opt-in. ADR-0006 needs an explicit amendment/supersession covering these decisions.

8. **Medium — The Anki storage resolution claims an amendment that is absent.**  
   [Data-model invariants](/E:/GitHub/scil/Leafi/docs/architecture/data-model.md:33) prohibit Anki IDs on `knowledge_items`, and its outbox row calls ADR-0004 “revised.” [ADR-0004](/E:/GitHub/scil/Leafi/docs/adr/0004-sqlite-system-of-record-anki-as-scheduler.md:22) still selects `knowledge_items.anki_note_id` and a null-ID queue. Both remain operative descriptions of storage.

9. **Medium — New timeout and drain rules disagree within their own documentation.**  
   [Reliability’s failure table](/E:/GitHub/scil/Leafi/docs/architecture/quality-attributes/reliability.md:7) gives Brain 12 seconds, but its [timeout summary](/E:/GitHub/scil/Leafi/docs/architecture/quality-attributes/reliability.md:16) gives 30 seconds. Separately, [device routing](/E:/GitHub/scil/Leafi/docs/architecture/flows/device-routing.md:20) makes `play()` include drain, then [resumes listening after another drain](/E:/GitHub/scil/Leafi/docs/architecture/flows/device-routing.md:29). Following both applies the camera’s drain twice and unnecessarily loses the beginning of the learner’s response.

10. **Medium — The new deletion command lacks an exception to immutable evidence rules.**  
    [Data-model invariants](/E:/GitHub/scil/Leafi/docs/architecture/data-model.md:31) make observations append-only and miscues permanent; [retention](/E:/GitHub/scil/Leafi/docs/architecture/data-model.md:43) deletes session utterances and observations while keeping counts. Since miscues reference observations, the design must specify an intentional deletion exception and what happens to dependent miscues, practices, and correction provenance.

## 3. Is S1 specified tightly enough?

**No.** The architectural direction is sufficiently clear, but these decisions still affect persisted meaning or user-visible behaviour.

- **High — Alignment state and text-mode outcomes.**  
  Locations: [ADR-0009 §2–6](/E:/GitHub/scil/Leafi/docs/adr/0009-assessment-observations-vs-judgements.md:22), [S1 acceptance](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-19-leafi-book-study.md:68).  
  Section 4 gives concrete failures; additionally, text practice needs an actual terminal miscue status.  
  **Proposed decision:** Maintain a provisional alignment across utterances with deterministic ambiguity handling, reconcile candidates when that alignment changes, and finish text-only practice as `unsure` with a separate `practiced/evidence=none` record.

- **High — Correction application lacks a revision transformation contract.**  
  Locations: [ADR-0010 §2–4](/E:/GitHub/scil/Leafi/docs/adr/0010-page-text-revisions-and-auditable-corrections.md:15), [correction flow](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md:80).  
  After verifying `cat` in “A cat sleeps,” replacing `A` with `The` must shift the verified span; token-count changes also move the cursor and assessments from older revisions. “Re-align the current sentence” does not define these transformations or how old confirmed miscues stop contributing to Difficulties.  
  **Proposed decision:** Use half-open Unicode character spans and a versioned tokenizer, record each revision’s edit mapping, transform verified spans and the active cursor through it, and atomically invalidate affected assessments and refresh their derived Difficulties while preserving original evidence.

- **High — The new Anki acknowledgement rule does not handle its required lost-response case.**  
  Locations: [`review_answers`](/E:/GitHub/scil/Leafi/docs/architecture/data-model.md:24), [required durable-side-effect tests](/E:/GitHub/scil/Leafi/docs/engineering/testing.md:22).  
  If the remote answer succeeds but its response is lost, `acked` remains false; “skip when acked” therefore does not prevent the repeat the test forbids.  
  **Proposed decision:** Persist a distinct `sent/unknown` answer state before dispatch, never automatically replay an uncertain answer, and reconcile it against remote review history before allowing another submission.

- **Medium — Anki parent-edit ownership remains unspecified.**  
  Locations: [testing](/E:/GitHub/scil/Leafi/docs/engineering/testing.md:22), [Anki’s curation requirement](/E:/GitHub/scil/Leafi/docs/adr/0004-sqlite-system-of-record-anki-as-scheduler.md:16).  
  “Reconciliation keeps Leafi fields” does not say whether a parent’s edits to those fields survive the next update.  
  **Proposed decision:** Preserve conflicting parent edits and update a generated field automatically only when its remote value still equals Leafi’s last acknowledged value.

- **High — Comprehension judgement requires a payload the egress policy excludes.**  
  Locations: [CHECK](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md:93), [security’s Claude payload](/E:/GitHub/scil/Leafi/docs/architecture/quality-attributes/security.md:15).  
  CHECK sends answers to the Brain for judgement, but the allowed payload contains page text, miscues, intent/target and counts—not learner answers.  
  **Proposed decision:** For S1, keep learner answers local, compare them conservatively with generated expected keywords, and record ambiguous responses as unavailable assessment without a Difficulty.

- **High — Revision guards do not cancel obsolete work on the same page.**  
  Locations: [ADR-0010 §5](/E:/GitHub/scil/Leafi/docs/adr/0010-page-text-revisions-and-auditable-corrections.md:18), [global skip/stop transitions](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md:29).  
  An explanation requested before `/skip` still has the same session and revision afterward; the specified guard permits it to interrupt resumed reading.  
  **Proposed decision:** Attach an active-turn generation and request ID to every asynchronous result, invalidate them on skip/stop/state replacement, and apply results only to their still-active originating turn.

- **Medium — State-specific input and manual-page initialization need explicit rules.**  
  Locations: [S1 intent classification](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-19-leafi-book-study.md:61), [session states](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md:9), [revision initialization](/E:/GitHub/scil/Leafi/docs/adr/0010-page-text-revisions-and-auditable-corrections.md:15).  
  “Everything else is reading” conflicts with ordinary input being a practice retry, comprehension answer or review rating; the text-only command supplies neither a printed page number nor an OCR-created first revision.  
  **Proposed decision:** Route ordinary input by active state, define unsupported controls as explicit no-ops, and create a confirmed manual revision for the initial text file, requiring explicit selection or supplied text for subsequent pages.

These proposals amend the cited rules; the alignment and confirmation proposals below specifically require reopening ADR-0009.

## 4. Ordinary-reading failures in ADR-0009 §2–§4

1. **High — Hesitation can prevent all forward progress.**  
   Location: [§2–§3](/E:/GitHub/scil/Leafi/docs/adr/0009-assessment-observations-vs-judgements.md:22).  
   Consider “The little brown dog walked slowly through the quiet garden toward the old gate,” delivered one word per utterance. No utterance contains two consecutive matches. Unless an implementer invents cross-utterance accumulation, the committed cursor remains at the start; eventually the next word lies outside the roughly ten-token forward window.  
   **Decision needed:** Consecutive matches must be evaluated over retained provisional evidence across utterances, not independently within each utterance.

2. **High — A final-word substitution or omission has no defined completion path.**  
   Locations: [§2–§3](/E:/GitHub/scil/Leafi/docs/adr/0009-assessment-observations-vs-judgements.md:22), [page completion transition](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md:23).  
   Expected: “The dog ran.” Heard: “The dog red,” or just “The dog.” The cursor cannot reach the final expected word through matching; omitted suffixes correctly remain unassessed. But CHECK requires the committed cursor to reach page end, and practice is triggered by sentence end. The design does not say whether provisional sentence completion triggers practice or how skip/practice subsequently settles that final token.  
   **Decision needed:** Provide an explicit sentence/page completion path that can settle uncertain terminal spans without labelling an unspoken suffix deleted or forcing a correct retry.

3. **High — Natural self-correction does not withdraw the earlier candidate.**  
   Location: [§3–§4](/E:/GitHub/scil/Leafi/docs/adr/0009-assessment-observations-vs-judgements.md:23).  
   Expected: “The little cat sat on the mat.” Utterance 1: “The little cap”; utterance 2: “cat sat on the mat.” The second utterance repairs the provisional substitution, but §4 only specifies withdrawal through a Practice retry or an explicit “misheard” statement. The original candidate can therefore survive and trigger unnecessary practice. Suppressing observations for reread matches further removes useful correction evidence.  
   **Decision needed:** Reconciled matches must withdraw superseded candidates, including self-corrections during ordinary reading, while retaining the original observations.

4. **High — Repeated passages make commitment ambiguous.**  
   Location: [§2–§3](/E:/GitHub/scil/Leafi/docs/adr/0009-assessment-observations-vs-judgements.md:22).  
   Page: “I can see it. I can see it.” After the first sentence, another “I can see it” matches both the reread region and the next sentence. Choosing the earlier match can stall genuine progress; choosing the later match can advance during a reread. Two consecutive matches do not distinguish those cases.  
   **Decision needed:** Specify cursor-relative alignment costs and tie handling, keeping equally plausible reread/advance paths provisional until later context or explicit learner input resolves them.

5. **High — The fixed window cannot recover from a skipped line or a longer restart.**  
   Location: [§2](/E:/GitHub/scil/Leafi/docs/adr/0009-assessment-observations-vs-judgements.md:22).  
   A four-word utterance searches only fourteen tokens forward. If the learner skips a longer line, the actual words may be entirely outside the window; restarting more than six tokens back has the corresponding backward failure. The bounded algorithm then lacks a specified alternative to spurious substitutions/insertions or stalled progress. Also, “semi-global” does not specify which leading gaps are free: skipped unread tokens could disappear as an unpenalized prefix.  
   **Decision needed:** Define free prefixes only for permitted rereading, and enter a non-assessing reposition/restart flow when no sufficiently unambiguous in-window anchor exists.

6. **High — Repeating an ASR error can confirm a false miscue with automatic judgement disabled.**  
   Location: [§4](/E:/GitHub/scil/Leafi/docs/adr/0009-assessment-observations-vs-judgements.md:24).  
   If ASR repeatedly hears a correctly spoken “three” as “tree,” the Practice retry “again disagrees,” satisfying confirmation without the evaluated pronunciation scorer. Repeating this across two sessions then creates a Difficulty. The two-session threshold does not protect against systematic recognition errors, and the rule does not say what happens when retry one disagrees but retry two matches.  
   **Decision needed:** Keep repeated transcript disagreement `unsure` unless independently corroborated, and finalize a candidate only after the practice sequence concludes, allowing a later successful retry to withdraw it.

## Remaining blockers before coding

- Reconcile the operative privacy policy, default redaction setup, and comprehension-answer payload.
- Amend ADR-0009 with cross-utterance alignment, ambiguity/recovery, terminal completion, and candidate reconciliation rules.
- Define correction transformations and atomic invalidation across revisions.
- Complete S1’s text-mode statuses, state-specific controls, and asynchronous cancellation.
- Specify Anki uncertain-answer handling and parent-edit ownership.
- Reconcile the active port sketches, acceptance tests, storage ADRs, and deletion semantics.

The hardware prototypes can remain scheduled before their dependent slices; they need not block the corrected text-mode S1.