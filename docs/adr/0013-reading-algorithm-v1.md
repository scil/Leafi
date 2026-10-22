---
status: proposed
v1: accepted 2026-10-19, implemented in `leafi/study/alignment.py` (the code follows v1 until this v2 is accepted; ADR-0017 §8)
date: 2026-10-19
revised: 2026-10-22 (v2: ADR-0017 §8.1–8.6 as pseudocode; the prior-art changes to alignment; v1 revised 2026-10-19 after codex round 4)
supersedes: 0009, 0012
---

# Reading algorithm: one owner for alignment, commitment, completion, practice and reconciliation

The file keeps its v1 name so that links stay valid; this text is v2. v1 is in git history (`git show 8a14e74:docs/adr/0013-reading-algorithm-v1.md`).

## Context

ADR-0007 → 0009 → 0012 refined the reading rules as prose; each codex round found interactions the prose left open, so v1 stated the algorithm once, with exact costs and state. Every other document points here and restates nothing.

v2 has two inputs. **ADR-0017 §8** moves practice out of reading: no correction happens while the learner reads, errors are practised afterwards by the `practise_errors` activity, and candidates live in a cycle across sentences and pages. **The domain prior art** ([`../research/2026-10-22-domain-prior-art.md`](../research/2026-10-22-domain-prior-art.md) §1, top changes 1–3) found that v1 credits real-word misreadings as correct (house/horse, though/through at `sim ≥ 0.80`), cannot reach a sentence after a lost start (the bounded window and the `run ≥ 2` acceptance forced "She smiled at the clever fox" onto sentence 1 in session 11, research 2026-10-21 §3.3), treats rereads as insertions, and practises function words, which Project LISTEN stopped doing to halve its false alarms. Provenance of every v2 mechanism: §Provenance.

## Definitions

