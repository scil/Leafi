# Codex design review, round 3 (gpt-6-astra, reasoning high, read-only)

Run 2026-10-19 against the round-2 resolutions. Prompt: prompts/round-3.md. Resolutions: ADR-0013 (supersedes 0009/0012), ADR-0010 §6/§9, ADR-0011, data model, flows, reliability.

## 1. Round-2 blocker status

| Blocker | Status | Resolving text and remaining limitation |
|---|---|---|
| Privacy policy, redaction setup, comprehension payload | **Partially resolved — Medium.** | [AGENTS.md:9](/E:/GitHub/scil/Leafi/AGENTS.md:9) now authorizes the explicit habit-snapshot opt-in. [ADR-0011:32](/E:/GitHub/scil/Leafi/docs/adr/0011-egress-policy-and-v1-scope.md:32) specifies local answer comparison, prohibits learner text in cloud payloads, and names `setup --redact`. However, [§28](/E:/GitHub/scil/Leafi/docs/adr/0011-egress-policy-and-v1-scope.md:28) still permits redacted free-form questions and claims default identifiers; that incompatible permission remains operative prose. |
| Cross-utterance alignment, ambiguity/recovery, completion, reconciliation | **Partially resolved — High.** | [ADR-0012 §1–5](/E:/GitHub/scil/Leafi/docs/adr/0012-reading-state-across-utterances.md:15) adds all five mechanisms; §4 explicitly withdraws self-corrected candidates. Their interactions still fail the walkthrough below: F1–F3. |
| Correction transformations and atomic invalidation | **Partially resolved — High.** | [ADR-0010 §6](/E:/GitHub/scil/Leafi/docs/adr/0010-page-text-revisions-and-auditable-corrections.md:22) supplies code-point spans, tokenizer versions, edit maps and transactional state transformation. Cross-revision invalidation coordinates and the Difficulty transaction boundary remain unclear: F5. |
| S1 text statuses, state-specific controls, asynchronous cancellation | **Partially resolved — High.** | [ADR-0012 §7–8](/E:/GitHub/scil/Leafi/docs/adr/0012-reading-state-across-utterances.md:45) resolves input routing, turn guards and playback cancellation; [ADR-0010 §7](/E:/GitHub/scil/Leafi/docs/adr/0010-page-text-revisions-and-auditable-corrections.md:23) resolves manual initialization. Successful typed Practice still has conflicting terminal statuses: F4. |
| Anki uncertain answers and parent-edit ownership | **Resolved.** | [ADR-0004 amendment](/E:/GitHub/scil/Leafi/docs/adr/0004-sqlite-system-of-record-anki-as-scheduler.md:30): persist `sent`, never replay automatically, reconcile against review history; update fields only when remote values match their last acknowledged values. |
| Ports, acceptance, storage ADRs and deletion | **Partially resolved — Medium.** | [S0 ports](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-19-leafi-book-study.md:34), [S3 acceptance](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-19-leafi-book-study.md:92), and [ADR-0006’s amendment](/E:/GitHub/scil/Leafi/docs/adr/0006-self-improvement-is-data-not-weights.md:27) resolve their former conflicts. [ADR-0010 §9](/E:/GitHub/scil/Leafi/docs/adr/0010-page-text-revisions-and-auditable-corrections.md:25) defines session deletion and dependent records. However, [security’s retention contract](/E:/GitHub/scil/Leafi/docs/architecture/quality-attributes/security.md:48) still promises `forget --book`, outside that sole exception; new storage inconsistencies appear in F6/F8. |

## 2. Contradictions or unimplementable rules in the amended design

**F1 — High: the anchor gate defeats cross-utterance accumulation.**  
[ADR-0012 §1](/E:/GitHub/scil/Leafi/docs/adr/0012-reading-state-across-utterances.md:17) commits merged provisional matches across utterances, but [§3](/E:/GitHub/scil/Leafi/docs/adr/0012-reading-state-across-utterances.md:27) makes an utterance without two consecutive matches unanchored, with **no observations**. There is no exception or provisional-evidence update rule allowing the first singleton to seed the next one.

