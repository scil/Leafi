---
status: accepted
date: 2026-10-19
supersedes: 0009, 0012
---

# Reading algorithm v1: one owner for alignment, commitment, completion, practice and reconciliation

## Context

ADR-0007 → 0009 → 0012 refined the reading rules as prose; each codex round found interactions the prose left open (singleton accumulation vs anchoring, ties on repeated text, completion events, text-mode practice status). The class of defect is "rules in several sentences that must be read together". This ADR replaces them with one algorithm, stated once, with the data it reads and writes. Other documents point here and do not restate the rules.

## Definitions

- `tokens[i]`: expected tokens of the current page revision, each with `sentence_id`, `char_span` (half-open code points) and `status ∈ {unattempted, provisional, committed, candidate, withdrawn, unread}`.
- `ReadingState = (page_read_id, revision_id, tokens, pcur, ccur, turn_id)`: `pcur` provisional cursor (index of the first token not yet provisionally matched or later), `ccur` committed cursor (`ccur ≤ pcur`).
- An utterance has words `w[0..m)`, optional per-word confidence, optional audio_ref.
- `norm()`: lowercase, strip punctuation, number words, contractions table (versioned with `tokenizer_version`).

## Algorithm (pure: `align(state, utterance) -> (state', observations, events)`)

```
1. window = tokens[max(0, ccur-6, sentence_start(ccur)) : min(n, pcur + ceil(1.5*m) + 8)]
2. DP = semi-global alignment of w over window:
     match cost 0 if norm(w)==norm(tok) or fuzzy ≥ 0.85 else substitution 1.0
     deletion (expected unmatched) 0.8, insertion (heard unmatched) 0.6
     + 0.1 × |first matched index − pcur|      # cursor-relative jump penalty
     leading expected tokens before ccur (reread region) are free; leading expected tokens at/after ccur cost deletion
3. accept iff (a) a run of ≥ 2 consecutive matches exists in the path, or
              (b) exactly one match exists and its index ∈ [pcur−2, pcur+2]          # singleton at the cursor accumulates
   else: events += unanchored; state unchanged; observations = []; return                # §Reposition handles two in a row
4. observations = matched / substituted / deleted spans and inserted events from the path (deleted spans only when ≤ 3 tokens AND followed by a match run ≥ 2; otherwise those tokens stay unattempted and the path is re-evaluated without them)
5. apply to tokens:
     matched    → provisional (if it was candidate/withdrawn/committed, keep committed; a candidate becomes withdrawn(reason=self_corrected if same utterance crosses it, else reread))
     substituted→ candidate (new miscue row, status=candidate, heard=w)
     deleted    → candidate (heard=null)
   pcur = max(pcur, last matched index + 1)
6. commit: scan from ccur; while tokens[ccur] ∈ {provisional, committed, withdrawn} or (tokens[ccur]==candidate and a later provisional/committed token exists in the same sentence): ccur += 1
   # a candidate inside a sentence commits once reading moved past it; the miscue row keeps its status
7. events += sentence_reached(s) for every sentence s whose last token index < pcur
8. return state', observations, events
```

Ties: the DP is deterministic; cursor-relative cost makes advancing cheaper than rereading when the text is identical. **Consequence (accepted):** two identical consecutive sentences read twice are recorded as progress. The learner or parent moves back with `/back N` (spoken "go back"); no alternative-path state is kept.

## Session rules that use the algorithm (owner: this ADR; `flows/reading-session.md` draws them)

