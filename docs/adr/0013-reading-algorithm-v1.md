---
status: accepted
date: 2026-10-19
supersedes: 0009, 0012
revised: 2026-10-19 (codex review round 4: exact DP costs and boundaries, terminal candidates, completion history, /back, control precedence, candidate settlement, CHECK partition)
---

# Reading algorithm v1: one owner for alignment, commitment, completion, practice and reconciliation

## Context

ADR-0007 → 0009 → 0012 refined the reading rules as prose; each codex round found interactions the prose left open. The class of defect is "rules in several sentences that must be read together". This ADR states the algorithm once, with exact costs and state, and every other document points here without restating it.

## Definitions

- `tokens[i]`, `i ∈ [0, n)`: expected tokens of the current page revision, each with `sentence_id`, `char_span` (half-open code points) and `status ∈ {unattempted, provisional, committed, candidate, settled, unread}`. `settled` = a former candidate whose miscue row reached a final status.
- `ReadingState = (page_read_id, revision_id, tokens, pcur, ccur, completed: set[sentence_id], turn_id)`. `pcur` = index of the first token that is not provisional/committed/candidate/settled after the last aligned token (the frontier); `ccur ≤ pcur`.
- Utterance words `w[0..m)` after `norm()` (lowercase, strip punctuation, number words, contractions table; versioned with `tokenizer_version`), optional per-word confidence (`None` when the ASR has none), optional `audio_ref`.
- `sim(a, b)` = `rapidfuzz.fuzz.ratio(a, b) / 100`.

## `align(state, utterance) -> (state', observations, events)` — pure, deterministic

```
1. lo = max(0, ccur − 6, sentence_start(ccur)); hi = min(n, pcur + ceil(1.5·m) + 8); window = tokens[lo:hi]
2. Global alignment of ALL heard words w[0..m) against window with these costs:
     match       0.0   if norm(w)==norm(tok)
     fuzzy match 0.3   if sim ≥ 0.80
     substitute  1.0
     delete tok  0.8   (expected token skipped between two aligned tokens)
     insert w    1.2   (heard word aligned to nothing; must exceed substitute so a heard word prefers an expected token)
     free gaps:  expected tokens before the first aligned token (any index ≥ lo) and after the last aligned token are free
                 (they stay in their current status; those after the last aligned token are "unattempted", never deleted)
     jump        0.1 × |first_aligned_index − pcur|
     boundary    0.5 for every sentence the path enters with fewer than 2 aligned tokens in it (keeps a stray trailing word
                 from becoming a substitution in the next sentence)
   Ties: lowest total cost; then first_aligned_index nearest pcur; then fewest insertions; then the lexicographically
   earliest path over (expected index, operation). This makes the result unique.
3. Accept the path iff (a) it has a run of ≥ 2 consecutive (match|fuzzy) tokens, or
                       (b) it has exactly one (match|fuzzy) token and its index ∈ [pcur − 2, pcur + 2].
   Otherwise: events = [unanchored]; return (state, [], events).         # §Reposition handles two in a row
4. Observations from the path: matched (incl. fuzzy, with sim), substituted(heard), deleted, inserted(heard, anchor = next
   expected index). An internal run of deleted tokens longer than 3 is NOT a deletion: those tokens become `unread`,
   events += line_skipped(count), and no candidate is created for them.
5. Status updates (in path order):
     matched tok:   unattempted|provisional|unread → provisional;  committed|settled → unchanged;
                    candidate → settled, its miscue → withdrawn(reason = self_corrected if this utterance is the one
                    immediately after the utterance that created the candidate, else reread)
     substituted:   unattempted|provisional|unread → candidate, new miscue(status=candidate, heard=w)
                    candidate → unchanged (the earlier row stays; a second candidate is not created)
                    committed|settled → unchanged (an already settled token is never re-opened by alignment)
     deleted (≤3):  same as substituted with heard = null
   pcur = max(pcur, last_aligned_index + 1)
6. Commit scan: while ccur < pcur and tokens[ccur].status ∈ {provisional, committed, candidate, settled}: ccur += 1
   (a candidate commits when reading moved past it; its miscue row keeps its own status)
7. events += sentence_reached(s) for every sentence s ∉ completed with last_index(s) < pcur
8. return (state', observations, events)
```

## Session rules that use the algorithm (owner: this ADR; `flows/reading-session.md` only draws them)