**F2 — High: repeated text is not necessarily a tie, and unresolved alternatives lack a state contract.**  
[ADR-0012 §2](/E:/GitHub/scil/Leafi/docs/adr/0012-reading-state-across-utterances.md:23) penalizes distance from the provisional cursor; after the first identical sentence, that normally favors advancement over rereading. Thus [the confirmation scenario](/E:/GitHub/scil/Leafi/docs/adr/0012-reading-state-across-utterances.md:59), which expects a provisional tie, is not guaranteed. Furthermore, [ReadingState](/E:/GitHub/scil/Leafi/docs/adr/0012-reading-state-across-utterances.md:17) specifies neither competing positions nor a tie counter, and §7 supplies no routing rule for the clarification answer.

**F3 — High: completion has incompatible transition conditions and no defined silence event.**  
[ADR-0012 §5](/E:/GitHub/scil/Leafi/docs/adr/0012-reading-state-across-utterances.md:35) allows completion through provisional progress or a pause, while [the state diagram](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md:23) enters CHECK only when the **committed** cursor reaches page end. It also does not establish whether final Practice precedes CHECK. Separately, [the Listener contract](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-19-leafi-book-study.md:41) supplies utterances/timeouts, but no rule tells pure `align()` about subsequent silence or defines an equivalent typed-text completion event.

**F4 — High: a matching typed Practice retry has two terminal statuses.**  
[ADR-0012 §6](/E:/GitHub/scil/Leafi/docs/adr/0012-reading-state-across-utterances.md:39) says both “any retry that matches → withdrawn” and “Text mode: practice ends as unsure.” [The Practice sequence](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md:70) unconditionally uses matched → withdrawn. This requires an explicit precedence decision; `evidence=none` alone does not decide it.

**F5 — High: correction invalidation compares incompatible coordinates.**  
[ADR-0010 §6](/E:/GitHub/scil/Leafi/docs/adr/0010-page-text-revisions-and-auditable-corrections.md:22) tests an `expected_token_index` against an edited **character** span while preserving older assessments’ original indices. [The correction flow](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md:86) merely says “miscues inside the span.” A candidate retained from revision 1 must be mapped through intervening edits before a revision-3 correction can invalidate it; that mapping/overlap rule is missing. These same locations place Difficulty recomputation “afterwards” versus inside the transaction.

**F6 — Medium: watch Difficulties are both required and prohibited.**  
[ADR-0012 §6](/E:/GitHub/scil/Leafi/docs/adr/0012-reading-state-across-utterances.md:41) creates watch weight from `unsure` miscues across three sessions; [the `difficulties` entity](/E:/GitHub/scil/Leafi/docs/architecture/data-model.md:22) says `unsure` miscues never contribute. Its count × recency formula also differs from the new per-session weights.

**F7 — Medium: CHECK has no reachable definition of a “clear miss.”**  
[The CHECK flow](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md:97) partitions answers into keyword match → correct, everything else → uncertain, then requires an encounter for a “clear miss.” [ADR-0011](/E:/GitHub/scil/Leafi/docs/adr/0011-egress-policy-and-v1-scope.md:32) instead calls ambiguous answers `unavailable`. Neither defines a third outcome that can record a misunderstanding.

**F8 — Medium: crash recovery both resumes and closes the session.**  
[The `page_reads` entity](/E:/GitHub/scil/Leafi/docs/architecture/data-model.md:15) persists state “so a crash resumes from the committed cursor”; [reliability](/E:/GitHub/scil/Leafi/docs/architecture/quality-attributes/reliability.md:13) closes the interrupted session on startup. Resuming through a new session/page-read could reconcile these, but ownership and transfer of candidates/reading state are unspecified.

## 3. ADR-0012 §1–8 walkthrough

Positions below count expected tokens consumed. Where the rules conflict, these are conditional traces, not invented resolutions.

### (a) “The little brown dog walked slowly.” — one word per utterance

1. **“The”:** §3 makes this unanchored: store the utterance, create no observations; cursor remains 0.
2. **“little”:** another singleton is unanchored. The whole-page retry cannot find three consecutive matches, so enter REPOSITION.
3. **“brown”, “dog”, “walked”, “slowly”:** §3 provides no singleton recovery path; assessment remains suspended. No candidate or Practice record is justified.

