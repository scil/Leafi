# ADR-0013 v2 rev 2: increment review (round 2, stand-in for codex)

Reviewer: a fresh Claude session (Opus 5.5) standing in for codex at the owner's request (codex quota exhausted), 2026-10-22, single reviewer for an increment round. Prompt: [prompts/adr-0013-v2-round-2-codex.md](prompts/adr-0013-v2-round-2-codex.md); diff `.scratch/review/adr-0013-v2-r2.diff` (46466f7..3d8fe57). Recorded verbatim below; resolutions are in the ADR's rev 3 and in the plan's Decision log.

---

Scope: `docs/adr/0013-reading-algorithm-v1.md` (v2 rev 2), `.scratch/review/adr-0013-v2-r2.diff`, the round-1 comparison. I also opened `docs/architecture/data-model.md` (entity table and Migration 5) and ADR-0017 §6.1 and §8 where a claim depended on them. `alignment.py` was not needed. No files were edited.

Costs are in tenths: exact/phones/join 0, fuzzy 3, inflection/substitute 10, delete run 8 + 3(L−1), insert 12, back jump 4 + (a−k), boundary 5 per visit with fewer than min(2, len) aligned tokens. Fast entry is |f−pcur| + 15 per skipped whole-unread sentence. Page entry is |f−pcur| when that is ≤ 2, else 15.

**There are two High findings.** Both are storage-integrity failures that happen in ordinary flows.

## High

**H1. `supply()` on a token that is already a candidate creates a second candidate for the same token** (§Supplying a word; data-model → Migration 5 `miscues`)

- `supply` sets `tok.status = candidate` and always writes a new miscue. It has no guard for a token that is already `candidate`.
- Failing scenario, using (t)'s sentence:
  1. The learner stalls at `dog`, accepts the hint, and `supply(3)` runs. Token 3 is `M`, miscue m1.
  2. The learner says "go back". `/back 1` leaves `M` tokens as they are, so token 3 stays `M` and `pcur = ccur = 0`.
  3. The learner rereads "the little brown" and stalls at `dog` again. The hint is accepted and `supply(3)` runs again.
  4. It creates miscue m2 with `status = candidate` on the same `(page_read_id, expected_token_index = 3)`. The partial unique index `WHERE status = 'candidate'` rejects the insert, so the utterance's transaction fails mid-session.
- Without that index, m2 replaces `tok.miscue_id`. `close_cycle` then cannot find "the token whose miscue_id = m1.id", and m1 is orphaned.
- The same thing happens through a second route: 4(d) or rule 7 makes `dog` a substitution candidate ("dug"), then `/back`, a stall at `dog`, and a hint.
- The ADR has to say what a hint on a candidate token does. Options: keep the existing miscue and set `origin = supplied` on it, or forbid the hint there.

**H2. The candidate partial unique index is keyed on an index that the design deliberately leaves stale** (§Correction interaction; Migration 5 `miscues`)

- Migration 5 adds a unique index on `(page_read_id, expected_token_index) WHERE status = 'candidate'`. It also states that `expected_token_index` "stays the index at the revision of creation". Meanwhile, an open-cycle page read is re-tokenised in place, so its indexes shift.
- Failing scenario:
  1. Revision r is "The cat sat on the mat." with a candidate on `sat` (index 2 at r).
  2. A voice correction inserts a word the OCR missed: r+1 is "The fat cat sat on the mat." `sat` is now index 3 and its candidate survives, because its span does not overlap the edit.
  3. The learner then misreads `cat`, which is index 2 at r+1. The new candidate has `expected_token_index = 2` in the same page read, which violates the index.
- Fix: put the index on `(page_read_id, page_revision_id, expected_token_index)`. The real one-candidate-per-token guarantee already lives in `ReadingState` through `miscue_id`.

## Medium

**M1. Walkthrough (f) is wrong: the best path is two substitutions, not a line skip** (§align rule 3; walkthrough (f); unchanged since rev 1)

- Setup: "A B C D K L" against A–L.
- Ending the path with K→E and L→F as substitutions costs 10 + 10 = 20. The tokens G–L after the last aligned token are a free gap.
- The deletion path costs 23 and the forward-entry path costs 46. So the minimum is **20**: accepted by 4(a) (A B C D), internal 20 ≤ 42.
- Result: candidates on E and F, which the learner skipped and did not misread. On the next utterance, K and L, which were read correctly, become `R` by rule 6.
- General rule: a line skip followed by k ≤ 2 heard words before the utterance ends produces k substitution candidates, because 10k < 23.
- Fix options:
  - Use ≥ 3 words after the skip in the walkthrough (30 > 23).
  - Name this as a limit.
  - Make a trailing substitution run pay more than a deletion.
