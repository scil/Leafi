# Codex design review, round 4 (gpt-6-astra, reasoning high, read-only)

Run 2026-10-19 against the round-3 resolutions. Prompt: prompts/round-4.md. Resolutions: ADR-0013 revised in full (exact DP costs, completion history, /back, control precedence, candidate settlement, CHECK partition), ADR-0010 §6, glossary, data model, flow.

## 1. Round-3 blocker status

| Blocker | Status | Resolving text / remaining issue |
|---|---|---|
| F1 — singleton accumulation | **Resolved.** | [ADR-0013:29–30](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:29) accepts exactly one match near `pcur`; steps 5–6 preserve progress. |
| F2 — repeated text and recovery | **Partially resolved — High.** | [ADR-0013:44](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:44) explicitly accepts advancement and removes alternative-path state. However, `/back N` has no defined unit, cursor/status transformation, or transition from CHECK. |
| F3 — completion | **Partially resolved — High.** | [ADR-0013:49](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:49) defines voice/text triggers and Practice-before-CHECK. Terminal substitutions become unread, completion events repeat, and global controls still conflict; see §§2–3. |
| F4 — successful typed Practice | **Resolved.** | [ADR-0013:51](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:51): matching retry → `withdrawn(practice)`, text evidence → `none`, never `confirmed`. |
| F5 — correction coordinates/transaction | **Partially resolved — High.** | [ADR-0010 §6](/E:/GitHub/scil/Leafi/docs/adr/0010-page-text-revisions-and-auditable-corrections.md:22) now maps character spans through revision chains and recomputes Difficulties transactionally, but restricts invalidation to undefined “non-final” miscues; ADR-0013 does not. |
| F6 — Difficulties | **Partially resolved — Medium.** | [Data model:22](/E:/GitHub/scil/Leafi/docs/architecture/data-model.md:22) adopts the ADR formula and watch weights. The glossary still excludes unsure evidence, and the encounter-based Difficulty rule has no corresponding formula; see §3. |
| F7 — CHECK outcomes | **Partially resolved — Medium.** | [ADR-0013:67](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:67) defines `incorrect` and its encounter, but a nonmatching one-word answer satisfies none of the three outcomes. |
| F8 — interrupted-session ownership | **Resolved.** | [ADR-0013:52](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:52) closes old candidates, creates a new page read, and specifies copied cursors/token statuses; [reliability:13](/E:/GitHub/scil/Leafi/docs/architecture/quality-attributes/reliability.md:13) agrees. |
| §1 — residual learner-text permission | **Resolved.** | [ADR-0011:28](/E:/GitHub/scil/Leafi/docs/adr/0011-egress-policy-and-v1-scope.md:28) now says redaction terms start empty and learner free text never reaches the Brain. |
| §1 — book deletion | **Resolved.** | [ADR-0010 §9](/E:/GitHub/scil/Leafi/docs/adr/0010-page-text-revisions-and-auditable-corrections.md:25) explicitly authorizes and defines `forget --book`; [security:48](/E:/GitHub/scil/Leafi/docs/architecture/quality-attributes/security.md:48) delegates to it. |

## 2. Hand execution of ADR-0013

Notation: zero-based token indices; cursor pairs are `(pcur, ccur)`; `U` = unattempted, `P` = provisional, `C` = committed, `M` = candidate, `R` = unread.

**High — execution prerequisite:** [steps 2–4](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:24) do not specify the fuzzy metric, DP terminal boundary conditions, residual tie-break, or exact deletion-path re-evaluation. Below, unequal example words do not pass fuzzy matching, and a semi-global alignment may leave the expected suffix unaligned. Where that differs from the stated consequence, I also trace the intended substitution path.

### (a) “The little brown dog walked slowly.” — one word per utterance

Each utterance matches at `pcur`, passes the singleton gate, and advances both cursors:

