# ADR-0013 v2, round 1: comparison of the two reviews and resolutions

Reviewers, run in parallel on the same prompt ([prompts/adr-0013-v2-round-1.md](prompts/adr-0013-v2-round-1.md)), neither reading the other: `code-plan-review` by a fresh Claude session ([record](2026-10-22-adr-0013-v2-code-plan-review.md), 3 High) and a fresh Claude session standing in for codex, whose quota ran out before it read anything ([record](2026-10-22-adr-0013-v2-claude.md), 2 High). Codex itself did not run this round; the increment round goes to codex when its quota returns.

## Tally (what each round was about)

The findings are not one class: they fall into six themes, and five of the six were found by both reviewers. Two themes rhyme with v1's history ("rules read together"): the start state of a page read and the token identity after a correction. Both are fixed here by one rule each, not by patches per scenario.

| Theme | code-plan-review | fallback | Resolution in ADR-0013 v2 rev 2 |
|---|---|---|---|
| Told (supplied) word withdrawn by the next match; no column | I2.1, G1.1 (Medium) | H1 (High) | `supply()` in the pseudocode; `miscues.origin` (`substitution`/`deletion`/`supplied`); alignment never withdraws a supplied candidate; a supplied function word is a candidate (a told word is an error whatever the word) |
| Page-read start state and page turns | F1.1 High (a turn completes an unstarted or partly read sentence; `provisional` stuck in completed sentences) | H2 High (a new cycle on the same page starts at token 0) | one `open_page_read` rule for every case (same cycle resume, `rest` from the learner's latest page read with the cursor mapped through edit maps, `{from, to}` / `familiar` fresh); a page turn or a non-terminal activity end completes nothing; a match in a completed sentence commits |
| Token identity after a correction | G2.2 High, G2.2 (page-read revision), I1.1 | M7 | tokens carry `miscue_id` through the edit map; `close_cycle` and Practice find the token by `miscue_id`; a correction re-tokenises every page read of that page in an open cycle in place (row moves to r+1); corrections are applied by the session process only while a session holds the lease; Practice's contradictory parenthesis removed |
| Slow and article-dropping readers | K1.1 High (pause completion, lone misreading, utterance-start deletions), K1.1 (page pass and dropped "the"), H7.2 (RA1 cited and contradicted) | M3 (a), (b) | completion (ii) waits while a content word is unattempted (RA1 adopted); acceptance 4(d): a lone plausible misreading at `pcur` (m = 1, content word, real word, confident, sim ≥ 0.5 or same first letter) is a candidate; runs span deleted function words; the page pass accepts 2 adjacent content words; the page pass is skipped for m < 2; the residual (a spoken lone function word, words before a mid-utterance jump back) is named in Consequences |
| Acceptance accepting the wrong path | K1.1 (refrain, Low) | M1 (chatter with one page word), M2 (lone function word against ADR-0017 §8), M5 (Run! Run! Run!), M6 (patterned books) | an internal-cost ceiling (7 per heard word, entry excluded) rejects a path after both passes; 4(c) only for m ≤ 2 and a content word (a lone function word anchors only when typed; ADR-0017 §8 amended to "spoken"); the boundary penalty only for sentences of ≥ 2 tokens, per visit; a fast-pass entry that skips a whole unattempted sentence costs 15 per sentence; a page path replaces an accepted fast path only by a margin of 10 |
| DP specification, numbers, inflections, performance | K1.1 (boundary per visit, back-jump bound, (g) cost 52, (i) repeat count, substitute-then-match), H7.1 (numbers, inflection, self-correction detector), K3.1 | M4 ((g) 52), M8 (numbers), M9 (DP ambiguity, ~4 s in v1's style), L1, L2 | boundary per visit including first and last; back jumps only after an aligned token, bounds written as formulas; (g) corrected (fast minimum 52, not accepted); `repeat` = a token already matched earlier in the path; substitute-then-match in one path is a self-correction with no miscue; no heard-side number collapsing: a DP `number join` (2–4 heard number words whose canonical reading equals one numeral's) at cost 0, canonical form without "and" and commas; `inflection` by shared lemma (`WordInfo.lemmas`, library chosen in M0 with research) so car/card stays a substitution; detector provenance *original, untuned*; the 100 ms bound covers `align` with `WordInfo` answers precomputed; a timed prototype and a brute-force oracle test are M0 gates |

## Smaller findings, each resolved

| Finding | From | Resolution |
|---|---|---|
| line-skip `unread` has no status filter | CPR F1.1 | only `unattempted`/`provisional` become `unread` |
| `category` mixes pair class and function word; deletions have none | CPR F1.1, FB L4 | two fields: `pair_class` (null for deletions and insertions), `function_word` |
| rejected utterances not counted; `observations` token columns NOT NULL | CPR G4.2, FB L5 | a rejected utterance writes one `unaligned` observation with null token columns (Migration 5) |
| "off-task" is a verdict on the child for a stage failure | CPR K2.1 | renamed `unaligned` ("words not tracked") everywhere |
| retry budget across page turns vs `practices.attempt` 1–2 | CPR G4.2 | the budget is per miscue: at most 2 attempts in total |
| idle attempt has no outcome; fail then idle unstated | CPR G4.2, FB L4, L8 | `practices.outcome` + `idle`; the final status rule states every sequence |
| `interrupted`, `unclear`, `idle` weights in Difficulties | CPR K2.1 | `interrupted` and `unclear` → 0 (no evidence about the learner); `disagreed` and `idle` keep 0.3 |
| low-confidence substitution becomes a candidate | CPR H7.2 | below `LOW_CONF` (0.5) a substitution is an observation only (research 2026-10-21 §3.3) |
| phonemic distance in the cost neither used nor rejected | CPR H7.2 | rejected for v2 with the reason (flat costs keep the cost ordering exact; revisit with the labelled set) |
| homographs (read/red) | FB L3 | `WordInfo.phones` returns a set; a small homograph table adds the second pronunciations |
| first-words prompt state lives in prose | FB L4 | `ReadingState` + `unaligned_run`, `unaligned_words`, `prompted` |
| versions that produced a category not stored | FB L4 | `page_reads.alignment_versions` |
| `created_by`, `miscue_id` missing from `ReadingState` | FB L4 | listed in Definitions |
| `pcur` defined twice | FB L6 | defined once, by rule 8 |
| "nothing is said at a sentence end" vs ADR-0017 §6.1 `sentence_end` | FB L6 | "except what ADR-0017 §6.1 allows" |
| one-candidate-per-token only in JSON | CPR B1.5 | partial unique index on `miscues(page_read_id, expected_token_index) WHERE status = 'candidate'` |
| a correction from another process during a session | CPR B2.1 | refused while a session holds the lease |
| ADR-0017 points at v1 rules (1–8, Reposition, "withdraws as reread") and `item_said` borrows the retry test | CPR I2.1 | ADR-0017 §3.4, §6.1, §8, §8.1 and its header updated; `item_said` gets its own whole-answer rule |
| CHECK: `judge` neither used nor rejected | CPR H7.2 | one line: ADR-0017 §3.4 owns `judge`; the keyword partition stays for counted quiz answers |
| reading eval is a repeated operation | CPR H5.1 | console button in the Confirmation and plan M10 |
| thresholds untuned without brackets | CPR K4.1 | `reading_eval.py` prints the distributions that bracket each one |
| inflection observations never reach Difficulties | FB L7 | named in Consequences; a future `pattern` knowledge item may consume them (not v2) |
| `tokens_committed` inflated by function-word misses | FB L7 | the summary reports `function_word_misses` beside it |

## Decisions the author made that the owner may override

- `unsure(interrupted)` and `unsure(unclear)` contribute 0 to Difficulties (v1 counted `interrupted` 0.3).
- A supplied function word is a candidate and is practised.
- A spoken lone function word never anchors; a typed one does (ADR-0017 §8 amended).
- The internal-cost ceiling (7 per heard word) rejects a heavily misread short utterance (3 substitutions in 4 words) as unaligned: no candidates rather than possibly false ones, to be tuned by the false-alarm evaluation.

## Not adopted

- Deferring completion of a skipped sentence until the next utterance confirms the jump (FB M6): the fast-pass skip penalty and the page-pass margin cover the patterned-book and refrain cases with no new pending state.
- An internal backward jump to any sentence start in the page pass (CPR K1.1, reading back three sentences): accepted as a named limit; the words before the jump are unaligned and nothing is miscredited.