- The oracle test will fail on (f) as written.

**M2. 4(d) turns one-word chatter into a candidate** (§align rule 4(d); prompt item)

- Page "Mum went to the shop to buy some milk." with `pcur = 8` (`milk`). The child calls "mum".
  - m = 1; one substitution at `pcur` on a content word; `is_word(mum)`; confident; same first letter.
  - Accepted, cost 15. A candidate is created on `milk` and `pcur = 9`.
  - `sentence_reached` then completes the sentence before `milk` was read.
- If the learner then reads "milk", 4(c) matches it (index 8 ∈ [7, 11], cost 6) and the candidate becomes `withdrawn(self_corrected)`. That is a false self-correction count.
- If a page turn, `skip` or `stop` follows instead, it stays a false alarm.
- Other pairs that pass:
  - "yeah" at `year` (sim 0.75) or at `yellow`;
  - "no" at `nose` (0.67);
  - "okay" at any word starting with o.
- RA2 (cited in the ADR) puts 17.6 % of child speech off-task, and short interjections are the commonest kind.
- Suggest excluding a small interjection list (yeah, yes, no, okay, mum, mom, dad, wait, look) from 4(d). This is cheap and does not need the labelled set.

**M3. ADR-0017 §8 item 2 still contradicts ADR-0013 v2 on page turns** (rule stated twice; a round-1 resolution not propagated)

- ADR-0017 line 359 still says a page turn "completes the current sentence by (iii)".
- ADR-0013 v2 and the comparison ("a page turn … completes nothing") say the opposite.
- The new §8 preamble says ADR-0013 wins. Even so, an accepted ADR now states the old rule that (j) depends on.
- Two smaller mismatches:
  - ADR-0017 §6.1 says a supplied token gets "reason `supplied`", but ADR-0013 uses `origin = supplied`.
  - ADR-0017 §8 item 5 says "the last page read"; ADR-0013 says "latest page read" through `open_page_read`.
- Fix: amend item 2, the §6.1 sentence and item 5, or turn them into pointers.

**M4. A practice sequence interrupted by a page turn has no defined record or final status** (§Practice 2–5; prompt item)

- Scenario: attempt 1 is `fail` (`practices` row, attempt 1). During attempt 2's listening window the learner turns the page, so `practise_errors` ends `page_turned`.
  - (a) The interrupted attempt has no `outcome` value. `idle`, `unclear` and `skipped` are all wrong. Writing any row uses up the budget; writing none should be stated.
  - (b) The learner reads on and the cycle closes with `wrap` or `next_reading`. `close_cycle` sets `unsure(not_practised)` (v = 0), which throws away a recorded `fail` that a completed sequence would have scored as `unsure(disagreed)` (0.3). `stop` similarly gives `skipped` (0).
  - (c) In a later `practise_errors`, the ADR does not say that the attempt number continues at 2 or that the final-status rule reads attempts from the earlier activity.
- Fix:
  - State "the interrupted attempt writes no row".
  - Have `close_cycle` use the practice final-status rule for a candidate with ≥ 1 attempt.
  - Make the final status read every `practices` row of the miscue.

**M5. A supplied miscue has no observation, but `miscues.observation_id` is not nullable** (Migration 5)

- In schema 4, `miscues.observation_id` is a required column.
- `supply` has no utterance and no observation, and Migration 5 does not make the column nullable or say that `supply` writes an observation.
- As written, every hint insert fails.

**M6. A correction behind the frontier strands slow readers** (§Correction interaction, cursor clamp)

- `pcur` and `ccur` are "clamped to the first such token when they were past it".
- Scenario: the learner is in s4. A voice correction fixes a word in s1, so `pcur` goes back to that token and s1 leaves `completed`.
  - A one-word utterance in s4 fails 4(c) and 4(d), which need `pcur ± 2`, and the page pass does not run for m = 1. Every utterance is `unaligned`.
  - Only after 6 such words does the first-words prompt fire.
  - The words read meanwhile end up `R`.
- Utterances with m ≥ 2 recover through the page pass (entry 15).
- Fix: clamp only when the edited token is at or after `ccur`, or only `ccur`. A correction behind the frontier does not need the learner to go back.