| After | Token statuses | Cursors | Alignment events |
|---|---|---|---|
| The | `P U U U U U` | `(1,1)` | none |
| little | `P P U U U U` | `(2,2)` | none |
| brown | `P P P U U U` | `(3,3)` | none |
| dog | `P P P P U U` | `(4,4)` | none |
| walked | `P P P P P U` | `(5,5)` | none |
| slowly | `P P P P P P` | `(6,6)` | `sentence_reached(1)` |

Completion converts all six tokens to `C`; cursors remain `(6,6)`. No miscues or practices; CHECK follows.

**Pass.** Step 6 advances the committed cursor without itself changing token statuses; sentence completion supplies that change. [Steps 5–7 and completion](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:33).

### (b) Expected “The dog ran.”; heard “The dog red.”, then silence

**Minimum-cost path with a free expected suffix:**

1. Match `The dog`; insert `red` for **0.6**, leaving `ran` unaligned. Substituting `ran ← red` would cost **1.0**.
2. State: `P P U`, cursors `(2,2)`, two matched observations and one insertion; **no miscue**; no `sentence_reached`.
3. Voice silence of 1.2 seconds completes the sentence; typed punctuation completes it immediately.
4. Final state: **`C C R`, `(2,2)`**, no miscues or practices; CHECK follows.

**High — missed attempted word:** this records `ran` as unread and gives no word practice, contrary to [the declared consequence](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:71).

**Even forcing the intended substitution does not repair it:**

- After alignment: `P P M`, `(2,2)`, one candidate row `ran ← red`, no alignment event.
- Completion changes **every token at/after `pcur` to unread**, producing `C C R`; the miscue row remains candidate.
- Practice is simultaneously required for sentence candidates and prohibited for unread tokens.

Thus token statuses/cursors are determinate, but there is **no coherent final miscue/Practice trace**: obeying the unread prohibition leaves the candidate open; selecting its row for Practice violates that prohibition. If selected and silence continues to the Practice idle timeout, the row becomes `unsure`.

**High — location:** [cursor update:37](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:37), [completion/Practice:49–51](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:49).

### (c) Expected “The little cat sat on the mat.”; heard “The little cap” / “cat sat on the mat.”

With the same DP boundary interpretation:

1. First utterance: match `The little`, insert `cap` (**0.6**, cheaper than substitution); state `P P U U U U U`, cursors `(2,2)`, no miscues/events.
2. Second utterance: five exact matches from index 2; state `P P P P P P P`, cursors `(7,7)`, event `sentence_reached(1)`.
3. Completion: **seven `C` tokens, `(7,7)`**, no miscues or practices; CHECK follows.

**High — location:** [DP costs:24–28](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:24). Reading progress is correct, but the promised self-correction record never exists.

If the first path is instead forced to substitute, it creates `cat ← cap`, with state `P P M U U U U` and `(2,2)`. The next utterance matches that candidate, makes its token committed, and withdraws its row; final tokens/cursors/events are otherwise identical.

**Medium — reason ambiguity:** [step 5](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:34) does not define “same utterance crosses it” sufficiently to distinguish `self_corrected` from `reread` across these two utterances; [the consequence](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:71) requires `self_corrected`.

### (d) “I can see it. I can see it.”

**First occurrence read, then the identical sentence again:**

- First utterance: `(4,4)`, event `sentence_reached(1)`; after completion, `C C C C U U U U`.
- Second utterance: the window starts at sentence 2 because `sentence_start(ccur)=4`; its four words match, advancing to `(8,8)`.
- Step 7 emits **both `sentence_reached(1)` and `sentence_reached(2)`**.
- After completion processing: **eight `C` tokens, `(8,8)`**, no miscues/practices; CHECK follows.

Advancement is explicitly accepted. **High — duplicate completion:** [step 7](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:40) emits already-completed sentences; suppressing repeated completion, Practice and turn increments needs an explicit rule/state. The listed [ReadingState](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:16) contains no completion history.

