---
status: accepted
date: 2026-10-19
---

# Self-improvement is stored data (corrections, lexicon, learner profile), not model training

## Context

The owner wants Leafi to get better with use: fewer OCR misreads of the child's books, fewer false "mispronounced" flags, practice that targets what this learner actually struggles with. Research shows fine-tuning ASR on child speech helps (Kid-Whisper), but needs data, GPU time and evaluation discipline.

## Considered options

1. Fine-tune ASR/OCR on collected data periodically.
2. Keep models fixed; store corrections and derived data that steer the fixed models and the coach.

## Decision outcome

Option 2 for v1, with three loops:

1. **Corrections → Page text.** A corrected span becomes `pages.text_truth`; that page is never OCR-trusted again; the correction row is provenance.
2. **Lexicon → models.** Words from the learner's books and corrections become ASR hotwords (if the transducer path supports them; prototype P-1) and an OCR post-correction dictionary (edit-distance snap for words within 1 edit of a lexicon entry, only when OCR confidence is low).
3. **Learner profile → coach.** Recurring miscues and knowledge items become `difficulties` with weights; the coach prompt and the card builder read them.

A fourth, cheap loop: every session appends text-only transcripts of coach turns to `data/evals/` so a future prompt eval can be built from real sessions (`claude-api build-eval`).

## Consequences

- No training pipeline, no GPU schedule, no privacy question about audio datasets.
- Improvements are explainable: the parent can open the corrections table.
- Fine-tuning stays available later; this ADR would be superseded, not edited.

## Confirmation

`tests/test_corrections.py` (truth wins, provenance kept), `tests/test_lexicon.py` (rebuild keeps manual rows), `tests/test_knowledge.py` (difficulty weights order practice).