- `tokens[i]`, `i ∈ [0, n)`: expected tokens of the current page revision, each with `sentence_id`, `char_span` (half-open code points), `function_word` (bool, from `FUNCTION_WORDS`) and `status ∈ {unattempted, provisional, committed, candidate, settled, unread}`. `settled` = a former candidate whose miscue row reached a final status.
- `ReadingState = (page_read_id, revision_id, tokens, pcur, ccur, completed: set[sentence_id], turn_id, off_task_run)`. `pcur` = the frontier (index of the first token that is not provisional/committed/candidate/settled after the last aligned token); `ccur ≤ pcur`.
- **Page read.** One pass over a page at one revision. Within one cycle (ADR-0017 §1) a `(page, revision)` has at most one page read: returning to a page in the same cycle resumes its page read with its saved state; a new cycle starts a new page read (`attempt + 1`).
- Utterance words `w[0..m)` after `norm()` and number collapsing (below), each with a confidence (`None` = typed; a typed word counts as confident everywhere in this ADR), optional `audio_ref`.
- `sim(a, b)` = `rapidfuzz.fuzz.ratio(a, b) / 100`.
- **`WordInfo`** is a port the session passes into `align`, so `align` stays pure: `is_word(w)` (the word is in the household lexicon or in the bundled frequency word list that ADR-0017 §6.2 ranks with) and `phones(w)` (espeak-ng phones without stress marks, cached per word, versioned `phones_version`; `None` when no phonemizer is configured, and then the phone test is skipped). Tests use a table.
- **`FUNCTION_WORDS`**: a fixed, versioned list in `study/function_words.py` (articles, auxiliaries, pronouns, prepositions, conjunctions; Project LISTEN's 36 function words plus their contractions). It is not `study/stopwords.py`, which serves CHECK. A content word is any other word.

### `norm()` v2 (`TOKENIZER_VERSION = 2`)

v1's rules (lowercase, strip punctuation, contractions table) plus numbers through `num2words`: an expected numeral token gets every reading it can have — cardinal; ordinal for `1st`, `2nd`, …; a year reading for four digits 1100–2099 ("nineteen ninety") — each written without spaces or hyphens (`twentyone`). Heard words are collapsed before alignment: a maximal run of number words that parses as one number (`twenty one`, `twenty-one`, `nineteen ninety`) becomes one word. An expected numeral matches a heard word equal to any of its readings. **Token boundaries do not change from v1**, so stored reading states stay valid; only `norm` values change.

### Pair classes

`pair(heard, tok)`, first match wins:

| Class | Test | Alignment cost (tenths) | Counts as matched |
|---|---|---|---|
| `exact` | `norm(heard) == tok.norm` (or one of a numeral's readings) | 0 | yes |
| `phones` | `phones(heard) == phones(tok)`, both not `None` (homophones: threw/through; ASR spelling variants) | 0 | yes |
| `inflection` | heard ≠ expected and, after removing at most one suffix from `{s, es, ed, d, ing, 's}` from each, the two stems are equal (walked/walk, smiles/smiled) | 10 | no |
| `fuzzy` | `sim ≥ 0.80` and `not is_word(heard)` (a garbled or partial word; typed typos) | 3 | yes |
| `substitute` | anything else, **including a real word at `sim ≥ 0.80`** (house/horse, there/three, though/through) | 10 | no |

## `align(state, utterance, info) -> (state', observations, events)` — pure, deterministic

```
1. FAST PASS over window W_f = tokens[lo:hi]:
     lo = max(0, ccur − 6, sentence_start(ccur)); hi = min(n, pcur + ceil(1.5·m) + 8)       # v1's window
     path_f = best_path(W_f, entry_cost = fast_entry)
2. PAGE PASS when path_f is not accepted (rule 4) or cost(path_f) > 5·m   (0.5 per heard word, untuned):
     path_p = best_path(tokens[0:n], entry_cost = page_entry)
     use path_p when it is accepted and cost(path_p) < cost(path_f) (or path_f is not accepted); else path_f
3. best_path(window, entry_cost): global alignment of ALL heard words w[0..m) against the window, costs in tenths:
     align word j at token i      pair cost (§Pair classes): exact 0, phones 0, fuzzy 3, inflection 10, substitute 10
     delete tokens (affine)       a run of L ≥ 1 expected tokens skipped between two aligned tokens: 8 + 3·(L − 1)
     insert word                  12   (must exceed substitute, so a heard word prefers an expected token)
     back jump (reread)           after aligning token a, align the next word at token k with
                                  sentence_start(a) − (previous sentence) ≤ k ≤ a: 4 + 1·(a − k)
                                  (fast pass: k ≥ lo; page pass: k ≥ sentence_start(a), i.e. within the sentence)
     free gaps                    expected tokens before the first aligned token and after the last aligned token
     entry                        fast_entry(f) = 1·|f − pcur|;
                                  page_entry(f) = 1·|f − pcur| when |f − pcur| ≤ 2, else 15 (one flat jump anywhere)
     boundary                     5 for every sentence the path enters (by advancing or by a jump) with fewer than 2
                                  aligned tokens in it
   Ties: lowest total cost; then first aligned index nearest pcur; then fewest insertions; then fewest back jumps;
   then the lexicographically earliest path over (expected index, operation). The result is unique.
4. ACCEPT the path iff it has an anchor:
     (a) a run of ≥ R consecutive matched tokens (exact | phones | fuzzy, adjacent in index and in the path) that
         contains a content word; R = 2 in the fast pass, 3 in the page pass; or
     (b) ≥ 2 matched tokens, one of them a content word, and matched ≥ ceil(m / 2)   (fast pass only); or
     (c) exactly one matched token, its index ∈ [pcur − 2, pcur + 2], and it is a content word or its heard
         word's confidence ≥ ANCHOR_CONF (0.8, untuned)   (fast pass only)
   Not accepted by either pass → events = [off_task(m)]; state'.off_task_run += 1; return (state', [], events).
5. Observations from the path, each with its pair class: matched (exact | phones | fuzzy, with sim; `repeat` when
   reached by a back jump), substituted(heard, class inflection | substitute), deleted, inserted(heard, anchor = next
   expected index). A run of ≥ 3 consecutive inserted words → one `off_task(count)` observation instead of insertions.
   An inserted word directly before a matched token k with sim(heard, tok_k) ≥ 0.5 or the same first letter is marked
   `self_correction` (running-record convention: a self-correction is not an error). An internal deletion run of
   L ≥ 4 is not a deletion: its tokens become `unread`, events += line_skipped(L), no candidate.
6. Entry beyond the frontier (page pass with first aligned index f > pcur): tokens in [pcur, f) still `unattempted`
   in sentence(f) → `unread`. (Earlier sentences are completed by rule 9's events.)
7. Status updates in path order:
     matched tok:      unattempted|provisional|unread → provisional;  committed|settled → unchanged;
                       candidate → settled, its miscue → withdrawn(self_corrected if this utterance is the one
                       immediately after the utterance that created the candidate, else reread)
     substituted or deleted (≤ 3), tok unattempted|provisional|unread:
                       tok.function_word, or class inflection with reading.inflections = observe (default)
                         → provisional; no miscue (the observation keeps the category; it is never practised)
                       otherwise → candidate, new miscue(status = candidate, heard = w or null, cycle_id = s.cycle)
     substituted or deleted, tok candidate|committed|settled → unchanged (one candidate per token; a settled token is
                       never re-opened by alignment)
   pcur = max(pcur, last_aligned_index + 1); off_task_run = 0
8. Commit scan: while ccur < pcur and tokens[ccur].status ∈ {provisional, committed, candidate, settled}: ccur += 1
9. events += sentence_reached(s) for every sentence s ∉ completed with last_index(s) < pcur
10. return (state', observations, events)
```

`align` must finish in ≤ 100 ms p95 on this PC for a 400-token page and 25 heard words, page pass included (`tests/test_alignment_perf.py`, hardware-marked); an implementation may vectorise the DP but must return the same path.

## Off-task speech and the first-words prompt

An `off_task` utterance changes no token and creates nothing. When `off_task_run ≥ OFF_TASK_PROMPT` (3) and those utterances hold ≥ 6 heard words, Leafi says once per such stretch "Where are you reading? Read me the first words of your line." (recovery dialogue, always allowed, ADR-0017 §6.1). Every following utterance is aligned by the same rules (the page pass included), so no separate REPOSITION state exists; the v1 two-strike Reposition is removed.

## Sentence completion

Sentence `s` completes on the first of: (i) `sentence_reached(s)`; (ii) the Listener yields nothing for `sentence_pause_s = 1.2` (voice) or the typed line ends with `. ? !` or is empty (text) while `pcur` ∈ the last two token indexes of `s` or beyond; (iii) a control (`skip`, `next page`, page turn, `stop`) or the end of the `read_listen` activity for any other reason while `s` is the current sentence. On completion: `provisional` tokens of `s` → `committed`; `unattempted` tokens of `s` → `unread`; `candidate` tokens stay `candidate`; `ccur = max(ccur, last_index(s) + 1)`; `pcur = max(pcur, ccur)`; `completed += {s}`; `turn_id += 1`. Several `sentence_reached` events in one utterance are processed in order, each once. **Nothing is practised and nothing is said at a sentence end** (ADR-0017 §8.4; speech inside reading follows ADR-0017 §6.1 only).

**Range and page completion.** A `read_listen` activity reads a range of the page read (`rest` or `{from, to}`, ADR-0017 §3.1); alignment always runs on the whole page read. The activity ends `completed` when every sentence of its range is in `completed`. `tokens_unread` is reported; unread tokens are never practised. What follows is chosen at the next boundary (ADR-0017 §2), not here.

## Cycles and candidates (ADR-0017 §8.1)

```
on miscue created by align:      miscue.cycle_id = s.cycle.id          # the cycle of the read_listen running
open_candidates(cycle)           = miscues with cycle_id = cycle.id and status = candidate
withdrawal while the cycle is open: rule 7 (a later match, in any read_listen of the cycle, on that page read)
close_cycle(cycle, reason):                                            # one transaction
  for m in open_candidates(cycle):
    m.status = unsure; m.unsure_reason = {stop: skipped, interrupted: interrupted}.get(reason, not_practised)
    tokens[m.expected_token_index].status = settled in m's page read state (persisted)
  cycle.status = closed; cycle.closed_reason = reason
close_cycle reasons: next_reading (another boundary-chosen read_listen or read_aloud starts), wrap, stop,
  interrupted (startup recovery), and the other terminal statuses of ADR-0017 §2 (→ not_practised)
```

`/back` reopening a candidate's sentence leaves it `candidate` (rule `/back N`). A correction invalidating a candidate removes it from the open set (§Correction interaction).

## Page turns and continuations (ADR-0017 §8.2)

A page turn or `next page` during `read_listen` completes the current sentence by (iii) and ends the activity with `page_turned`, **without settling anything**. When the learner keeps reading, ADR-0017 §2 starts a continuation `read_listen` in the same cycle on the new page: its page read is the cycle's existing one for `(page, revision)` if there is one (resumed with its state), else a new one. This repeats on every further turn. A page turn during `practise_errors` ends it with `page_turned`; the candidate being practised and the unpractised ones stay `candidate`, owned by the cycle.

## Practice (run by `practise_errors`, ADR-0017 §3.1)

Per selected candidate, in the order ADR-0017 gives (Difficulty weight, then position), on **that candidate's own page read** (its page and revision; a candidate whose revision was corrected is no longer open):

1. Leafi shows the candidate's sentence on Faces and models the word (TTS).
2. The learner retries, at most twice. With `ASR_HOTWORDS` on, the retry stream carries the target word as its only hotword; reading streams never carry page hotwords (a page-biased ASR would hide miscues).
3. Each retry is `pass` when some heard word, after `norm` and number collapsing, is the target by class `exact` or `phones` and its confidence ≥ `RETRY_MIN_CONF` (0.5, untuned); `fail` when every heard word has confidence ≥ `RETRY_MIN_CONF` and none passes; else `unclear`. Fuzzy and inflection classes never pass a retry.
4. A `pass` → miscue `withdrawn(practice)`. Two retries without a pass → `unsure(disagreed)` if either was `fail`, else `unsure(unclear)`. `skip` → `unsure(skipped)`. No retry within `PRACTICE_RETRY_S` (10 s voice; text waits) → `unsure(idle)`, and practice continues with the next candidate.
5. Each attempt writes a `practices` row with `outcome ∈ {matched, disagreed, unclear, skipped}` and `evidence = acoustic` only when `PRON_AUTO_JUDGE` is on and the scorer ran (then the scorer may set `confirmed` instead of `unsure`), else `evidence = none`. **Text mode uses exactly these rules with `evidence = none`; `confirmed` is impossible there.**
6. After its sequence the token becomes `settled` in its page read state.

Candidates on function words never exist (rule 7), so they are never practised.

## `/back N`

Spoken "go back", typed `/back N`, N ≥ 1, default 1, **within the current page read only**: let `cur` = the sentence containing `pcur − 1` when `pcur` is at a sentence start or at `n` (and `pcur > 0`), else the sentence containing `pcur`; target = `cur − (N − 1)` (clamped to the first sentence). For every sentence from target to `cur` inclusive: remove from `completed`; tokens `committed|provisional|unread` → `unattempted`; `candidate` tokens stay (a later match withdraws them as `reread`); `settled` tokens stay. `pcur = ccur = first_index(target)`; `turn_id += 1`. `/back` never crosses a page: on a page with nothing read yet it reopens the first sentence and Leafi says "To read the last page again, turn back to it." (recovery dialogue); turning back resumes that page's page read in the same cycle (§Page turns). Allowed in `read_listen`; in `practise_errors` it is a spoken no-op ("Let's finish these words first, or say skip.").

## Control precedence (highest first)

| Control | In `read_listen` | In `practise_errors` |
|---|---|---|
| `stop` | complete the current sentence by (iii); the activity ends `stopped`; `finalize` closes the cycle with reason `stop` | current candidate → `unsure(skipped)`; the activity ends `stopped`; `finalize` closes the cycle with reason `stop` |
| `next page` / page turn | complete by (iii); ends `page_turned` | ends `page_turned`; candidates stay `candidate` |
| `/back N` | as above | spoken no-op |
| `skip` | complete the current sentence by (iii); `pcur = ccur = first_index(next sentence)`; the activity continues, or ends `completed` when its range is complete | current candidate → `unsure(skipped)`; the next candidate, or the activity ends `completed` |

A control that does not apply → spoken no-op. Other activities' controls are ADR-0017 §3.1's.

## Interrupted session (ADR-0017 §8.5)

On startup a stale session's `running` activity becomes `interrupted` and its open cycle closes with reason `interrupted`, so its candidates become `unsure(interrupted)` (tokens `settled`); guest end states follow ADR-0018 §1. Each page read keeps its `ReadingState`. A new session of the same learner on the same book offers "continue from page N?" using that learner's last page read of that book; yes → a new page read (`attempt + 1`) with `ccur = pcur = old ccur`, tokens before it `committed`, the rest `unattempted`, `completed` = sentences entirely before `ccur`.

## Async guard

The ADR-0017 epoch replaces v1's `(session_id, revision_id, turn_id)`; `turn_id` increments on sentence completion, `skip`, `/back`, `stop`, a page turn, and every event ADR-0017 §1 lists.

**Input routing by activity**: `read_listen` → `align`; `practise_errors` → the retry test; `quiz` → CHECK outcomes; `review_anki` → the ease grammar; controls everywhere. Cancellation during playback comes from the console or a Face (`/stop`, a key); spoken `stop` works while listening.

## Correction interaction (coordinates: ADR-0010 §6)

A correction creates revision r+1 with an edit map. The current `ReadingState` is re-tokenised on r+1: tokens whose mapped char span overlaps the edited span → `unattempted`; `pcur`, `ccur` are mapped through the edit map and clamped to the first such token when they were past it; sentences containing such tokens leave `completed`. Miscues of **any** revision of this page with status ∈ {candidate, unsure, confirmed} whose `expected_char_span` maps (through the chain of edit maps up to r) into a span overlapping the corrected span → `invalidated(page_text_corrected)`; `withdrawn` and already-`invalidated` rows are untouched. An invalidated candidate leaves its cycle's open set. Difficulties are recomputed inside the same transaction.

## Difficulties (single formula; data-model.md repeats only column names)

For a word (miscues): `weight = Σ_s v(s) × 0.5^(days_since(s)/30)` over sessions `s`, with `v(s) = 1.0` if the word had a `confirmed` miscue in `s`, else `0.3` if it had an `unsure` miscue in `s` with reason ∈ {`disagreed`, `unclear`, `idle`, `interrupted`}, else 0. `unsure(not_practised)` and `unsure(skipped)` contribute 0 and do not count toward the existence rule (ADR-0017 §8.6). A row exists only if `confirmed` evidence exists in ≥ 1 session (`kind = confirmed`) or, with no confirmed evidence, counting `unsure` evidence in ≥ 3 distinct sessions (`kind = watch`); once a row exists every session's `v(s)` contributes. Function words never have miscues, so they never become word Difficulties.

For a knowledge item (encounters): `weight = Σ_s e(s) × 0.5^(days_since(s)/30)` with `e(s) = 1.0` if session `s` has an encounter with `trigger ∈ {check(incorrect), explain, teach_incorrect}` for the item; `teach_ok` is ignored; a row exists only with counting encounters in ≥ 2 distinct sessions (`kind = knowledge`).

Watch items order Practice and never produce a "wrong" line or a card by themselves. The values 30, 0.3 and 3 are *untuned*: a priority score, not a recall model (Anki owns memory, ADR-0004).

## CHECK outcomes (exhaustive; run by `quiz`)

ADR-0017 §3.4 decides first whether an answer is counted at all (a spoken answer counts only when confidently recognised; an uncounted one is `unavailable` and writes no encounter). For a counted answer:

1. `unavailable` if the Brain did not return questions, or the learner skips / says "I don't know" / gives no answer within `CHECK_ANSWER_S` (20 s voice, no limit text).
2. else `correct` if, after `norm`, all keywords of at least one acceptable answer are present.
3. else `incorrect` if the answer contains ≥ 2 content words (words not in `study/stopwords.py`).
4. else `unavailable` (too little to judge).

Leafi then gives the answer in the Coach voice regardless; only `incorrect` writes an `encounters` row (`trigger = check`).

## Running-record conventions and reported counts

Self-correction and repetition are not errors; a word Leafi supplied is (ADR-0017 §6.1 makes it a candidate with `heard = null`, reason `supplied`). Per page read the summary reports, from the observations: words matched, substitutions and deletions by category (`substitute`, `inflection`, `function_word`), candidates, `self_corrections` (rule 5 marks plus `withdrawn(self_corrected)`), `repetitions` (back-jump matches), `off_task_words`, `tokens_unread`. These map to running-record categories in the parent's export; no number is shown to the child.

## False-alarm budget

A **false alarm** is a candidate on a token the learner read correctly, by a human label. Budget: ≤ 5 % of correctly read content-word tokens per page read on the labelled recordings set (*untuned*; Project LISTEN reached < 1 % at 23 % detection). The miss rate is reported, with no budget. The set (`data/evals/reading/`, local, never committed) holds the owner's readings with deliberate errors and, later, the learner's labelled readings; `scripts/evals/reading_eval.py` replays it through `align` and prints both rates. A budget breach is a tech-debt row; the first levers are the page-pass trigger, `ANCHOR_CONF` and `reading.inflections`. Until the budget is met, practice lines frame every candidate as "let's practise", never as wrong (product non-goal).

## Walkthroughs (expected results; `tests/test_alignment.py` and `tests/test_cycle_candidates.py` encode them)

Status codes: U unattempted, P provisional, C committed, M candidate, S settled, R unread.

- (a) "The little brown dog walked slowly." typed one word per utterance: each singleton accepted by rule 4(c) ("The" is a function word but typed, so confident; spoken at confidence 0.6 it would be `off_task`); after "slowly" `sentence_reached`; completion commits all six; no miscues.
- (b) "The dog ran." heard "The dog red.": `red`/`ran` is `substitute` (10 < insert 12); anchor 4(a) "The dog"; candidate at `ran` owned by the cycle; `sentence_reached` completes the sentence (`C C M`, cursors (3, 3)); nothing is practised or said; the range is complete → `read_listen` ends `completed`. At the next boundary `practise_errors` runs it: no retry within 10 s → `unsure(idle)`, token `S`.
- (c) "The little cap" / "cat sat on the mat.": utterance 1 → candidate at `cat` (`cap` is `substitute`, sim 0.67); utterance 2 enters at `cat` (entry 1 beats inserting "cat", 12) and matches it → `withdrawn(self_corrected)`, token `S`; completion → `C C S C C C C`.
- (d) "I can see it. I can see it." read sentence by sentence: the second identical utterance aligns in the window starting at sentence 2 and completes it; `/back 1` reopens sentence 2 only (`C C C C U U U U`, cursors (4, 4), `completed = {1}`).
- (e) "The dog ran away." against "The dog ran. The cat sat.": `away` → insert (12) rather than substitute `The` of sentence 2 (10 + boundary 5); no candidate.
- (f) A skipped line of 6 tokens inside an utterance ("A B C D K L" against "A B C D E F G H I J K L"): delete run 8 + 3·5 = 23; v1's cheaper "jump ahead and substitute four words" path costs 6 + 40 here; `line_skipped(6)`, E–J `R`, no candidate.
- (g) **Lost start (session 11).** Page: s1 "At the edge of the wood lived a clever old fox." (tokens 0–10), s2 "Every morning he walked down to the river to drink." (11–20), s3 "She smiled at the clever fox." (21–26); `pcur = ccur = 0`; heard "she smiled at the clever fox". Fast window `[0, 17)` cannot reach s3; its best path inserts "she smiled" (24), matches `at the` (0–1), deletes 2–7 (8 + 15), matches `clever` (8), deletes `old` (8), matches `fox` (10): cost 55. Its only run (`at the`) has no content word, but 4(b) accepts it (4 of 6 matched); the page pass runs because 55 > 5·6: entry at 21 (15) and six exact matches, cost 15 < 55 → used. s1 and s2 complete by (i) with every token `R`; s3 `C`; **no candidate** (v1: four false candidates in s1).
- (h) **Real-word misreading.** "The horse ran." heard "the house ran": `house`/`horse` sim 0.80 but `is_word(house)` → `substitute`; matched `the`, `ran` (2 of 3, `ran` content) → accepted by 4(b); candidate at `horse` (v1 credited it as fuzzy). Typed "the hosre ran" → `hosre` is not a word → `fuzzy`, matched, no candidate.
- (i) **Reread inside an utterance.** "The dog ran fast." heard "the dog the dog ran fast": back jump from `dog` (a = 1) to `the` (k = 0) costs 4 + 1 = 5 against inserting "the dog" (24); the second pair is `matched` with `repeat`; `repetitions = 2`; no insertion, no candidate. Heard "the little cap cat sat" for "The little cat sat": inserting `cap` (12) beats substitute + back jump (10 + 4); `cap` is marked `self_correction` (sim 0.67 ≥ 0.5); no candidate.
- (j) **A → B → C in one cycle.** `read_listen` on A opens cycle k; A s1 gets a candidate at A:3; the learner turns the page in A s2 → s2 completes by (iii) (its unattempted tokens `R`), the activity ends `page_turned`, nothing settles; continuation on B (same cycle, new page read); a candidate at B:5; turn → continuation on C; C completes → `completed`. `open_candidates(k) = {A:3, B:5}`. The next boundary runs `practise_errors([A:3, B:5])`, each on its own page read (A's state, then B's); then a boundary-chosen `read_listen` starts → `close_cycle(k, next_reading)`, which finds nothing open. Had practice been refused, both would become `unsure(not_practised)` and contribute 0 to Difficulties.
- (k) **`/back` across a page turn.** After (j)'s turn to B, before anything is read on B, "go back": B's page read has `pcur = 0`, so `cur` = B's first sentence, nothing changes but `turn_id`, and Leafi says to turn back. The learner turns back to A → `page_turned` → continuation on A resumes A's page read (cursors where they were, A:3 still `M`). Rereading A s1: the fast window (starting at A's current sentence) does not contain s1, the fast pass is not accepted, the page pass anchors on s1, and the match at A:3 → `withdrawn(reread)`.
- (l) **`stop` mid-practice.** `practise_errors([A:3, B:5, C:2])` is on B:5 when the learner says stop: A:3 is already settled; B:5 → `unsure(skipped)`; the activity ends `stopped`; `finalize` closes the cycle with reason `stop` → C:2 → `unsure(skipped)`; all three tokens `S` in their page reads.
- (m) **Off-task chatter.** During `read_listen`, "mum can I have a snack after this": no content-word run in either pass and nothing near `pcur` → `off_task(8)`, no state change. Three such utterances in a row → the first-words prompt, once.
- (n) **Lone function word.** At `pcur` on "the" of "… to the park", heard "the" at confidence 0.6 → not accepted (function word, below `ANCHOR_CONF`) → `off_task(1)`; at 0.9 → accepted by 4(c).
- (o) **Numbers.** "He was 21." heard "he was twenty one" → collapsed to `twentyone` = the numeral's cardinal reading → `exact`. "in 1990" heard "in nineteen ninety" → the year reading.
- (p) **Inflection.** "She smiled at the fox." heard "she smiles at the fox": `smiles`/`smiled` stems equal → `inflection`; with `reading.inflections = observe` the token is `P` and the observation keeps the category; with `practise` it is a candidate.

## Provenance

| Mechanism | Verdict | Source |
|---|---|---|
| token statuses, `ReadingState`, commit scan | original (tutoring state) | prior-art §1 #1, #10 (Project LISTEN "chase the kid" to track, "blame the kid" to credit) |
| global DP with substitute < insert, boundary penalty | adapted | Needleman–Wunsch via ADR-0007; values original, *untuned* |
| fast window + page pass with a flat entry jump | adapted | Project LISTEN MultiMatch jump model (RA1); prior-art §1 #2, #12; research 2026-10-21 D5 |
| back jumps (rereads are reading) | adapted | RA1 (regressions are reading, jump penalty on non-sequential transitions) |
| affine deletions | adopted | affine gap costs (RA17); replaces v1's cost-ordering surprise of 2026-10-20 |
| real-word pairs are substitutions; phone equality | adapted | RA1 (phonemic mismatch distance), RA14 (graphic miscues), RA23 (computed pairs) |
| inflection class, observe by default | original | RA1 and RA3 (dropped endings are the most frequent decoding error; dialect) — decided for an L2 learner whose ASR drops endings at an unmeasured rate |
| function words never practised and never a lone anchor | adopted | RA3 (LISTEN halved false alarms by ignoring 36 function words); RA2 |
| acceptance with a content word; `off_task` | adapted | RA2 (17.6 % of child speech off-task; sentence words seldom occur two in sequence) |
| ≥ 3 inserted words → off-task observation | adapted | research 2026-10-21 §3.3 off-task rule (marked unverified there; probably Chen & Mostow 2011) |
| first-words prompt as the last fallback | original | v1 Reposition, kept as a prompt |
| self-correction count, running-record categories | adopted | RA14 (after Clay 1993) |
| `num2words` readings | adopted | RA13 (num2words 0.5.14, LGPL-2.1) |
| practice retry: exact or same phones, confidence-gated, hotword only on the retry | adapted | RA5 (Reading Coach word practice), RA9 (sherpa-onnx hotwords in `modified_beam_search`), RA1 ("distracters detract") |
| cycle-owned candidates, settlement at close, continuations | original | ADR-0017 §8.1–8.2 (owner requirement 2.2a) |
| false-alarm budget | adapted | RA1 (< 1 % false alarms at 23 % detection) |
| Difficulties formula | original, *untuned* | RA10 (half-life regression is the recall model Leafi does not build) |
| CHECK keyword partition | original | RA12 (keyword matching is the baseline) |

## Consequences

- One function, one state, scenario tests; other documents reference sections of this ADR by name.
- Real-word misreadings now become candidates, so more candidates appear than in v1; the false-alarm budget is what keeps that honest, and function words and (by default) inflections are observed, never practised.
- A lost start no longer forces speech onto the wrong sentence; the cost is a page pass on poor utterances, bounded by the performance test.
- Practice leaves reading entirely; reading speaks only as ADR-0017 §6.1 allows.
- New data: `WordInfo` (a word list and espeak-ng phones), `num2words`, `FUNCTION_WORDS`, and the columns listed in `data-model.md`.
- Identical consecutive sentences read twice count as progress (accepted; `/back`).

## Confirmation

`tests/test_alignment.py` (walkthroughs (a)–(i), (m)–(p); the tie-break order; pair classes with a `WordInfo` table; the page pass runs exactly when rule 2 says; acceptance 4(a)–(c)), `tests/test_cycle_candidates.py` (walkthroughs (j)–(l); `close_cycle` reasons map to the stated `unsure` reasons; a correction removes a candidate from the open set; one page read per `(page, revision)` per cycle), `tests/test_practice.py` (retry classes; `unclear` vs `disagreed`; fuzzy never passes; text mode never `confirmed`), `tests/test_norm.py` (number readings and collapsing; token boundaries equal to v1's on the fixture pages), `tests/test_difficulties.py` (`not_practised` and `skipped` contribute 0; `teach_incorrect` counts, `teach_ok` does not), `tests/test_alignment_perf.py` (hardware-marked, the 100 ms bound), and `scripts/evals/reading_eval.py` on the labelled set before `practise_errors` is enabled by default.

## Reviews

v1: codex design reviews 1–5 (2026-10-19) under `../plans/active/reviews/`. v2: pending (codex and `code-plan-review`, AGENTS.md → Verification); no v2 code before it is accepted.