**Whole page read first, then the sentence again:** the initial alignment reaches `(8,8)` and emits both sentence events; completion leaves all tokens `C`. The repeated sentence then goes to CHECK under [state routing](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:55), leaving reading tokens/cursors/miscues unchanged. Its CHECK outcome depends on the question and keywords. `/back N` is promised but cannot be executed from the supplied rules.

## 3. Contradictions with current documents

| Severity | Two locations | Conflict |
|---|---|---|
| **High** | [ADR-0013:49–51](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:49) ↔ [reading-session:35–38](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md:35) | ADR completion on stop/page turn runs Practice “before anything else”; the flow immediately enters WRAP/FIND_PAGE and discards provisional alignment on page turn. Skip records `unsure` under the ADR but returns to READ “without recording a judgement” in the flow, including after the final sentence. |
| **High** | [ADR-0013:59](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:59) ↔ [ADR-0010 §6](/E:/GitHub/scil/Leafi/docs/adr/0010-page-text-revisions-and-auditable-corrections.md:22) | ADR-0013 invalidates overlapping miscues without a status restriction; ADR-0010 limits this to “non-final” miscues. Excluding settled `confirmed`/`unsure` rows could retain a Difficulty caused by corrected page text. |
| **Medium** | [ADR-0013:63](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:63) ↔ [GLOSSARY:108](/E:/GitHub/scil/Leafi/GLOSSARY.md:108) | Unsure evidence contributes watch weight versus “Only confirmed Miscues count toward Difficulties.” |
| **Medium** | [ADR-0013:63](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:63) ↔ [data-model:32](/E:/GitHub/scil/Leafi/docs/architecture/data-model.md:32) | The “single formula” covers miscues only; the invariant also creates Difficulties from encounters across two sessions, without a weight or combination rule. |
| **Medium** | [ADR-0013:67](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:67) ↔ [ADR-0011:32](/E:/GitHub/scil/Leafi/docs/adr/0011-egress-policy-and-v1-scope.md:32) | ADR-0011 assigns ambiguous answers `unavailable`; ADR-0013’s listed unavailable cases omit them, while its incorrect rule can classify ambiguous multiword answers as incorrect. A nonmatching one-word answer is unclassified altogether. |

## 4. Is S1 text-mode implementable without inventing an important decision?

**No.**

- **High — alignment:** Define DP endpoints, fuzzy scoring, residual ties and deletion re-evaluation so terminal substitutions and their persisted evidence have one result ([ADR-0013:24](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:24)).
- **High — completion:** Distinguish attempted terminal candidates from unread suffixes and specify completion deduplication and multi-sentence event processing ([ADR-0013:37](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:37)).
- **High — controls:** Define `/back N`’s state transformation and reconcile stop/page-turn/skip precedence with Practice and CHECK ([ADR-0013:44](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:44); §3).
- **High — candidate lifecycle:** Specify what happens to candidates beyond the two-word Practice limit and to pending candidates when controls leave the sentence/session ([ADR-0013:49](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:49)).
- **High — corrections:** Resolve which settled miscue statuses are invalidated by corrected page text (§3).
- **Medium — reconciliation:** Define the cross-utterance predicate that produces `withdrawn(self_corrected)` in the required acceptance scenario ([ADR-0013:34](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:34)).
- **Medium — Difficulties:** Reconcile the glossary and specify or remove encounter-derived weighting (§3).
- **Medium — CHECK:** Define content-word counting and an exhaustive outcome partition, including nonmatching one-word and ambiguous answers ([ADR-0013:67](/E:/GitHub/scil/Leafi/docs/adr/0013-reading-algorithm-v1.md:67)).

### Remaining blockers before coding

- Alignment and terminal-candidate handling.
- Completion deduplication, control precedence and `/back`.
- Complete candidate settlement and self-correction rules.
- Correction invalidation scope.
- Difficulty and CHECK contract reconciliation.