---
status: superseded by 0013
date: 2026-10-19
supersedes: 0007
---

> Amended by ADR-0012 (same day, codex review round 2): §2's per-utterance commitment becomes commitment over a reading state kept across utterances; §2's "no new observation on reread" becomes "no new candidate"; §4's "retry again disagrees → confirmed" is withdrawn: `confirmed` needs acoustic evidence, otherwise `unsure`.

# Alignment produces observations with a committed cursor; a pronunciation judgement needs acoustic evidence

## Context

ADR-0007 chose transcript-to-expected-text alignment but let a transcript disagreement become a `mispronounced` miscue directly, aligned each utterance against the whole remaining page, and defined a verdict per expected word (which cannot represent insertions). The codex design review (round 1, A1, A2, D3, D4, G4) showed these would produce false corrections, cursor drift, and unrepresentable events. Child-speech ASR noise of 10–15 % is expected.

## Decision drivers

- A wrong "you said it wrong" to a 10-year-old costs more than a missed miscue.
- Hesitation, restarts and rereads are normal; VAD boundaries are not sentence boundaries.
- Typed text can exercise the flow but carries no acoustic evidence.

## Decision outcome

1. **Observation, not judgement.** `alignment.align(window, utterance, cursor) -> AlignResult` returns *observations*: `matched`, `substituted`, `deleted` spans over expected tokens, and `inserted` events anchored *between* expected tokens (so a trailing insertion is representable), plus `provisional_cursor` and `committed_cursor`. No observation is a pronunciation claim.
2. **Bounded, semi-global alignment.** The window is expected tokens from `committed_cursor - reread_back (default 6)` to `committed_cursor + 1.5 × len(utterance_words) + 8`. Expected tokens after the last matched token are **never** marked deleted; they stay unattempted. A `deleted` span counts only when followed by a later match in the same alignment. Tokens inside the reread window that match again produce no new observation (no duplicate penalty).
3. **Commitment rule.** `committed_cursor` advances to the end of the last run of ≥ 2 consecutive matched tokens (or 1 at a sentence end); everything after is provisional and may be revised by the next utterance.
4. **Candidate miscue → confirmed or unsure.** A `substituted` or `deleted` observation creates a `miscues` row with `status=candidate`. It becomes `confirmed` only by (a) the pronunciation scorer, when `PRON_AUTO_JUDGE=true` and its evaluation threshold has been met (ADR-0011), or (b) a Practice outcome where the learner's retry again disagrees with the expected word; it becomes `withdrawn` when the retry matches or the learner says Leafi misheard; otherwise `unsure`. Only `confirmed` miscues feed Difficulties, and a Difficulty needs corroboration across ≥ 2 sessions.
5. **Practice is model-and-repeat first.** Leafi models the word, invites a retry, cap 2 retries per word, always offers "skip". The default spoken outcome for a candidate is "let's hear it once more" and, when still unsure, "I may have misheard, let's move on", never "wrong".
6. **Text mode parity is functional.** In text mode the practice loop runs, outcomes are recorded as `practiced` with `evidence=none`; no acoustic success or failure is ever recorded (product B4/B11 wording updated).
7. **Control commands are not reading.** A spoken control (`stop`, `skip`, `next page`, `page twelve`, `I don't understand`, `the book says …`) is recognised only when the utterance is ≤ 6 words and matches the command grammar; typed controls use a `/` prefix. Page text that happens to contain a command phrase is read as text because it aligns to the page.

## Consequences

- `AlignResult` is the main test seam; tests must be multi-utterance scenarios with invariants (unattempted suffix never deleted; rereads not penalised; cursor explainable).
- Pronunciation scoring is optional hardware (`PRON_AUTO_JUDGE` off by default) and never required for the loop.
- Confidence from ASR may be unavailable; `unsure_below` applies only when confidence exists; missing confidence is `None`, not 0.

## Confirmation

`tests/test_alignment.py` scenarios: clean read; substitution; skip mid-sentence; trailing insertion; hesitation split across two utterances; restart of a sentence; reread of the previous three words; ASR noise at 15 %; cursor never passes an unattempted token. `tests/test_practice.py`: cap, skip, withdrawn/unsure/confirmed transitions; text mode never records acoustic evidence.