**Reposition.** Two consecutive `unanchored` events → align once against the whole page (lo = 0, hi = n) requiring a run ≥ 3 in rule 3; success: tokens between the old `ccur` and the new first aligned index become `unread`, `ccur = pcur = first_aligned_index`, then rules 4–7 apply; failure → state `REPOSITION`: Leafi asks for the first words of the learner's line; each following utterance is aligned page-wide with the run ≥ 3 rule; no candidates are created until anchored.

**Sentence completion** of sentence `s` happens on the first of: (i) `sentence_reached(s)`; (ii) the Listener yields nothing for `sentence_pause_s = 1.2` (voice) or the typed line ends with `. ? !` or is empty (text) while `pcur` ∈ last two token indexes of `s` or beyond; (iii) a control (`skip`, `next page`, page turn, `stop`) while `s` is the current sentence. On completion: `provisional` tokens of `s` → `committed`; `unattempted` tokens of `s` → `unread`; `candidate` tokens stay `candidate` (they were attempted); `ccur = max(ccur, last_index(s) + 1)`; `pcur = max(pcur, ccur)` (invariant `ccur ≤ pcur` holds); `completed += {s}`; `turn_id += 1`. If completion came from (i) or (ii): run **PRACTICE** for the candidates of `s` (at most 2, ordered by Difficulty weight then position; further candidates → `unsure(not_practised)`); if it came from (iii) `skip`: candidates → `unsure(skipped)`, no practice; from `next page` / page turn / `stop`: **page settlement** (every open candidate anywhere on the page → `unsure(skipped)`, their tokens `settled`), no practice, then FIND_PAGE / WRAP. Several `sentence_reached` events in one utterance are processed in order, each once. **After PRACTICE ends** (all candidates settled, or `skip` on the last one, or `/back`): → CHECK if every sentence is in `completed`, else READ.

**Page completion** = every sentence ∈ `completed` (or the learner turned the page / said next page) → CHECK over completed sentences. `tokens_unread` is reported in the summary; unread tokens are never practised.

**Practice** (per candidate, voice or text): Leafi models the word; retry 1: if `norm(retry) == norm(expected)` or `sim ≥ 0.80` → miscue `withdrawn(practice)`; else retry 2 with the same test; two disagreements → `unsure(disagreed)`; `skip` → `unsure(skipped)`; no retry within `PRACTICE_RETRY_S` (10 s voice; text waits) → `unsure(idle)` and practice continues with the next candidate (the session idle timer `STUDY_IDLE_S` runs only in READ/CHECK/REVIEW_DUE while awaiting input, never during PRACTICE); `stop` → page settlement. Each attempt writes a `practices` row with `evidence = acoustic` only when `PRON_AUTO_JUDGE` is on and the scorer ran (then the scorer may set `confirmed` instead of `unsure`), else `evidence = none`. **Text mode uses exactly these rules with `evidence = none`; `confirmed` is impossible there.** After the sequence the token becomes `settled`.

**`/back N`** (spoken "go back", typed `/back N`, N ≥ 1, default 1): let `cur` = the sentence containing `pcur − 1` when `pcur` is at a sentence start or at `n` (the last sentence with an attempted token), else the sentence containing `pcur`; target = `cur − (N − 1)` (clamped to the first sentence), so `/back 1` reopens `cur` only and `/back 2` reopens `cur` and the one before it. For every sentence from target to `cur` inclusive: remove from `completed`; tokens `committed|provisional|unread` → `unattempted`; `candidate` tokens stay (their rows stay `candidate`; a later match withdraws them as `reread`); `settled` tokens stay. `pcur = ccur = first_index(target)`; `turn_id += 1`. Allowed in READ, PRACTICE (open candidate of the aborted practice → `unsure(skipped)`), CHECK (returns to READ).

**Control precedence** (highest first): `stop` → complete the current sentence by (iii), page settlement → WRAP. `next page` / page turn → complete by (iii), page settlement (this covers a PRACTICE in progress) → FIND_PAGE. `/back` as above. `skip` → in PRACTICE: current candidate `unsure(skipped)`, then the next candidate, else CHECK/READ per "After PRACTICE ends"; in READ: complete the current sentence by (iii) and set `pcur = ccur = first_index(next sentence)`; in CHECK/EXPLAIN/REVIEW_DUE: leave the state with no record. A control that does not apply → spoken no-op.

**Interrupted session.** On startup, stale sessions are closed: their open candidates become `unsure(interrupted)` (tokens `settled`); the last page read's `ReadingState` is kept. A new session on the same book offers "continue from page N?"; yes → new `page_reads` row (`attempt + 1`) with `ccur = pcur = old ccur`, tokens before it `committed`, the rest `unattempted`, `completed` = sentences entirely before `ccur`.