## Low

- **L1. (g): the fast-pass minimum is 44, not 52.** Path: insert `she`, insert `smiled` (24), `at₀`, `the₁` (exact), `clever`→`edge₂`, `fox`→`of₃` (20).
  - It has no anchor (only function words matched) and internal 44 > 42, so it is still not accepted. The conclusion stands.
  - The stated number is wrong for the second round running, and the oracle test will catch it.
- **L2. (k) cannot happen as written.** With A s1 = "the cat sat on the mat", A:3 is `on`, a function word.
  - Alignment never creates a candidate there.
  - If A:3 were supplied instead, rule 7 would not withdraw it.
  - Either way the stated "`withdrawn(reread)`" is impossible. Pick a text where A:3 is a content word. This is new in rev 2.
- **L3. (s): a third path also costs 20 with f = 5.**
  - Path: `I see a` in s2, then delete `blue cat I see a` (L = 5: 8 + 12 = 20), then `red₁₃ bird₁₄`.
  - It ties on cost and on first index. Only the lexicographic key decides (at index 8, `substitute` comes before `delete`).
  - The outcome (candidates at blue/cat) holds, but it depends on the operation order. State that, or the next edit to the order flips it silently into `line_skipped(5)`.
- **L4. (i), second variant: the runner-up is 17, not 36.**
  - Path: insert `red` (12), then back jump 1→0 (5).
  - The result (16) is unchanged.
- **L5. Corrections treat open and closed cycles differently** (§Opening a page read vs §Correction interaction).
  - In an open cycle, the edited tokens become `U` and the cursors clamp to them. In a closed cycle, `open_page_read` commits every token before the mapped `c`, edited ones included.
  - Two cases are undefined:
    - mapping a `prev.ccur` whose token the correction deleted;
    - `prev.ccur = n` (a finished page) being "clamped to a sentence start". Down to the last sentence start, or kept at n?
  - The clamp direction is only implied by (j).
- **L6. The fast-pass back-jump bound is undefined in the first sentence.** `first_index(sentence(a) − 1)` does not exist there; it should say "or lo".
- **L7. `number join` does not define "number word".** (o)'s "one hundred and five" needs `and` to count as a number word inside a join; otherwise the 4-word join fails.
- **L8. Migration 5 is missing two observation fields.** Rule 5 carries `sim` on matches and a count on `unaligned(count)`; neither has a column.
- **L9. Two misreadings in five words can be rejected even though the ceiling passes.** For "She went to the shop" heard "she want to the ship": internal 20 ≤ 35, but every matched word is a function word, so neither 4(a) nor 4(b) holds and the result is `unaligned(5)`. The two real misreadings later end as `R`. This is a miss, not a false alarm; name it next to the ceiling limit in Consequences.
- **L10. (w) does not say where `pcur` is.** `The₀ → R` holds only if `pcur` is before index 1. If the learner jumped back (`pcur` later on the page), rule 6 does not apply.
- **No duplication problem inside ADR-0013.** The rule "no alignment candidate on a function word" appears in rule 7, Practice and Difficulties, but all three agree.
- **Comparison resolutions:** all are in the ADR except the page-turn rule, which did not reach ADR-0017 §8 item 2 (M3).
- **Migration 5:** every new state and column reached it, except M5, L8 and the H2 index key.
- **Round-1 walkthroughs:** no walkthrough that rev 1 had right is broken by rev 2. The intended changes are (a) spoken "The" and (n). (f) and (g) were already wrong in rev 1; (k)'s inconsistency is new.
- **Refrain:** the page-pass replacement margin holds (see the appendix), so no finding.

## Appendix: hand-executions

