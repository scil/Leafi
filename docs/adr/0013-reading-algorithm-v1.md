---
status: accepted
accepted: 2026-10-22 (owner; v2 rev 3 with the author's calls of the round-1 comparison and the plan's Decision log as they stand)
v1: accepted 2026-10-19, implemented in `leafi/study/alignment.py` (the code follows v1 until plan M4 implements v2)
date: 2026-10-19
revised: 2026-10-22 (v2 rev 3: round-2 increment review; v2 rev 2: round-1 reviews, see Reviews; v2 rev 1: ADR-0017 §8.1–8.6 as pseudocode and the prior-art changes to alignment; v1 revised 2026-10-19 after codex round 4)
supersedes: 0009, 0012
---

# Reading algorithm: one owner for alignment, commitment, completion, practice and reconciliation

The file keeps its v1 name so that links stay valid; this text is v2. v1 is in git history (`git show 8a14e74:docs/adr/0013-reading-algorithm-v1.md`).

## Context

ADR-0007 → 0009 → 0012 refined the reading rules as prose; each codex round found interactions the prose left open, so v1 stated the algorithm once, with exact costs and state. Every other document points here and restates nothing.

v2 has two inputs. **ADR-0017 §8** moves practice out of reading: no correction happens while the learner reads, errors are practised afterwards by the `practise_errors` activity, and candidates live in a cycle across sentences and pages. **The domain prior art** ([`../research/2026-10-22-domain-prior-art.md`](../research/2026-10-22-domain-prior-art.md) §1, top changes 1–3) found that v1 credits real-word misreadings as correct (house/horse, though/through at `sim ≥ 0.80`), cannot reach a sentence after a lost start (the bounded window and the `run ≥ 2` acceptance forced "She smiled at the clever fox" onto sentence 1 in session 11, research 2026-10-21 §3.3), treats rereads as insertions, and practises function words, which Project LISTEN stopped doing to halve its false alarms. Provenance of every v2 mechanism: §Provenance.

## Definitions