**High — F1:** §1’s intended trace would instead be provisional “The” → commit through “little” → provisional “brown” → commit through “dog” → provisional “walked” → commit through “slowly”. The design cannot select that trace without modifying §3. §§4–6 otherwise have nothing to reconcile or practise.

### (b) Expected “The dog ran.”; heard “The dog red.”, then silence

1. **§§1–3:** assuming the intended substitution alignment, record two matched observations and `ran ← red` substituted; create a candidate. Commit through “dog”; the terminal alignment remains provisional.
2. **§5:** the substituted final token is explicitly eligible for Practice. Completion should occur through the provisional cursor, or the ≥1.2-second pause if its position is interpreted differently.
3. **§§4/6:** silence is neither a matching retry nor exhausted retries nor skip. It does **not** by itself make the candidate `unsure`; no Practice-attempt row is yet required.
4. **§7:** after entering PRACTICE, subsequent ordinary input is a retry, not reading. Continued silence eventually invokes the documented idle timeout, but the candidate’s disposition at WRAP is unspecified.

**High — F3/F4:** the silence trigger, Practice-before-CHECK ordering, and settlement on idle termination are unresolved. CHECK’s committed text would contain only “The dog” unless another rule advances commitment.

### (c) Expected “The little cat sat on the mat.”; heard “The little cap” / “cat sat on the mat.”

1. **§§1–3, first utterance:** the two-word anchor permits matched observations for “The little”; commit through token 2, record a substitution/candidate for “cat.” This is not near the sentence end, so §5 does not yet trigger Practice.
2. **§§2–4, second utterance:** the five-word match anchors normally; record matched observations including “cat,” withdraw its candidate as `self_corrected`, and retain the original substitution observation.
3. **§§1/5–6:** the final match run advances commitment through the sentence. No surviving candidate requires Practice; CHECK can follow.

**Resolved for this reading:** §4 supplies the missing reconciliation. The representation should retain both the matched-token evidence and the withdrawn miscue status; they describe different facts.

### (d) Page “I can see it. I can see it.”, read once, then “I can see it” again

There are two materially different interpretations:

- **The whole page was read once:** §§1–5 record eight matches, commit through token 8 and complete the page. If now in CHECK, §7 routes the repeated sentence as a **comprehension answer**, not a reread; §4 never runs. A deliberate rereading transition is not specified.
- **Only the first occurrence was read:** the initial four matches commit through token 4. On the next identical utterance, §2’s jump penalty ordinarily favors the second occurrence: its start is near the provisional cursor, while the reread starts four tokens back. The design can therefore record advancement and complete the page even if the learner intended a reread.

**High — F2:** an exact tie is not guaranteed. If one occurs, §2 prohibits commitment and eventually asks for clarification, but does not specify which observations/candidates remain provisional, how alternatives persist, or how the answer selects one.

**§§7–8, common to all four:** state changes/new sentences invalidate asynchronous work through `turn_id`; controls bypass ordinary input routing. During playback, cancellation uses the console/Face; spoken stop works only while listening. Those contracts are now clear.

## 4. Is S1 sufficiently specified?

**No.** The remaining decisions affect persisted evidence or observable session behavior:

- **High — F1/F2:** Define how singleton evidence survives anchoring, how reread/advance alternatives are retained and selected, and which cursor repositioning changes.
- **High — F3:** Define typed/silence completion events and the ordered transitions through final Practice, CHECK, page changes and idle termination.
- **High — F4:** Choose the terminal miscue status for a successful typed Practice retry.
- **High — F5:** Define cross-revision token-to-character overlap for invalidation and one atomic boundary for derived Difficulties.
- **Medium — F6/F7:** Choose the authoritative Difficulty formula and the exact CHECK outcomes that create encounters.
- **Medium — F8:** Choose whether interrupted reading resumes, and under which session/page-read identity.
- **Medium — §1 policy findings:** Remove the conflicting learner-text permission and specify or withdraw `forget --book`.

### Remaining blockers before coding

- Resolve F1–F4’s alignment, completion and Practice contracts.
- Complete F5’s correction/invalidation contract.
- Reconcile F6–F8’s derived records and recovery behavior.
- Reconcile the residual privacy and book-deletion contracts identified in section 1.