- **Reposition.** Two consecutive `unanchored` events → align once against the whole page with the same acceptance rule but requiring a run ≥ 3; success repositions `pcur = ccur = first index of that run` (tokens between old `ccur` and the new one → `unread`); failure → state `REPOSITION` (Leafi asks for the first words of the learner's line; the next utterance is aligned against the whole page; no candidates are created while repositioning).
- **Sentence completion** happens on the first of: (i) `sentence_reached(s)`; (ii) the Listener returns no utterance for `sentence_pause_s = 1.2` (voice) or the typed line ends with `. ? !` or is empty (text) while `pcur` is within the last 2 tokens of `s`; (iii) a control `next page`/page turn/`stop` (completes the current sentence as far as read). On completion: tokens of `s` before `pcur` that are still `provisional` become `committed`; tokens of `s` at/after `pcur` become `unread`; `ccur = max(ccur, pcur)`. Then **PRACTICE** runs for the candidates of `s` (max 2 words, Difficulty weight then position) before anything else.
- **Page completion** = the last sentence completed → CHECK (uses completed sentences only). `tokens_unread` is reported in the summary; unread tokens are never practised.
- **Practice** (per candidate, voice or text): Leafi models the word; retry 1; if `norm(retry) == norm(expected)` → miscue `withdrawn(practice)`; else retry 2 with the same test; two disagreements, a skip, an idle timeout or a stop → `unsure`. `evidence = acoustic` only when `PRON_AUTO_JUDGE` is on and the scorer ran, and then the scorer's result may set `confirmed` instead of `unsure`. **Text mode uses exactly these rules with `evidence = none`; `confirmed` is impossible there.** Each attempt writes a `practices` row.
- **Interrupted session.** On startup, stale sessions are closed: their open candidates become `unsure (reason=interrupted)`; the last page read's `ReadingState` is kept. A new session on the same book offers "continue from page N?"; yes → new `page_reads` row (`attempt+1`) copying `ccur = pcur = old ccur` with tokens before it `committed` and the rest `unattempted`; the old read's rows are untouched.
- **Async guard** `(session_id, revision_id, turn_id)`; `turn_id` increments on sentence completion, skip, stop, state change.
- **Cancellation during playback** comes from the console/Face (`/stop`, key); spoken `stop` works while listening.
- **Input routing by state**: READ → align; PRACTICE → retry test; CHECK → local keyword comparison; REVIEW_DUE → `again`/`good`; EXPLAIN/CORRECT → that grammar; controls everywhere, inapplicable control → spoken no-op.

## Correction interaction (owner of coordinates: ADR-0010 §6; this section says what the reading state does)

A correction creates revision r+1 with an edit map. The current `ReadingState` is re-tokenised on r+1: every token whose char span (mapped through the edit map) overlaps the edited span becomes `unattempted`; `pcur` and `ccur` are mapped through the edit map and clamped to the first such token if they were past it. Miscues of **any** earlier revision are invalidated when their `expected_char_span` (stored in their own revision's coordinates) maps, through the chain of edit maps up to r, into a span that overlaps the corrected span (ADR-0010 §6 as amended). Difficulties are recomputed inside the same transaction.

## Difficulties (single formula; data-model.md repeats only the column names)

`weight = Σ over sessions s of (1.0 if the word had a confirmed miscue in s else 0.3 if it had an unsure miscue in s else 0) × 0.5^(days_since(s)/30)`, counted only when the word appears in ≥ 3 distinct sessions for `unsure` evidence or ≥ 1 for `confirmed`. Watch (unsure-only) items order Practice and never produce a "wrong" line or a card by themselves.

## CHECK outcomes

`correct` (all keywords of at least one acceptable answer present after `norm`), `incorrect` (the answer has ≥ 2 content words, is not a skip/"I don't know", and matches no acceptable set), `unavailable` (skip, no answer, "I don't know", Brain unavailable). Leafi then gives the answer in the Coach voice regardless; only `incorrect` writes an `encounters` row (`trigger=check`).

## Consequences

- One function, one state, scenario tests: (a) one word per utterance commits through singleton accumulation; (b) "The dog red." then silence → candidate `ran`, sentence completes by pause, practice runs, CHECK sees "The dog ran." completed with `ran` as a candidate/unsure; (c) "little cap / cat sat on the mat" withdraws `self_corrected`; (d) identical sentences advance (documented), `/back` returns.
- ADR-0009 and ADR-0012 are superseded; their option analysis stays for history.

## Confirmation

`tests/test_alignment.py` implements the four walkthroughs plus skipped line, 15 % noise, trailing insertion, reread of three words, and the invariants (unread/unattempted suffix never a candidate; `ccur ≤ pcur`; deterministic).