- **(a)** Typed singletons each cost 0 + 5 = 5, accepted by 4(c). Spoken "The": no anchor rule applies, so `unaligned(1)`. "little": entry 1 + 5 = 6, accepted by 4(c); `The₀ → R` by rule 6. ✓
- **(b)** `the dog` + `red`/`ran` substitute = 10 (inserting would cost 12). 4(a); internal 10 ≤ 21; 10 ≤ 15, so no page pass. Result `C C M`. ✓
- **(c)** Utterance 1: 10, candidate on `cat`. Utterance 2: entry 1 vs inserting "cat" 12, so 1; `withdrawn(self_corrected)`. Result `C C S C C C C`. ✓
- **(d)** Second utterance: lo = sentence_start(4) = 4, cost 0. `/back`: `pcur = n`, so cur = s2. Result `C C C C U U U U`, (4, 4). ✓
- **(e)** Insert `away` 12 vs substitute `The₃` 10 + boundary 5 = 15. ✓
- **(f)** ✗ Minimum 20 (substitute E, F), not the 23 line skip (M1).
- **(g)** ✗ Fast minimum 44 (L1), not accepted. Page pass: 15 + 0, run of 6, used. s1 and s2 become `R`, s3 `C`. ✓ result.
- **(h)** 10 (inserting + deleting would cost 20). Runs have length 1; 4(b) holds with 2 ≥ 2; internal 10 ≤ 21. `hosre`: LCS 4 → sim 0.80, not a word → fuzzy. ✓
- **(i)** First: 5 vs 24. ✓ Second: 16; runner-up 17 (L4). ✓ Third: insert 12 vs 10 + 4 = 14; sim(cap, cat) = 0.67 ≥ 0.5, so marked. ✓
- **(j)** `open_page_read(rest)`: prev = cycle k's A page read; `ccur` inside s2 clamps down to the start of s2; s1 `C`. ✓ (The clamp direction is implied only.)
- **(k)** Window lo = start of s2. Page pass entry 15, cost 15, run of 6. Result ✗ (L2).
- **(l)** B:5 `skipped`, then `close_cycle(stop)` makes C:2 `skipped`. ✓
- **(m)** No match anywhere, so no anchor: `unaligned(7)`. ✓
- **(n)** ✓
- **(o)** `he was` + join = 0, run of 3 (the numeral counts as a content word). The 4-word join needs `and` to count as a number word (L7).
- **(p)** 10; `at the fox` is a run, so 4(a). ✓
- **(q)** `mum₀` + 7 substitutions = 70. Only one match and m = 8, so no anchor (the ceiling, 70 > 56, also fails). The page pass gives the same path, so `unaligned(8)`. ✓
- **(r)** Straight path 0 (min(2, 1) = 1, so no boundary charge); 4(a) run of 3; the repeat path costs 4 + 4 = 8. ✓
- **(s)** s2: 20. s3: 5 + 15 = 20. Deletion path: 20 (L3). Result: s2, candidates on blue and cat. ✓
- **(t)** `supply(3)`: `ccur` 3 → 4. "dog walked slowly": entry 1 vs insert 12, so 1; `dog` stays `M`. ✓
- **(u)** 0, then 5, then `dug`/`dog`: 0 + 10 + 5 = 15 (alternative at `walked₄`: 16). 4(d) holds with sim 0.67. Pause: `walked` and `slowly` are still `U`, so no completion. Then 5, 5. Result `C C C M C C`. ✓
- **(v)** `mat` 6 → 5 found by `miscue_id`; no overlap, so it stays a candidate. ✓
- **(w)** 15 + 8 + 8 = 31; internal 16 ≤ 35; run across the deleted `the` tokens. ✓ (`pcur` unstated, L10.)

Named inputs from the prompt:

- **Acceptance ceiling.** "The big dog ran home" heard "the bag dog run home":
  - bag/big substitute 10, run/ran inflection 10, so cost 20, internal 20 ≤ 35.
  - Runs: none of length ≥ 2. 4(b): 3 matched ≥ 3 → accepted. Candidate on `big`; `ran` observed `P`.
  - 20 ≤ 25, so no page pass.
  - The function-word variant fails on the anchor instead (L9).
- **4(d) on chatter.** M2.
- **`rest` at an older revision.** Maps `ccur` r→current and clamps it to a sentence start; edited tokens before `c` become `C` (L5).
- **Correction while the page read belongs to a closed cycle.** The page read keeps revision r. Its `unsure` and `confirmed` miscues are invalidated by span and Difficulties are recomputed. A later `rest` maps the cursor. This works, apart from L5.
- **`supply` then `/back`.** `M` stays; a reread match does not withdraw it; a second hint triggers H1.
- **Per-miscue budget after a page turn.** M4.
- **Refrain two sentences ahead.**
  - Reading the current sentence costs 0, so there is no page pass. A fast-pass jump to the refrain costs distance + 30.
  - The page pass runs only when cost_f > 5m, and the page path costs ≥ internal_f + 15.
  - So an identical refrain never displaces the current sentence, and the margin holds.
  - The reverse case, where the learner really skipped to the refrain, credits the current sentence. The tokens skipped ahead end `R`, with no candidate.
