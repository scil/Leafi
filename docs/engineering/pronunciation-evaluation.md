# Pronunciation scorer evaluation (gates `PRON_AUTO_JUDGE`)

ADR-0011 keeps automatic pronunciation judgement off until a held-out, parent-labelled child-speech
evaluation shows a **false-correction rate ≤ 15 %** on **≥ 40 flagged words**. This page is the protocol;
the result goes into the plan's Surprises with the threshold that was chosen. Prototype P-4 (2026-10-20)
only proved the plumbing: OpenPronounce 0.3.0 runs offline on the GPU with Leafi's Kokoro reference voice,
0.06–0.8 s per word after a 15 s first load, and on synthetic voices scored a correct native "little" at
0.65 and the homophone "threw" for "through" at 1.00. That is why a measured threshold is needed.

## Definitions

- **Flagged word**: a word the reading session turned into a Practice candidate (ADR-0013) and the learner
  retried at least once; the scorer runs on the retry audio only (`Utterance.audio_ref`).
- **Parent label** per retry: `ok` (the word was said acceptably), `wrong` (clearly mispronounced), `unclear`
  (noise, two words, cut off). `unclear` rows are excluded from the rates but counted.
- **False correction**: the scorer would set `confirmed` (score < `PRON_CONFIRM_BELOW`) on a retry the parent
  labelled `ok`. **Miss**: score ≥ threshold on a `wrong` retry. The gate is on false corrections, because a
  wrong "no" to a child costs more than a missed one (research §2.9).

## Collecting the set (owner, at home)

1. Run real sessions with `AUDIO_KEEP_CLIPS=true` and `EVAL_TRANSCRIPTS=true` for a week; both stay local.
   Each kept retry clip is a 16 kHz mono wav under `data/evals/clips/<session>/<miscue_id>-<attempt>.wav`
   with a row in `data/evals/retries.csv`: `session_id, miscue_id, attempt, expected, heard_text, path`.
2. The parent listens to every clip once with the expected word visible and fills `label` (`ok|wrong|unclear`)
   in the CSV. No one else hears the clips; they are deleted after the evaluation (`forget --session`).
3. Stop when ≥ 40 rows are labelled `ok` or `wrong` across ≥ 3 sessions and ≥ 20 distinct words; aim for
   ≥ 10 `wrong` rows, otherwise the miss rate is meaningless.

## Scoring the set (agent, offline)

```
$env:LEAFI_NO_NETWORK="1"; .venv\Scripts\python scripts/probes/p4_openpronounce.py --eval data/evals/retries.csv
```

The script scores every labelled clip against `expected`, writes `data/evals/scores.csv`
(`…, score, phones_expected, phones_heard, label`) and prints, for thresholds 0.3, 0.4, 0.5, 0.6:

| threshold | flagged | false corrections | rate | misses | miss rate |

plus the score distributions of `ok` and `wrong` rows (min, quartiles, max).

## Decision rule

- Pick the highest threshold whose false-correction rate is ≤ 15 % with ≥ 40 flagged rows. Set it as
  `PRON_CONFIRM_BELOW` (today a constant in `study/session.py`; make it a setting when the value is known)
  and flip `PRON_AUTO_JUDGE=true` in `.env`.
- No threshold passes → keep `PRON_AUTO_JUDGE=false`, record the table, and look at the `ok` rows with low
  scores: short function words and flapped /t/ (as in "little") are the expected offenders; the fix is a
  per-word allow-list or an exact-match pre-check, not a lower bar.
- Repeat the evaluation after any change to the scorer, the reference voice or the microphone.