- `tokens[i]`, `i ∈ [0, n)`: expected tokens of the page read's revision, each with `sentence_id`, `char_span` (half-open code points), `function_word` (bool), `status ∈ {unattempted, provisional, committed, candidate, settled, unread}`, and for a candidate or settled token `miscue_id` (its miscue row, carried through corrections) and `created_by` (the utterance number that created it). `settled` = a former candidate whose miscue row reached a final status.
- `ReadingState = (page_read_id, revision_id, tokens, pcur, ccur, completed: set[sentence_id], turn_id, unaligned_run, unaligned_words, prompted)`. `pcur` is the frontier, moved only by rule 8 and the rules that name it; `ccur ≤ pcur` is the commit cursor, moved by rule 9.
- **Page read.** One pass over a page, persisted after every utterance. Within one cycle (ADR-0017 §1) a page has at most one page read; a correction moves it to the new revision in place (§Correction interaction). How a page read starts: §Opening a page read.
- Utterance words `w[0..m)` after `norm()`, each with a confidence (`None` = typed; **a typed word counts as confident everywhere in this ADR**), optional `audio_ref`.
- `sim(a, b)` = `rapidfuzz.fuzz.ratio(a, b) / 100`.
- **`WordInfo`** is a port the session passes into `align`, so `align` stays pure: `is_word(w)` (the word is in the household lexicon or in the bundled frequency word list ADR-0017 §6.2 ranks with), `phones(w)` (a set of espeak-ng pronunciations without stress marks, plus second pronunciations from a small homograph table — read, lead, live, wind, tear, wound, bow, close, minute; empty when no phonemizer is configured, and then the phone test is skipped), `lemmas(w)` (the set of lemmas of a word; the library or table is chosen in plan M0 with research). Answers are cached per word and **computed before `align` is called** (page tokens when the revision loads, heard words when the utterance arrives). `page_reads.alignment_versions` records the versions of the word list, `FUNCTION_WORDS`, the phonemizer and the lemma source. Tests use a table.
- **`FUNCTION_WORDS`**: a fixed, versioned list in `study/function_words.py` (articles, auxiliaries, pronouns, prepositions, conjunctions; Project LISTEN's 36 function words plus their contractions). It is not `study/stopwords.py`, which serves CHECK. A content word is any other word.

### `norm()` v2 (`TOKENIZER_VERSION = 2`)

v1's rules (lowercase, strip punctuation, contractions table) plus number readings: an expected numeral token gets every reading `num2words` gives it — cardinal; ordinal for `1st`, `2nd`, …; a year reading for four digits 1100–2099 — each in **canonical form**: lowercase, without "and", commas, spaces or hyphens (`105` → `onehundredfive`, `1990` → `nineteenninety`). Heard words are **not** collapsed; the DP's `number join` (rule 3) matches 2–4 consecutive heard number words to one numeral. **Token boundaries do not change from v1**, so stored reading states stay valid; only `norm` values change.

### Pair classes

`pair(heard, tok)`, first match wins:

| Class | Test | Alignment cost (tenths) | Counts as matched |
|---|---|---|---|
| `exact` | `norm(heard) == tok.norm`, or equal to one of a numeral's readings | 0 | yes |
| `phones` | `phones(heard) ∩ phones(tok) ≠ ∅` (homophones: threw/through; homographs: read/red) | 0 | yes |
| `inflection` | heard ≠ expected, both `is_word`, and `lemmas(heard) ∩ lemmas(tok) ≠ ∅` (walked/walk, smiles/smiled; car/card are different lemmas) | 10 | no |
| `fuzzy` | `sim ≥ 0.80` and `not is_word(heard)` (a garbled or partial word; typed typos) | 3 | yes |
| `substitute` | anything else, **including a real word at `sim ≥ 0.80`** (house/horse, there/three, though/through) | 10 | no |

Costs are flat by class; a substitution cost graded by phone distance (prior-art §1 #3(b)) is not used in v2, because flat costs keep the cost ordering exact and hand-checkable; it is revisited with the labelled set (§False-alarm budget).

## `align(state, utterance, info) -> (state', observations, events)` — pure, deterministic

```
1. FAST PASS over W_f = tokens[lo:hi]:
     lo = max(0, ccur − 6, sentence_start(ccur)); hi = min(n, pcur + ceil(1.5·m) + 8)       # v1's window
     path_f = best_path(W_f, entry = fast_entry)
2. PAGE PASS, only when m ≥ 2 and (path_f is not accepted (rule 4) or cost(path_f) > 5·m):
     path_p = best_path(tokens[0:n], entry = page_entry)
     use path_p when it is accepted and either path_f is not accepted or cost(path_p) + 10 < cost(path_f); else path_f
3. best_path(window, entry): the minimum-cost alignment of ALL heard words w[0..m) that aligns ≥ 1 token
   (an all-insertion path is not a path; rule 4 decides whether the best one is accepted). Costs in tenths:
     align word j at token i      pair cost (§Pair classes)
     number join                  heard words j..j+k−1 (2 ≤ k ≤ 4) at one numeral token i whose readings contain their
                                  concatenated canonical form: 0, counts as matched. The words must be number words
                                  (num2words' English vocabulary: zero … nineteen, the tens, hundred, thousand, million,
                                  their ordinals) or "and" between two of them; "and" is dropped by the canonical form
     delete tokens (affine)       a run of L ≥ 1 expected tokens skipped between two aligned tokens: 8 + 3·(L − 1)
     insert word                  12   (exceeds substitute, so a heard word prefers an expected token)
     back jump (reread)           directly after aligning token a, align the next word at token k:
                                  fast pass  max(lo, first_index(previous sentence of a, or a's own sentence when a
                                             is in the first)) ≤ k ≤ a
                                  page pass  sentence_start(a) ≤ k ≤ a
                                  cost 4 + 1·(a − k)
     free gaps                    expected tokens before the first aligned token and after the last aligned token
     entry (first aligned f)      fast_entry(f) = 1·|f − pcur| + 15 per sentence s with sentence(pcur) ≤ s < sentence(f)
                                  that is not completed and has no attempted token (skipping a whole unread sentence);
                                  page_entry(f) = 1·|f − pcur| when |f − pcur| ≤ 2, else 15 (one flat jump anywhere)
     boundary                     5 for every visit with fewer than min(2, len(s)) aligned tokens; a visit is a maximal
                                  stretch of the path's aligned tokens in one sentence s (a back jump into another
                                  sentence starts a new visit; deletions alone open none); the first and last visits count
   cost(path) is the sum; internal(path) = cost(path) − the entry cost − the boundary charges.
   Ties: lowest cost; then first aligned index nearest pcur; then fewest insertions; then fewest back jumps; then the
   lexicographically earliest path over (expected index, operation: match, phones, fuzzy, join, substitute, delete,
   insert, jump). The result is unique. Some walkthroughs are decided by this last key (walkthrough (s)); changing the
   operation order is a design change.
4. ACCEPT a path iff it has an anchor and, when m ≥ 3, internal(path) ≤ 7·m (the ceiling, untuned; rules (c) and (d)
   bound m ≤ 2 themselves). A "run" is a sequence of matched tokens in
   increasing index order with nothing between them in the path but deleted function-word tokens.
     (a) a run of ≥ 2 matched tokens containing a content word (fast pass); in the page pass a run of ≥ 3 matched
         tokens containing a content word, or a run of 2 matched content words; or
     (b) ≥ 2 matched tokens, one of them a content word, and matched ≥ ceil(m / 2)   (fast pass only); or
     (c) m ≤ 2 and exactly one matched token, index ∈ [pcur − 2, pcur + 2], that is a content word, or a function word
         from a typed utterance   (fast pass only); or
     (d) m = 1 and the path is one substitution at index pcur on a content word, with `is_word(heard)`, heard not in
         `INTERJECTIONS` (yeah, yes, no, okay, ok, mum, mom, mummy, dad, daddy, wait, look, hey, oh, um, uh, hmm, and
         the household's names; a versioned list in `study/function_words.py`), confidence ≥ ANCHOR_CONF (0.8, untuned),
         and sim(heard, tok) ≥ 0.5 or the same first letter (a lone plausible misreading)   (fast pass only)
   Not accepted by either pass → events = [unaligned(m)]; observations = [unaligned(m), no tokens];
   state'.unaligned_run += 1; state'.unaligned_words += m; return.
5. Observations from the path, each with `pair_class` (null for deletions and insertions) and `function_word`:
     matched (exact | phones | fuzzy | join, with sim; `repeat` when the token was already matched earlier in this path),
     substituted(heard), deleted, inserted(heard, anchor = next expected index).
     A run of ≥ 3 consecutive inserted words → one `unaligned(count)` observation instead of insertions.
     `self_correction` marks (detector original, untuned): an inserted word directly before a match at token k with
     sim(heard, tok_k) ≥ 0.5 or the same first letter; a substitution at token k later matched in the same path.
     An internal deletion run of L ≥ 4: its `unattempted|provisional` tokens become `unread` (other statuses unchanged),
     events += line_skipped(L), no candidate.
6. Entry beyond the frontier (first aligned index f > pcur, either pass): tokens in [pcur, f) of sentence(f) still
   `unattempted` → `unread`. (Earlier sentences are completed by rule 10's events.)
7. Status updates in path order (C(s) = "sentence s is completed"):
     matched tok:      unattempted|provisional|unread → committed if C(sentence(tok)), else provisional;
                       committed|settled → unchanged;
                       candidate with origin supplied → unchanged (alignment never withdraws a told word);
                       other candidate → settled, its miscue → withdrawn(self_corrected if tok.created_by is the
                       utterance immediately before this one, else reread)
     substituted or deleted (≤ 3), tok unattempted|provisional|unread → OBSERVED (no miscue: the token becomes
                       committed if C(sentence(tok)), else provisional) when any of:
                         tok.function_word; class inflection with reading.inflections = observe (default);
                         a substitution whose heard confidence < LOW_CONF (0.5, untuned); a self_correction mark
                       otherwise → candidate, new miscue(status = candidate, origin = substitution | deletion,
                         heard = w or null, cycle_id = s.cycle), tok.miscue_id, tok.created_by = this utterance
     substituted or deleted, tok candidate|committed|settled → unchanged (one candidate per token; a settled token is
                       never re-opened by alignment)
8. pcur = max(pcur, last_aligned_index + 1); unaligned_run = 0; unaligned_words = 0; prompted = false
9. Commit scan: while ccur < pcur and tokens[ccur].status ∈ {provisional, committed, candidate, settled}: ccur += 1
10. events += sentence_reached(s) for every sentence s ∉ completed with last_index(s) < pcur; return
```

**Performance.** `align` itself (with `WordInfo` answers precomputed) must finish in ≤ 100 ms p95 on this PC for a 400-token page and 25 heard words, page pass included. The page pass has about 400 × 26 × 3 × 2 states and a back-jump fan-out of up to a sentence: about a million transitions, seconds in v1's pure-Python style, so the implementation is expected to vectorise (affine deletion as a running minimum, back jumps as per-sentence prefix minima) with the tie-break keys packed into one integer and a fixed transition order; it must return the same path as a brute-force reference on small inputs (`tests/test_alignment_oracle.py`). A timed prototype is a gate before this ADR is accepted (plan M0).

## Supplying a word (ADR-0017 §6.1 hint)

```
supply(state, i):            # Leafi said the word at token i = pcur after the learner accepted a hint
  tok = tokens[i]
  if tok.status == candidate: its miscue.origin = supplied      # one miscue per token: the existing row is kept
  elif tok.status ∈ {unattempted, provisional, unread}:          # a told word is an error, also for a function word
    tok.status = candidate
    new miscue(status = candidate, origin = supplied, heard = null, observation_id = null, cycle_id = s.cycle);
    tok.miscue_id, tok.created_by
  else: nothing (committed or settled: the hint was not needed for the record)
  pcur = max(pcur, i + 1); rule 9; rule 10
```

A supplied candidate is settled only by Practice or by `close_cycle`; rule 7 never withdraws it. A supplied miscue has no observation.

## Unaligned speech and the first-words prompt

An `unaligned` utterance changes no token and creates nothing; the summary reports its words as "not tracked", never as a verdict on the learner. When `unaligned_run ≥ 3` and `unaligned_words ≥ 6` and not `prompted`, Leafi says "Where are you reading? Read me the first few words of your line." (recovery dialogue, always allowed, ADR-0017 §6.1) and sets `prompted`. Every following utterance is aligned by the same rules, page pass included; the v1 two-strike Reposition state is removed.

## Sentence completion

Sentence `s` completes on the first of: (i) `sentence_reached(s)`; (ii) the Listener yields nothing for `sentence_pause_s = 1.2` (voice) or the typed line ends with `. ? !` or is empty (text), while `pcur` ∈ the last two token indexes of `s` or beyond **and no content-word token of `s` is `unattempted`** (a slow reader's pause before the next word does not end the sentence); (iii) `skip`, `stop`, a terminal status (ADR-0017 §2), or the end of the `read_listen` range while `s` is the current sentence. **A page turn, `next page` or any other non-terminal end of `read_listen` completes nothing**: the current sentence stays open in its page read and continues when the page read is resumed.

On completion: `provisional` tokens of `s` → `committed`; `unattempted` tokens of `s` → `unread`; `candidate` tokens stay `candidate`; `ccur = max(ccur, last_index(s) + 1)`; `pcur = max(pcur, ccur)`; `completed += {s}`; `turn_id += 1`. Several `sentence_reached` events in one utterance are processed in order, each once. Nothing is practised at a sentence end, and nothing is said there except what ADR-0017 §6.1's `reading.interrupt` mode allows.

**Range completion.** A `read_listen` activity reads a range of the page read (ADR-0017 §3.1); alignment always runs on the whole page read. The activity ends `completed` when every sentence of its range is in `completed`. What follows is chosen at the next boundary (ADR-0017 §2). At wrap, `unattempted` tokens of open sentences are reported as `not_reached`, `unread` tokens as `unread`; neither is practised.

## Opening a page read

```
open_page_read(s, page, range):                                  # called by read_listen and its continuations
  r = current revision of page
  if s.cycle has a page read of page: return it                  # same cycle: resume as it is (already at r)
  pr = new page read (cycle = s.cycle, revision = r, attempt + 1, all tokens unattempted, completed = {})
  if range is {from, to} or page is familiar: pcur = ccur = from (0 for familiar)
  else (rest):
    prev = this learner's latest page read of page, any session, any revision
    if prev: c = prev.ccur mapped through the edit maps from prev's revision to r (ADR-0010 §6; a position inside
             a deleted span maps to the first surviving token after it); c = n stays n (the page was finished, the
             range is empty); otherwise c moves down to the start of its sentence;
             tokens before c → committed, except tokens whose span a correction since prev's revision touched →
             unread; completed = sentences entirely before c; pcur = ccur = c
  return pr
```

"Continue from page N?" after an interrupted session (§Interrupted session) is this rule with range `rest`.

## Cycles and candidates (ADR-0017 §8.1)

```
open_candidates(cycle) = miscues with cycle_id = cycle.id and status = candidate
close_cycle(cycle, reason):                                      # one transaction
  for m in open_candidates(cycle):
    if m has practices rows: m gets Practice step 4's final status from all its rows (a recorded fail → disagreed)
    else: m.status = unsure; m.unsure_reason = {stop: skipped, interrupted: interrupted}.get(reason, not_practised)
    the token whose miscue_id = m.id in m's page read state → settled (persisted)
  cycle.status = closed; cycle.closed_reason = reason
reasons: next_reading (another boundary-chosen read_listen or read_aloud starts), wrap, stop, interrupted (startup
  recovery), and the other terminal statuses of ADR-0017 §2 (→ not_practised)
```

A token is always found by its `miscue_id`, never by `miscues.expected_token_index`, which keeps the index at the revision where the miscue was created. A later match in any `read_listen` of the cycle withdraws a candidate by rule 7. `/back` reopening its sentence leaves it `candidate`. A correction invalidating it removes it from the open set.

## Page turns and continuations (ADR-0017 §8.2)

A page turn or `next page` during `read_listen` ends the activity with `page_turned`, completes nothing and settles nothing. When the learner keeps reading, ADR-0017 §2 starts a continuation `read_listen` in the same cycle; `open_page_read` returns the cycle's page read of the new page if there is one, else opens one. This repeats on every turn. A page turn during `practise_errors` ends it with `page_turned`; the candidate being practised and the unpractised ones stay `candidate`, owned by the cycle.

## Practice (run by `practise_errors`, ADR-0017 §3.1)

Per selected candidate, in the order ADR-0017 gives (Difficulty weight, then position), on its own page read (located by `miscue_id`, shown with `pages.current_text()`):

1. Leafi shows the candidate's sentence on Faces and models the word (TTS).
2. The learner retries. **The budget is per miscue: at most 2 attempts in total**, also when a page turn interrupted an earlier `practise_errors`. With `ASR_HOTWORDS` on, the retry stream carries the target word as its only hotword; reading streams never carry page hotwords (a page-biased ASR would hide miscues).
3. Each attempt is `pass` when some heard word is the target by class `exact` or `phones`, or a run of heard number words is it by `number join`, with confidence ≥ `RETRY_MIN_CONF` (0.5, untuned); `fail` when every heard word has confidence ≥ `RETRY_MIN_CONF` and none passes; `idle` when no retry arrives within `PRACTICE_RETRY_S` (10 s voice; text waits); else `unclear`. Fuzzy and inflection classes never pass.
4. The sequence ends on a `pass`, on `skip`, on `idle`, or after the second attempt; an attempt cut by a page turn or a terminal writes no row and does not use the budget, and a later `practise_errors` continues with the next attempt number. The final status reads every `practices` row of the miscue, from any activity: `pass` → `withdrawn(practice)`; `skip` → `unsure(skipped)`; else `unsure(disagreed)` if any attempt was `fail`, else `unsure(idle)` if the last was `idle`, else `unsure(unclear)`. After `idle`, practice continues with the next candidate.
5. Each attempt writes a `practices` row (`attempt` 1–2 per miscue, `outcome ∈ {matched, disagreed, unclear, idle, skipped}`) with `evidence = acoustic` only when `PRON_AUTO_JUDGE` is on and the scorer ran (then the scorer may set `confirmed` instead of `unsure`), else `evidence = none`. **Text mode uses exactly these rules with `evidence = none`; `confirmed` is impossible there.**
6. After its sequence the token becomes `settled` in its page read state.

Alignment creates no candidate on a function word; a supplied function word is a candidate and is practised.

## `/back N`

Spoken "go back", typed `/back N`, N ≥ 1, default 1, **within the current page read only**: let `cur` = the sentence containing `pcur − 1` when `pcur` is at a sentence start or at `n` (and `pcur > 0`), else the sentence containing `pcur`; target = `cur − (N − 1)` (clamped to the first sentence). For every sentence from target to `cur` inclusive: remove from `completed`; tokens `committed|provisional|unread` → `unattempted`; `candidate` tokens stay; `settled` tokens stay. `pcur = ccur = first_index(target)`; `turn_id += 1`. `/back` never crosses a page: on a page with nothing read it changes nothing but `turn_id`, and Leafi says "To read the last page again, turn back to it." (recovery dialogue); turning back resumes that page's page read in the same cycle. Allowed in `read_listen`; in `practise_errors` it is a spoken no-op ("Let's finish these words first, or say skip.").

## Control precedence (highest first)

| Control | In `read_listen` | In `practise_errors` |
|---|---|---|
| `stop` | complete the current sentence by (iii); the activity ends `stopped`; `finalize` closes the cycle with reason `stop` | current candidate → `unsure(skipped)`; the activity ends `stopped`; `finalize` closes the cycle with reason `stop` |
| `next page` / page turn | ends `page_turned`; nothing completes | ends `page_turned`; candidates stay `candidate` |
| `/back N` | as above | spoken no-op |
| `skip` | complete the current sentence by (iii); `pcur = ccur = first_index(next sentence)`; the activity continues, or ends `completed` when its range is complete | current candidate → `unsure(skipped)`; the next candidate, or the activity ends `completed` |

A control that does not apply → spoken no-op. Other activities' controls are ADR-0017 §3.1's.

## Interrupted session (ADR-0017 §8.5)

On startup a stale session's `running` activity becomes `interrupted` and its open cycle closes with reason `interrupted`, so its candidates become `unsure(interrupted)` (tokens `settled`); guest end states follow ADR-0018 §1. Each page read keeps its `ReadingState`. A new session of the same learner on the same book offers "continue from page N?" from that learner's latest page read of that book; yes → `open_page_read` with range `rest`.

## Async guard

The ADR-0017 epoch replaces v1's `(session_id, revision_id, turn_id)`; `turn_id` increments on sentence completion, `skip`, `/back`, `stop`, a page turn, and every event ADR-0017 §1 lists.

**Input routing by activity**: `read_listen` → `align` (and `supply` after an accepted hint); `practise_errors` → the retry test; `quiz` → CHECK outcomes; `review_anki` → the ease grammar; controls everywhere. Cancellation during playback comes from the console or a Face (`/stop`, a key); spoken `stop` works while listening.

## Correction interaction (coordinates: ADR-0010 §6)

**Who applies it.** While a session holds the speech lease, only the session process applies corrections; a correction from another process (a parent tool) is refused with "a study session is running". A correction creates revision r+1 with an edit map.

**Page reads.** Every page read of the corrected page whose cycle is open is re-tokenised on r+1 **in place** (the same row; its revision becomes r+1): each token carries its status, `miscue_id` and `created_by` through the edit map; tokens whose mapped char span overlaps the edited span lose `miscue_id` and become `unattempted` when they lie at or after the mapped `ccur`, `unread` when they lie before it (the learner read the old text there; a correction behind the frontier does not send the learner back); `pcur`, `ccur` are mapped through the edit map and clamped to the first `unattempted` such token when they were past it; sentences containing an `unattempted` such token leave `completed`. Page reads of closed cycles keep their revision (they are history; `open_page_read` maps cursors through the edit maps).

**Miscues.** Miscues of **any** revision of this page with status ∈ {candidate, unsure, confirmed} whose `expected_char_span` maps (through the chain of edit maps up to r) into a span overlapping the corrected span → `invalidated(page_text_corrected)`; `withdrawn` and already-`invalidated` rows are untouched. An invalidated candidate leaves its cycle's open set. Difficulties are recomputed inside the same transaction.

## Difficulties (single formula; data-model.md repeats only column names)

For a word (miscues): `weight = Σ_s v(s) × 0.5^(days_since(s)/30)` over sessions `s`, with `v(s) = 1.0` if the word had a `confirmed` miscue in `s`, else `0.3` if it had an `unsure` miscue in `s` with reason `disagreed` or `idle`, else 0. `unsure` with reason `not_practised`, `skipped`, `interrupted` or `unclear` contributes 0 and does not count toward the existence rule: none of them is evidence about the learner (ADR-0017 §8.6 named the first two; `interrupted` and `unclear` follow for the same reason). A row exists only if `confirmed` evidence exists in ≥ 1 session (`kind = confirmed`) or, with no confirmed evidence, counting `unsure` evidence in ≥ 3 distinct sessions (`kind = watch`); once a row exists every session's `v(s)` contributes. Function words have miscues only when supplied.

For a knowledge item (encounters): `weight = Σ_s e(s) × 0.5^(days_since(s)/30)` with `e(s) = 1.0` if session `s` has an encounter with `trigger ∈ {check(incorrect), explain, teach_incorrect}` for the item; `teach_ok` is ignored; a row exists only with counting encounters in ≥ 2 distinct sessions (`kind = knowledge`).

Watch items order Practice and never produce a "wrong" line or a card by themselves. The values 30, 0.3 and 3 are *untuned*: a priority score, not a recall model (Anki owns memory, ADR-0004).

## CHECK outcomes (exhaustive; run by `quiz`)

ADR-0017 §3.4 decides first whether an answer is counted (a spoken answer counts only when confidently recognised; an uncounted one is `unavailable` and writes no encounter) and owns the `judge` scoring of open answers; for a counted answer to a keyword question:

1. `unavailable` if the Brain did not return questions, or the learner skips / says "I don't know" / gives no answer within `CHECK_ANSWER_S` (20 s voice, no limit text).
2. else `correct` if, after `norm`, all keywords of at least one acceptable answer are present.
3. else `incorrect` if the answer contains ≥ 2 content words (words not in `study/stopwords.py`).
4. else `unavailable` (too little to judge).

Leafi then gives the answer in the Coach voice regardless; only `incorrect` writes an `encounters` row (`trigger = check`).

## Running-record conventions and reported counts

Self-correction and repetition are not errors; a word Leafi supplied is. Per page read the summary reports, from the observations: words matched, substitutions and deletions by `pair_class`, `function_word_misses` (observed, not candidates), inflections observed, candidates by origin, `self_corrections` (rule 5 marks plus `withdrawn(self_corrected)`), `repetitions` (`repeat` matches), words not tracked (`unaligned`), `tokens_unread`, `not_reached`. These map to running-record categories in the parent's export; no number is shown to the child.

## False-alarm budget

A **false alarm** is a candidate (origin `substitution` or `deletion`) on a token the learner read correctly, by a human label. Budget: ≤ 5 % of correctly read content-word tokens per page read on the labelled recordings set (*untuned*; Project LISTEN reached < 1 % at 23 % detection). The miss rate is reported, with no budget. The set (`data/evals/reading/`, local, never committed) holds the owner's readings with deliberate errors and, later, the learner's labelled readings; `scripts/evals/reading_eval.py` replays it through `align` and prints both rates and the distributions that bracket each untuned threshold (word confidences of right and wrong words for `ANCHOR_CONF`, `LOW_CONF`, `RETRY_MIN_CONF`; inter-word pauses for `sentence_pause_s`; internal cost per heard word of right and wrong paths for the 5·m trigger and the 7·m ceiling). A budget breach is a tech-debt row; the first levers are the page-pass trigger, the ceiling, `ANCHOR_CONF`, `LOW_CONF` and `reading.inflections`. Until the budget is met, practice lines frame every candidate as "let's practise", never as wrong (product non-goal).

## Walkthroughs (expected results; `tests/test_alignment.py` and `tests/test_cycle_candidates.py` encode them)

Status codes: U unattempted, P provisional, C committed, M candidate, S settled, R unread. Heard words are confident unless stated. Every stated "best path" is checked by the brute-force oracle.

- (a) "The little brown dog walked slowly." **typed** one word per utterance: each singleton costs 0 + boundary 5 = 5 and is accepted by 4(c) ("The" because typed); after "slowly" `sentence_reached`; completion commits all six; no miscues. **Spoken**, "The" alone is a lone function word → `unaligned(1)`; "little" then enters at 1 (entry 1, 4(c)) and "The" becomes R by rule 6.
- (b) "The dog ran." heard "The dog red.": `red`/`ran` is `substitute` (10 < insert 12); anchor 4(a) "The dog"; internal 10 ≤ 21; candidate at `ran` (origin substitution, owned by the cycle); `sentence_reached` completes the sentence (`C C M`, cursors (3, 3)); nothing is practised or said; the range is complete → `read_listen` ends `completed`. At the next boundary `practise_errors` runs it: no retry within 10 s → `idle` → `unsure(idle)`, token `S`.
- (c) "The little cap" / "cat sat on the mat.": utterance 1 → candidate at `cat` (`cap` is `substitute`, sim 0.67); utterance 2 enters at `cat` (entry 1 beats inserting "cat", 12) and matches it → `withdrawn(self_corrected)`, token `S`; completion → `C C S C C C C`.
- (d) "I can see it. I can see it." read sentence by sentence: the second identical utterance aligns in the window starting at sentence 2 and completes it; `/back 1` reopens sentence 2 only (`C C C C U U U U`, cursors (4, 4), `completed = {1}`).
- (e) "The dog ran away." against "The dog ran. The cat sat.": `away` → insert (12) rather than substitute `The` of sentence 2 (10 + boundary 5, a visit with one aligned token); no candidate.
- (f) A skipped line of 6 tokens inside an utterance ("A B C D K L M" against "A B C D E F G H I J K L M", content words): delete run 8 + 3·5 = 23 against substituting K, L, M onto E, F, G and leaving the rest as a free gap (30) or jumping ahead and substituting four words (6 + 40); internal 23 ≤ 49; `line_skipped(6)`, E–J `R`, no candidate. With only two words after the skip ("A B C D K L"), substituting them onto E, F (20) beats the deletion run (23): two false candidates, a named limit (Consequences).
- (g) **Lost start (session 11).** Page: s1 "At the edge of the wood lived a clever old fox." (tokens 0–10), s2 "Every morning he walked down to the river to drink." (11–20), s3 "She smiled at the clever fox." (21–26); `pcur = ccur = 0`; heard "she smiled at the clever fox". The fast window `[0, 17)` cannot reach s3; its minimum is 44 (insert "she smiled": 24; `at the` exact at 0–1; clever/edge and fox/of substituted: 20; entry 0), whose only matches are function words (no anchor) and internal 44 > 42 → not accepted (the oracle test holds the exact figure; this walkthrough asserts the outcome). The page pass (m = 6) enters at 21 (15) with six exact matches: cost 15, internal 0, a run of 6 → used. s1 and s2 complete by (i) with every token `R`; s3 `C`; **no candidate** (v1: four false candidates in s1).
- (h) **Real-word misreading.** "The horse ran." heard "the house ran": `house`/`horse` sim 0.80 but `is_word(house)` → `substitute`; matched `the`, `ran` (2 of 3, `ran` content) → 4(b); candidate at `horse`. At confidence 0.4 the substitution is observed only (`LOW_CONF`), token `P`. Typed "the hosre ran" → `hosre` is not a word → `fuzzy`, matched, no candidate.
- (i) **Rereads and self-corrections inside an utterance.** "The dog ran fast." heard "the dog the dog ran fast": back jump from `dog` (a = 1) to `the` (k = 0) costs 4 + 1 = 5 against inserting "the dog" (24); the second `the` and `dog` are `repeat` matches; `repetitions = 2`; no candidate. Heard "the dog red the dog ran fast": `red` substituted at `ran` (10), back jump 2 → 0 (6), `the dog ran fast` matched: 16 against inserting `red` and jumping back from `dog` (12 + 5 = 17); `ran` was substituted and then matched in the same path → `self_correction`, no miscue. Heard "the little cap cat sat" for "The little cat sat": inserting `cap` (12) beats substitute + back jump (10 + 4); `cap` is marked `self_correction` (sim 0.67); no candidate.
- (j) **A → B → C in one cycle.** `read_listen` on A opens cycle k; A s1 gets a candidate at A:3; the learner turns the page inside A s2 → the activity ends `page_turned`; s2 stays open (its read tokens `P`, the rest `U`); nothing settles. Continuation on B (same cycle, a new page read); a candidate at B:5; turn → continuation on C; C completes → `completed`. `open_candidates(k) = {A:3, B:5}`. The next boundary runs `practise_errors([A:3, B:5])`, each on its own page read; then a boundary-chosen `read_listen(A, rest)` starts → `close_cycle(k, next_reading)` finds nothing open, and `open_page_read` starts A's new page read at the start of s2 (A's old `ccur`, inside s2, clamped to a sentence start), s1 `C`. Had practice been refused, both would become `unsure(not_practised)` and contribute 0.
- (k) **`/back` across a page turn.** After (j)'s turn to B, before anything is read on B, "go back": B's page read has `pcur = 0`, so nothing changes but `turn_id`, and Leafi says to turn back. The learner turns back to A → `page_turned` → continuation on A resumes A's page read (`ccur` inside s2, A:3 still `M`). Rereading A s1 ("a big cat sat on the mat", A:3 = `sat`, a content word): the fast window starts at s2, the fast pass is not accepted, the page pass (m = 7) anchors on s1 (entry 15), its tokens are `C` and stay so, and the match at A:3 → `withdrawn(reread)`.
- (l) **`stop` mid-practice.** `practise_errors([A:3, B:5, C:2])` is on B:5 when the learner says stop: A:3 is already settled; B:5 → `unsure(skipped)`; the activity ends `stopped`; `finalize` closes the cycle with reason `stop` → C:2 → `unsure(skipped)`; all three tokens `S` in their page reads.
- (m) **Unaligned chatter.** During `read_listen`, "can I have a snack after this" with no page word: no anchor in either pass → `unaligned(7)`, no state change. Three such utterances (≥ 6 words) → the first-words prompt, once.
- (n) **Lone function word.** At `pcur` on "the" of "… to the park", spoken "the" at any confidence → `unaligned(1)` (ADR-0017 §8: never anchoring alone); typed "the" → accepted by 4(c).
- (o) **Numbers.** "He was 21." heard "he was twenty one": `number join` of "twenty one" at the numeral (canonical `twentyone`) → matched, cost 0. Page "twenty one cats" (two tokens) heard "twenty one cats" → three exact matches (no join: there is no numeral). "in 1990" heard "in nineteen ninety" → join on the year reading. "105" heard "one hundred and five" → join of four words, canonical `onehundredfive`.
- (p) **Inflection.** "She smiled at the fox." heard "she smiles at the fox": `smiles`/`smiled` share the lemma `smile` → `inflection`; with `reading.inflections = observe` the token is `P` and the observation keeps the class; with `practise` it is a candidate. "car" heard for "card": different lemmas → `substitute` → candidate.
- (q) **Chatter with a page word.** Page "Mum went to the shop to buy some milk.", `pcur = 0`, heard "mum can I have a snack after this" (m = 8): the fast path `mum` + 7 substitutions costs 70, internal 70 > 56 → not accepted (4(c) also needs m ≤ 2); the page pass has no run → `unaligned(8)`; no candidate.
- (r) **One-word sentences.** "Run! Run! Run!" heard "run run run": straight path, three visits of one aligned token in sentences of length 1 → no boundary charge, cost 0; the repeat path (two back jumps) costs 8 → straight wins; all three sentences reached.
- (s) **Patterned book.** s1 "I see a red bird." (0–4), s2 "I see a blue cat." (5–9), s3 = s1's text (10–14), `pcur = ccur = 5`, heard "I see a red bird": in s2, two substitutions = 20; entering s3 costs 5 + 15 (s2 is a whole unattempted sentence) = 20, so the first aligned index nearest `pcur` → s2; a third path, "I see a" in s2, deleting "blue cat I see a" (8 + 12) and matching "red bird" in s3, also costs 20 from index 5 and loses only on the operation order (substitute before delete at index 8) → candidates at `blue` and `cat`.
- (t) **Told word.** The learner stops at `dog` in "The little brown dog walked slowly."; "Want a hint?" → yes → Leafi says "dog" → `supply(3)`: `M`, origin supplied, `pcur = 4`. The learner reads "dog walked slowly": `dog` matches but stays `M` (alignment never withdraws a told word); it is practised later.
- (u) **Slow reader with one misreading.** Same sentence, one word per utterance, spoken: "the little" (4(a)), "brown" (4(c)), "dug" (m = 1: substitution at `pcur` = 3 on `dog`, a real word, confident, sim 0.67 → 4(d), cost 15) → candidate at `dog`; a 1.2 s pause after "dug" does not complete the sentence (`walked`, `slowly` are content words still `U`); "walked", "slowly" (4(c)) → completion → `C C C M C C`.
- (v) **Correction before a candidate.** Revision r "The big cat sat on the mat." with a candidate at `mat` (index 6, `miscue_id` 41); the learner corrects "big" away → r+1 "The cat sat on the mat."; the page read is re-tokenised in place, the token carrying `miscue_id` 41 is now index 5; `close_cycle` settles index 5, found by `miscue_id`; the miscue row keeps `expected_token_index` 6 at revision r.
- (w) **Dropped articles after a lost start.** Page-pass case of "The dog saw the cat in the park." heard "dog saw cat in park" (m = 5) with `pcur = 0` and this sentence outside the fast window (a lost start, as in (g)): entry 15, deleted `the` twice (8 + 8); the run "dog saw · cat in · park" spans deleted function words → 4(a) page form; internal 16 ≤ 35 → accepted; both `the` tokens `P` with no miscue; `The₀` before the entry becomes `R` by rule 6.

## Provenance

| Mechanism | Verdict | Source |
|---|---|---|
| token statuses, `ReadingState`, commit scan | original (tutoring state) | prior-art §1 #1, #10 (Project LISTEN "chase the kid" to track, "blame the kid" to credit) |
| global DP with substitute < insert, boundary penalty per visit | adapted | Needleman–Wunsch via ADR-0007; values original, *untuned* |
| fast window + page pass with a flat entry jump and a replacement margin | adapted | Project LISTEN MultiMatch jump model (RA1); prior-art §1 #2, #12; research 2026-10-21 D5 |
| sentence-skip entry penalty | original | review round 1 (patterned books, the main early-reader genre) |
| back jumps (rereads are reading) | adapted | RA1 (regressions are reading, jump penalty on non-sequential transitions) |
| affine deletions | adopted | affine gap costs (RA17); replaces v1's cost-ordering surprise of 2026-10-20 |
| real-word pairs are substitutions; phone-set equality, homograph table | adapted | RA1 (phonemic mismatch distance), RA14 (graphic miscues), RA23 (computed pairs); homograph table original |
| inflection by shared lemma, observe by default | adapted | RA1 and RA3 (dropped endings are the most frequent decoding error; dialect); lemma source chosen in plan M0 |
| function words never practised from alignment, never a lone spoken anchor | adopted | RA3 (LISTEN halved false alarms by ignoring 36 function words); RA2 |
| acceptance with a content word, internal-cost ceiling, `unaligned` | adapted | RA2 (17.6 % of child speech off-task; sentence words seldom occur two in sequence); ceiling original, *untuned* |
| lone plausible misreading 4(d) | original, *untuned* | review round 1 (slow readers); the false-alarm evaluation decides it |
| low-confidence substitution observed only | adopted | research 2026-10-21 §3.3 ("a single low-confidence word is maybe, not a correction trigger") |
| pause completion waits while content words remain | adopted | RA1 (wait if content words remain), prior-art §1 #11 |
| ≥ 3 inserted words → unaligned observation | adapted | research 2026-10-21 §3.3 off-task rule (marked unverified there; probably Chen & Mostow 2011) |
| first-words prompt as the last fallback | original | v1 Reposition, kept as a prompt |
| self-correction count, told word as an error, running-record categories | adopted | RA14 (after Clay 1993); the self-correction detector is original, *untuned* |
| `num2words` readings, canonical form, `number join` | adapted | RA13 (num2words 0.5.14, LGPL-2.1) for readings; the join operation original |
| practice retry: exact, same phones or join, confidence-gated, budget per miscue, hotword only on the retry | adapted | RA5 (Reading Coach word practice), RA9 (sherpa-onnx hotwords in `modified_beam_search`), RA1 ("distracters detract") |
| cycle-owned candidates, settlement at close, continuations, `open_page_read` | original | ADR-0017 §8.1–8.2 (owner requirement 2.2a) |
| corrections re-tokenise open page reads in place, tokens by `miscue_id` | adapted | ADR-0010 §6 edit maps; v1's `Tok.miscue_id` |
| false-alarm budget, threshold brackets | adapted | RA1 (< 1 % false alarms at 23 % detection); code-plan-review K4.1 |
| Difficulties formula | original, *untuned* | RA10 (half-life regression is the recall model Leafi does not build) |
| CHECK keyword partition | original | RA12 (keyword matching is the baseline); `judge` is ADR-0017 §3.4's |

## Consequences

- One function, one state, scenario tests checked by a brute-force oracle; other documents reference sections of this ADR by name.
- Real-word misreadings now become candidates, so more candidates appear than in v1; the false-alarm budget keeps that honest, and function words, inflections (by default) and low-confidence substitutions are observed, never practised.
- A lost start no longer forces speech onto the wrong sentence; the cost is a page pass on poor utterances and a vectorised DP to keep it inside 100 ms.
- Practice leaves reading entirely; reading speaks only as ADR-0017 §6.1 allows.
- Named limits: a spoken lone function word is never tracked (it ends `unread` if nothing later reaches it); a word at the start of an utterance that the reader skipped is a free gap, not a deletion; words read before a jump back of more than one sentence inside one utterance are not tracked; a short, heavily misread utterance (3 substitutions in 4 words) is rejected by the ceiling rather than producing candidates, and so is one whose only matched words are function words ("she want to the ship" for "She went to the shop": no anchor); a line skip followed by one or two words at the end of an utterance makes those words substitutions on the skipped tokens (walkthrough (f)); systematic dropped endings never reach Difficulties in v2 (a future `pattern` knowledge item may consume the inflection observations).
- New data: `WordInfo` (a word list, espeak-ng phones with a homograph table, a lemma source), `num2words`, `FUNCTION_WORDS`, and the columns listed in `data-model.md` → Migration 5.
- Identical consecutive sentences read twice count as progress (accepted; `/back`).

## Confirmation

`tests/test_alignment.py` (walkthroughs (a)–(i), (m)–(s), (u), (w); the tie-break order; pair classes with a `WordInfo` table; the page pass runs exactly when rule 2 says; acceptance 4(a)–(d) and the ceiling), `tests/test_alignment_oracle.py` (the DP equals a brute-force enumeration on random small pages and utterances), `tests/test_cycle_candidates.py` (walkthroughs (j)–(l), (t), (v); `close_cycle` reasons map to the stated `unsure` reasons; a correction removes a candidate from the open set and re-tokenises every open page read of the page; `open_page_read` for each range, for a prior page read at an older revision, for a finished page, and for a cursor inside a deleted span; a hint on a token that is already a candidate keeps one miscue; a correction behind the frontier leaves the cursors where they were; a second candidate after a correction at an index an older-revision candidate held), `tests/test_practice.py` (the per-miscue budget across a page turn, with the cut attempt writing no row; `close_cycle` on a candidate with a recorded `fail` gives `disagreed`; `pass`, `fail`, `unclear`, `idle` and every final status; fuzzy never passes; text mode never `confirmed`), `tests/test_norm.py` (number readings in canonical form; token boundaries equal to v1's on the fixture pages), `tests/test_difficulties.py` (`not_practised`, `skipped`, `interrupted` and `unclear` contribute 0; `teach_incorrect` counts, `teach_ok` does not), `tests/test_corrections.py` (a correction from another process is refused while a session holds the lease), `tests/test_alignment_perf.py` (hardware-marked, the 100 ms bound), and `scripts/evals/reading_eval.py` on the labelled set, with a console button, before `practise_errors` is enabled by default.

## Reviews

v1: codex design reviews 1–5 (2026-10-19) under `../plans/active/reviews/`. v2 round 1 (2026-10-22): `code-plan-review` ([record](../plans/active/reviews/2026-10-22-adr-0013-v2-code-plan-review.md)) and a fresh Claude session standing in for codex, whose quota had run out ([record](../plans/active/reviews/2026-10-22-adr-0013-v2-claude.md)); comparison and resolutions: [round-1 comparison](../plans/active/reviews/2026-10-22-adr-0013-v2-round-1-comparison.md). Round 2 (2026-10-22), the increment on rev 2, by a fresh Claude session for codex at the owner's request ([record](../plans/active/reviews/2026-10-22-adr-0013-v2-round-2-claude.md)): two High (a second hint on a candidate token; the candidate index keyed on a stale index), six Medium, ten Low; all resolved in rev 3 except its M5 (`miscues.observation_id` is already nullable in schema 4). Accepted by the owner on 2026-10-22 without a codex round; plan M0's prototype timing and lemma-source choice may still change the DP or the inflection test, and any such change is a design change reviewed before code.
