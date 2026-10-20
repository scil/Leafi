---
status: superseded by 0013
date: 2026-10-19
amends: 0009
---

> Superseded the same day by ADR-0013, which states the reading algorithm once with pseudocode (codex review round 3: the anchor gate blocked singleton accumulation, ties on identical text, completion events, text-mode practice status). Kept for the reasoning.

# Alignment keeps a reading state across utterances; candidates reconcile; nothing is "confirmed" without acoustic evidence

## Context

ADR-0009 fixed the shape of alignment (observations, bounded window, committed cursor) but evaluated commitment per utterance and let a repeated transcript disagreement confirm a miscue. Codex review round 2 (§4.1–4.6, §3.1) showed: one-word-per-utterance reading never commits; a final-word substitution has no completion path; a natural self-correction does not withdraw the candidate; repeated passages make commitment ambiguous; a skipped line falls outside the window with no recovery; a systematic ASR error ("three" → "tree") would confirm a false miscue.

## Decision outcome

### 1. Reading state is per page read and persists across utterances

`ReadingState(page_read_id, revision_id, tokens: list[TokenState], committed_cursor, turn_id)` where `TokenState ∈ {unattempted, provisional_match, committed, candidate_substituted, candidate_deleted, withdrawn, skipped_by_learner}`. `align()` is still pure: it takes the state and an utterance and returns a new state plus the observations it added. Commitment is evaluated over the **merged** provisional evidence: a run of ≥ 2 consecutive tokens in `provisional_match` (across any number of utterances) commits up to the run's end; at a sentence end, a run of 1 commits.

### 2. Window, free prefix, ties

- Window = `[committed_cursor − reread_back(6), committed_cursor + 1.5 × n_words + 8]`, extended backward to the start of the current sentence if that is further back.
- Only tokens in the reread region (before `committed_cursor`) are a free prefix. Expected tokens after the cursor that precede the first match become `candidate_deleted` only if ≤ 3 tokens and the following match run is ≥ 2; otherwise they stay `unattempted` and the utterance is treated as a reposition (§3).
- Alignment cost is cursor-relative: each token of jump from the provisional cursor adds 0.1; a tie between a reread path and an advance path stays provisional with no commitment until the next utterance disambiguates; if still tied after two utterances, Leafi asks ("Are you reading this line again?") — a control answer, not a judgement.

### 3. Reposition and restart

An utterance with no anchor (no match run ≥ 2 inside the window, or best score below `anchor_min`) is `unanchored`: stored, no observations. After two consecutive unanchored utterances the window becomes the whole page once; a unique anchor of ≥ 3 consecutive matches repositions the cursor there (tokens in between become `unattempted`, never deleted); otherwise state `REPOSITION`: Leafi asks the learner to read the first words of their line, no assessment until anchored.

### 4. Reconciliation withdraws candidates

A later match covering a token that holds a candidate (a self-correction "little cap… cat sat", a reread, a practice retry) sets it `withdrawn (self_corrected | reread | practice)`; the original observation rows stay. Reread matches therefore **do** produce `matched` observations (ADR-0009 §2's "no new observation" is replaced by "no new candidate").

### 5. Sentence and page completion

A sentence is complete when the committed or provisional cursor passes its last token, **or** when the utterance ends with a pause ≥ `sentence_pause_s` (1.2) and the provisional alignment reached one of the sentence's last two tokens. At completion: candidates in the sentence go to Practice (max 2 words, ordered by Difficulty weight then position); a substituted last token is a candidate; an unspoken last token stays `unattempted` and is reported in the summary as unread, never practised. The page is complete when every sentence is complete or the learner turns the page / says next page; CHECK runs on the committed text only.

### 6. Candidate lifecycle without acoustic evidence

Practice outcomes: any retry that matches → `withdrawn (practice)`; all retries disagree or the learner skips → `unsure`. A candidate becomes `confirmed` **only** with acoustic evidence (`PRON_AUTO_JUDGE` on after its evaluation, ADR-0011). Repeated transcript disagreement never confirms. Text mode: practice ends as `unsure` with a `practices` row `(outcome=practiced, evidence=none)`.

Difficulties v1: from `confirmed` miscues (weight 1.0 per session) and from `unsure` miscues on the same word in ≥ 3 distinct sessions (weight 0.3, "watch"); watch items only order Practice and never produce a "wrong" line or a card by themselves.

### 7. Input routing is by state; async results carry a turn id

READ → alignment; PRACTICE → retry match against the practised word; CHECK → local keyword comparison; REVIEW_DUE → rating words (`again`/`good`, `/again` `/good`); EXPLAIN/CORRECT → the grammar for that state. Controls apply everywhere; a control that does not apply in the current state is a spoken no-op ("not now"). Every asynchronous request carries `(session_id, page_revision_id, turn_id)`; `skip`, `stop`, a state change or a new sentence bumps `turn_id`; a result whose tuple is stale is discarded.

### 8. Cancellation during playback (v1)

The Listener is paused while a Mouth plays, so spoken `stop` works only while listening; cancellation during playback comes from console/Face controls (`/stop`, a key press). This is stated to the learner once per session.

## Consequences

- `align()` has a richer input (state) but stays pure and deterministic; tests are scenario-driven over sequences of utterances.
- Without the pronunciation scorer, Leafi never tells the child a word was wrong; it asks for another try and moves on.
- The data model adds `tokens` state to `page_reads` (json) and `turn_id` to async requests.

## Confirmation

`tests/test_alignment.py` scenarios from the two reviews: one word per utterance commits; final-word substitution → candidate → practice → unsure; "little cap / cat sat" withdraws; "I can see it. I can see it." tie stays provisional then resolves; skipped line → unanchored ×2 → reposition without deletions; "tree" for "three" twice → unsure, never confirmed, no Difficulty before the third session.
