---
status: accepted
date: 2026-10-19
---

# Reading is verified by aligning the transcript to the expected page text; phonemes only on flagged words

## Context

"Help the child read words right" needs a decision per expected word. Raw word error rate against free transcription punishes the learner for ASR mistakes and gives no per-word answer. Project LISTEN and Microsoft Reading Coach both align what was heard to what should have been read.

## Decision drivers

- Child-speech ASR noise of 10–15 % WER is expected; the method must tolerate it.
- Feedback must name the word, not a score.
- Phoneme scoring is slower and has false alarms on short words.

## Considered options

1. Free transcription + WER.
2. Forced alignment of audio to the expected text (MFA / torchaudio) and GOP scoring for every word.
3. Word-level sequence alignment (Needleman–Wunsch over normalised tokens with a fuzzy-match substitution cost) between the ASR transcript and the expected words from the reading cursor; verdict per expected word; the pronunciation scorer runs only on `mispronounced`/`unsure` words at Practice time.

## Decision outcome

Option 3. `alignment.align(expected, utterance) -> list[Verdict]` is pure, deterministic and the main test seam. Normalisation: lowercase, strip punctuation, number words, common contractions table. Substitution cost uses `rapidfuzz` similarity; `unsure` when ASR word confidence < `alignment.unsure_below` (0.5). A sentence boundary triggers feedback; a single miscue mid-sentence does not interrupt.

## Consequences

- No forced aligner dependency; timestamps from the ASR are enough to cut the practice clip.
- Homophones and ASR normalisation (e.g. "two"/"to") need the normalisation table to grow from real sessions (data loop, ADR-0006).
- Fluency metrics (wpm) come from utterance timestamps, free.

## Confirmation

`tests/test_alignment.py`: perfect read, one substitution, one skip, one insertion, ASR noise within tolerance, cursor advance, sentence-boundary detection.