**Async guard** `(session_id, revision_id, turn_id)`; `turn_id` increments on sentence completion, `skip`, `/back`, `stop`, state change.

**Cancellation during playback** comes from the console/Face (`/stop`, key); spoken `stop` works while listening.

**Input routing by state**: READ → `align`; PRACTICE → retry test; CHECK → local keyword comparison; REVIEW_DUE → `again`/`good`; EXPLAIN/CORRECT → that grammar; controls everywhere.

## Correction interaction (coordinates: ADR-0010 §6)

A correction creates revision r+1 with an edit map. The current `ReadingState` is re-tokenised on r+1: tokens whose mapped char span overlaps the edited span → `unattempted`; `pcur`, `ccur` are mapped through the edit map and clamped to the first such token when they were past it; sentences containing such tokens leave `completed`. Miscues of **any** revision of this page with status ∈ {candidate, unsure, confirmed} whose `expected_char_span` maps (through the chain of edit maps up to r) into a span overlapping the corrected span → `invalidated(page_text_corrected)`; `withdrawn` and already-`invalidated` rows are untouched. Difficulties are recomputed inside the same transaction.

## Difficulties (single formula; data-model.md repeats only column names)

For a word (miscues): `weight = Σ_s v(s) × 0.5^(days_since(s)/30)` over sessions `s`, with `v(s) = 1.0` if the word had a `confirmed` miscue in `s`, else `0.3` if it had an `unsure` miscue in `s`, else 0. A row exists only if `confirmed` evidence exists in ≥ 1 session (`kind = confirmed`) or, with no confirmed evidence, `unsure` evidence in ≥ 3 distinct sessions (`kind = watch`); once a row exists every session's `v(s)` contributes.
For a knowledge item (encounters): `weight = Σ_s e(s) × 0.5^(days_since(s)/30)` with `e(s) = 1.0` if session `s` has an encounter with `trigger ∈ {check(incorrect), explain}` for the item; a row exists only with encounters in ≥ 2 distinct sessions (`kind = knowledge`).
Watch items order Practice and never produce a "wrong" line or a card by themselves.

## CHECK outcomes (exhaustive)

1. `unavailable` if the Brain did not return questions, or the learner skips / says "I don't know" / gives no answer within `CHECK_ANSWER_S` (20 s voice, no limit text).
2. else `correct` if, after `norm`, all keywords of at least one acceptable answer are present.
3. else `incorrect` if the answer contains ≥ 2 content words (words not in the stop-word list `study/stopwords.py`).
4. else `unavailable` (too little to judge).
Leafi then gives the answer in the Coach voice regardless; only `incorrect` writes an `encounters` row (`trigger=check`).

## Walkthroughs (expected results; `tests/test_alignment.py` encodes them)

- (a) "The little brown dog walked slowly." one word per utterance: each singleton accepted by rule 3(b); after "slowly" `sentence_reached`; completion commits all six; no miscues.
- (b) "The dog ran." heard "The dog red.": `red` → substitute (1.0 < insert 1.2) → candidate at `ran`; `sentence_reached` completes the sentence at once (`C C M`, cursors (3,3)); PRACTICE runs; no retry within `PRACTICE_RETRY_S` → `unsure(idle)`; token settled; the page is complete → CHECK.
- (c) "The little cap" / "cat sat on the mat.": utterance 1 → candidate at `cat` (substitute); utterance 2 matches `cat` → `withdrawn(self_corrected)`, token `settled`; completion commits the rest (`C C S C C C C`); no practice.
- (d) "I can see it. I can see it." read sentence by sentence: the second identical utterance advances into sentence 2 (cheaper by the jump rule) and completes it; `completed` prevents any repeated event; `/back 1` then reopens sentence 2 only (`C C C C U U U U`, cursors (4,4), `completed = {1}`).
- (e) "The dog ran away." against "The dog ran. The cat sat.": `away` → insert (1.2) rather than substitute `The` of sentence 2 (1.0 + 0.5 boundary); no candidate.
- (f) a skipped line of 6 tokens: `line_skipped(6)`, tokens unread, reading continues.

## Consequences

- One function, one state, scenario tests; other documents reference sections of this ADR by name.
- Identical consecutive sentences read twice count as progress (accepted; `/back`).
- ADR-0009 and ADR-0012 are superseded; their option analysis stays for history.
