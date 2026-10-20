# Codex design review, round 5 — final (gpt-6-astra, reasoning high, read-only)

Run 2026-10-19 against the round-4 resolutions. Prompt: prompts/round-5.md. The five remaining decisions were recorded in ADR-0013 and the data model; the review loop closed at the five-round budget of the codex-review skill.

## 1. Round-4 blocker status

| Blocker | Status | Resolving text / remaining issue |
|---|---|---|
| Alignment specification | **Resolved.** | [ADR-0013:19–43](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:19) specifies similarity, costs, free endpoints, tie-breaking and conversion of long deletions to `line_skipped`. |
| Completion | **Partially resolved — High.** | [Steps 5–7 and completion](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:52) preserve terminal candidates and deduplicate sentence events; early completion still violates the cursor invariant (§4). |
| Controls and `/back` | **Partially resolved — High.** | [Control rules](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:69) now specify transformations and precedence, but `/back 1` contradicts walkthrough (d), and terminal PRACTICE transitions disagree with the flow. |
| Candidate lifecycle | **Partially resolved — High.** | [Completion](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:63) assigns excess candidates `unsure(not_practised)`; [stop](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:71) settles all remaining candidates; page departure during PRACTICE lacks equivalent coverage. |
| Correction invalidation scope | **Resolved.** | [ADR-0010 §6](/E:/GitHub/scil/Leafi/docs/adr/0010-page-text-revisions-and-auditable-corrections.md:22) and [ADR-0013](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:83) both invalidate overlapping `candidate/unsure/confirmed` rows across revisions, preserving withdrawn rows. |
| Self-correction predicate | **Resolved.** | [Step 5](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:46): the immediately following utterance produces `self_corrected`; otherwise `reread`. |
| Difficulties | **Partially resolved — Medium.** | [ADR formulas](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:87) now cover both sources, and [Miscue](/E:/GitHub/scil/Leafi/GLOSSARY.md:107) admits unsure evidence; the data-model summary still differs for mixed evidence (§3). |
| CHECK partition | **Resolved.** | [ADR-0013:93–97](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:93) defines content words and a final `unavailable` branch; [ADR-0011](/E:/GitHub/scil/Leafi/docs/adr/0011-egress-policy-and-v1-scope.md:32) delegates to it. |

## 2. Hand execution

Zero-based token indexes; cursors are `(pcur, ccur)`. `U` = unattempted, `P` = provisional, `C` = committed, `M` = candidate, `S` = settled.

### (b) “The dog red.”

- Two matches plus substitution cost **1.0**, versus **1.2** for trailing insertion.
- Alignment produces `P P M`, `(3,3)`, and `sentence_reached(1)`.
- Completion immediately produces `C C M`, `completed={1}`, then PRACTICE; the sentence does not wait for silence.
- Under the Practice timeout rule, final tokens are **`C C S`**, cursors **`(3,3)`**; one miscue row: token 2, `ran ← red`, **`unsure(idle)`**, evidence `none`.
- Alignment events: **`[sentence_reached(1)]`**.

**Medium — ambiguous exit:** the walkthrough proceeds to CHECK, but the global idle rule proceeds to WRAP; see §3. Locations: [Practice/walkthrough](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:67), [global idle](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md:39).

### (c) “The little cap” / “cat sat on the mat.”

- First utterance: substitution costs **1.0**; state **`P P M U U U U`**, `(3,3)`, no events.
- Second utterance starts at index 2, costing **0.1** for the backward jump; all five words match.
- The candidate becomes `settled`, and its existing row becomes `withdrawn(self_corrected)`.
- Final tokens: **`C C S C C C C`**; cursors **`(7,7)`**; `completed={1}`.
- One miscue row: token 2, `cat ← cap`, **`withdrawn(self_corrected)`**, evidence `none`.
- Events: **`[]`, then `[sentence_reached(1)]`**; no PRACTICE; CHECK follows.

No child-facing defect in this trace. “Commits all” in the walkthrough includes a token whose actual status remains `settled`.

### (d) Repeated sentence, then `/back 1`

Using the walkthrough’s stated sequence of two utterances, each “I can see it”:

| After | Tokens | Cursors | Completed | Alignment events |
|---|---|---|---|---|
| First sentence | `C C C C U U U U` | `(4,4)` | `{1}` | `sentence_reached(1)` |
| Second sentence | `C C C C C C C C` | `(8,8)` | `{1,2}` | `sentence_reached(2)` |
| `/back 1` | **`U U U U U U U U`** | **`(0,0)`** | **`{}`** | None |

No miscues. The second alignment’s window begins at index 4, so sentence 1 is already excluded.

**High — wrong recovery target:** at page end, `cur=sentence 2`; one sentence *before* it is sentence 1, and the inclusive reset reopens both sentences. The promised result—only sentence 2 reopened—would instead be `C C C C U U U U`, `(4,4)`, `completed={1}`. Locations: [/back rule](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:69), [walkthrough (d)](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:104).

If the initial quotation means the entire page in one utterance, both completion events occur then; the subsequent repeated sentence is routed to CHECK. The final `/back` discrepancy remains.

### (e) “The dog ran away.”

- Match indexes 0–2 and insert `away`: **1.2**.
- Substituting index 3 instead costs **1.0 + 0.5 = 1.5**.
- Inserted observation: `away`, anchor **3**.
- Final tokens: **`C C C U U U`**; cursors **`(3,3)`**; `completed={1}`.
- **No miscue rows**; events **`[sentence_reached(1)]`**; continue READ.

No ambiguity or child-facing defect in this trace.

## 3. Contradictions with other current documents

| Severity | Two locations | Conflict |
|---|---|---|
| **High** | [ADR `/back`](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:69) ↔ [flow:37](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md:37) | Inclusive target-to-current reset can reopen **N+1** sentences; the flow says **N**. |
| **High** | [ADR controls](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:71) ↔ [flow:23](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md:23) | Skipping the last Practice candidate returns to READ under the control rule, but to CHECK under the flow when the page is complete. |
| **High** | [ADR completion/controls](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:63) ↔ [flow:38](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md:38) | The flow settles open candidates on page departure; the ADR only invokes sentence completion, which already happened before PRACTICE, and provides no page-wide settlement equivalent to `stop`. |
| **Medium** | [ADR walkthrough (b)](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:102) ↔ [flow:39](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md:39) | Practice silence leads to CHECK versus global idle leading to WRAP; distinct timers or precedence are unspecified. |
| **Medium** | [ADR completion](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:63) ↔ [miscues schema](/E:/GitHub/scil/Leafi/docs/architecture/data-model.md:18) | Required `unsure(not_practised)` has no corresponding allowed `unsure_reason`. |
| **Medium** | [ADR word formula](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:87) ↔ [data-model:22](/E:/GitHub/scil/Leafi/docs/architecture/data-model.md:22) | One confirmed session establishes a row, after which one separate unsure session contributes `0.3` under the ADR; the table permits unsure contributions only across ≥3 sessions. |

## 4. Is S1 text-mode implementable now?

**No—not without resolving the remaining behavioral decisions.**

- **Blocker — High:** [Completion](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:63) must preserve the [cursor invariant](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:17): typing “The dog.” against “The dog ran.” produces `C C unread`, **`(pcur,ccur)=(2,3)`**, so cursor advancement or the invariant needs an explicit decision.
- **Blocker — High:** Define whether `/back 1` at page end reopens the last sentence or both sentences, resolving §2(d).
- **Blocker — High:** Specify settlement of every outstanding page candidate when page departure interrupts PRACTICE (§3).
- **Blocker — High:** Specify CHECK versus READ after skipping the final Practice candidate (§3).
- **Blocker — Medium:** Distinguish Practice timeout from session idle, or define their precedence and resulting exit (§3).
- **Implementer may decide — Medium:** Add `not_practised` to the storage reason enum, following the explicit owner rule (§3).
- **Implementer may decide — Medium:** Implement the ADR’s mixed-evidence Difficulty formula and correct the secondary table (§3).

### Remaining blockers before coding

- Completion cursor invariant.
- `/back` recovery target.
- Page-departure candidate settlement.
- Final Practice skip destination.
- Practice timeout versus session idle.