# Public data for the reading evaluation (ADR-0013 → False-alarm budget; plan M4.4)

Checked: 2026-10-22. Method: `tiered-research` (T1 = the dataset's own site, its paper, the hosting API). Decision it serves: the owner asked (2026-10-22) to evaluate ADR-0013 v2's alignment on public data first — speechocean762, and the 2026 CoNLL oral-reading corpus if it can be obtained — with the owner's own recordings only as a later check on Leafi's devices.

## 1. Findings

| | speechocean762 | Storiza Corpus (Rose et al., CoNLL 2026) |
|---|---|---|
| What | 5,000 read-aloud English sentences, 250 speakers, Mandarin L1, half children; about 6 hours; 20 sentences per speaker; phone recordings at 16 kHz in a quiet room (S2) | 320 recordings of 63 U.S. 1st–3rd graders (English L1) reading GPT-generated phonics stories; ~9 hours, 33,612 words (S5) |
| Labels | five experts per utterance; scores at sentence, word and phone level (S2, Table 1) | manual word-level time alignment, IPA transcripts, 10 reading-error categories with 26 sublabels (S5) |
| Word-level label | accuracy 0–10: 10 correct; 7–9 correct with a heavy accent; 4–6 ≤ 30 % of phones wrong; 2–3 > 30 % wrong **or "mispronounced into some other word"**; 0–1 hard to distinguish **or missed** (S2, Table 1) | reading errors against the story text (S5) |
| Licence | CC BY 4.0 on OpenSLR (S1); the paper: "freely for commercial and non-commercial purposes" (S2). The Hugging Face card shows Apache-2.0, which covers its loader script, not the data (S3) | none stated for the data. The paper says 239 recordings (74.69 %) have parent consent to release and "will be deposited through" LDC, and that texts, alignments, transcripts and error annotations are "publicly accessible" via OSF (S5) |
| Access today | `speechocean762.tar.gz`, 520 MB, free download (S1) | **not obtainable**: no LDC catalog entry found; the OSF project behind the paper's link is private (view-only link), has no licence, and holds one file, the annotation guidelines (`.docx`, modified 2026-05-04) — no annotations, no audio (S6, S7) |

## 2. What each can measure for Leafi

**speechocean762 (usable now).** Each utterance is one sentence with its target text, so the pipeline runs end to end: audio → Parakeet → `align` against the sentence → candidates, compared with the experts' word labels.
- *False alarms* (ADR-0013's budgeted rate): a candidate on a word scored ≥ 7 (said correctly, possibly accented) is a false alarm. The set is large for this: most words of most utterances are correct.
- *Misses*: a word scored 0–3 ("into some other word" or "missed") is a reading error Leafi should flag; 4–6 is excluded from both counts (partly mispronounced, not a misreading).
- *Limits*: one sentence per utterance (the page pass and lost starts are not exercised); the errors are mostly pronunciation by learners reading a known sentence, so real misreadings are rare and the miss rate rests on few cases; adults are filtered out by the `age` field for the child figures; Mandarin L1 matches the household's learner.

**Storiza (not yet).** Exactly the target task (children's reading errors against the text, multi-sentence stories), but L1 English children and no data to download. Look again when an LDC entry appears; asking the authors for access is the owner's call.

**The owner's recordings (later).** Still needed once: the false-alarm and miss rates depend on Leafi's own microphone path (the DJI headset, the camera's Opus track), ASR settings and books, which no public set has. They become the last check, not the first.

## 3. Recommendation for plan M4.4

1. `doctor --download` gains `speechocean762` (520 MB into `data/evals/speechocean762/`, gitignored; CC BY 4.0, attribution to Zhang et al., Interspeech 2021, kept in the evaluation's output).
2. `scripts/evals/reading_eval.py --set speechocean762 [--max-age 12]` runs Parakeet and `align` per utterance and prints the false-alarm rate (budget ≤ 5 %), the miss rate, and the distributions that bracket each untuned threshold (ADR-0013 → False-alarm budget).
3. Storiza: re-check access in M10; no work until data exists.
4. The owner's labelled set: after (2), on the PC headset, silent.

## 4. (no section; numbering kept for links)

## 5. First results (2026-10-22, ADR-0013 v2 at 8bc2fe9)

`python scripts/evals/reading_eval.py --set speechocean762`: all 5,000 utterances, Parakeet TDT 0.6B v2 int8 on CPU, `LocalWordInfo` without word lists (lemminflect's dictionary for `is_word`, espeak-ng phones with homographs, lemminflect lemmas + overrides-1); 646 s. Labels: ≥ 7 correct, 0–3 error, 4–6 excluded.

| | all speakers | children ≤ 12 |
|---|---|---|
| utterances | 5,000 | 2,080 |
| unaligned utterances | 562 (11.2 %) | 306 (14.7 %) |
| correct content words | 13,092 | 5,464 |
| false alarms on them | 963 (**7.4 %**) | 539 (**9.9 %**) |
| false alarms that are substitutions / deletions | 918 / 45 | 525 / 14 |
| error words (scored 0–3) | 2,001 | 283 |
| caught (hits) | 393 (miss rate 80.4 %) | 60 (miss rate 78.8 %) |
| ASR confidence, correct words p10 / p50 / p90 | 0.816 / 0.998 / 1.0 | 0.775 / 0.996 / 1.0 |
| ASR confidence, false-alarm words p10 / p50 / p90 | 0.581 / 0.823 / 0.992 | 0.566 / 0.805 / 0.989 |

Reading of the numbers:
- **The budget (≤ 5 %) is breached** (TD-28). The false alarms are almost all substitutions the ASR heard confidently enough to pass `LOW_CONF` (0.5): accented vowels the experts accepted (see→say, where→were, know→now, all→are, live→leave, world→word) and names the ASR does not know (Layla→Lila, Jim→James, Mary→Marie, Tim→team). Their confidences sit well below correct words' (median 0.82 vs 0.998), so `LOW_CONF` is the first lever; its effect is measured, not assumed.
- **Unaligned utterances (11–15 %) are not false alarms but lost tracking**: short sentences read with several substitutions fall under the acceptance rules or the ceiling. They also hide words from the false-alarm count, so the true rate under a looser acceptance would be higher.
- **The miss rate (~80 %) mostly measures a different task**: a word scored 0–3 for pronunciation is often still recognised as the target word by an ASR whose language model expects it, so `align` sees a match. This set cannot say much about misreadings; the Storiza corpus or the owner's set must.

### 5.1 Second run: `LOW_CONF` 0.5 → 0.9 (2026-10-23, at da39206; one lever changed)

Same set, same `LocalWordInfo` versions, every other threshold unchanged (`ANCHOR_CONF` 0.8, `RETRY_MIN_CONF` 0.5, trigger 5, ceiling 7, page margin 10, now recorded in the result file); 680 s; `data/evals/results/reading-eval-speechocean762-20261023T065559Z.json` against `…T053452Z.json`.

| | all: `LOW_CONF` 0.5 | all: 0.9 | children ≤ 12: 0.5 | children ≤ 12: 0.9 |
|---|---|---|---|---|
| false alarms on correct content words | 963 (7.4 %) | 337 (**2.6 %**) | 539 (9.9 %) | 159 (**2.9 %**) |
| false alarms: substitutions / deletions | 918 / 45 | 292 / 45 | 525 / 14 | 145 / 14 |
| errors caught (hits) of 2,001 / 283 | 393 | 127 (**−68 %**) | 60 | 20 (**−67 %**) |
| miss rate | 80.4 % | 93.7 % | 78.8 % | 92.9 % |
| share of candidates that are real errors (hits ÷ (hits + false alarms)) | 29.0 % | 27.4 % | 10.0 % | 11.2 % |
| unaligned utterances | 562 (11.2 %) | 562 (11.2 %) | 306 (14.7 %) | 306 (14.7 %) |
| ASR confidence of remaining false alarms p10 / p50 / p90 | 0.581 / 0.823 / 0.992 | 0.911 / 0.976 / 0.999 | | |

Reading of the numbers:
- **The budget is now met** (2.6 %, children 2.9 % ≤ 5 %).
- **But the threshold did not separate errors from false alarms**: it removed about two thirds of each (false alarms −65 %, hits −68 %), so the share of candidates that are real errors stayed where it was (29 % → 27 %; children 10 % → 11 %). On this set, the ASR's confidence is as low on a word the experts scored 0–3 as on an accented word they accepted, so confidence alone buys the budget by practising fewer words, not by practising better ones.
- **Deletions are untouched** (45 before and after): `LOW_CONF` applies only to heard substitutions.
- **Unaligned utterances are unchanged**, as expected: `LOW_CONF` acts after acceptance.
- **Caveat on hits**: speechocean762's errors are mostly mispronunciations; a lower hit count here may matter less for real misreadings (substituted words), which only the Storiza corpus or the owner's set can show.

## 6. Sources

| id | tier | title / url | source-date | checked | supports |
|---|---|---|---|---|---|
| S1 | T1 | OpenSLR SLR101 — https://openslr.org/101/ | undated page | 2026-10-22 | licence CC BY 4.0, file 520 MB, citation |
| S2 | T1 | Zhang et al., "speechocean762", Interspeech 2021 — https://arxiv.org/pdf/2104.01378 | 2021 | 2026-10-22 | speakers, recording, Table 1 rubric, free use |
| S3 | T3 | Hugging Face `mispeech/speechocean762` — https://huggingface.co/datasets/mispeech/speechocean762 | living page | 2026-10-22 | fields (age 6–37), splits 2.5k/2.5k, card licence (loader) |
| S4 | T1 | ACL Anthology 2026.conll-main.35 — https://aclanthology.org/2026.conll-main.35/ | CoNLL 2026, pp. 588–600 | 2026-10-22 | abstract; no availability text on the page |
| S5 | T1 | Rose et al., "A Dataset for Oral Reading in Young English Readers" — https://aclanthology.org/2026.conll-main.35.pdf | 2026 | 2026-10-22 | size, labels, consent for 239 recordings, LDC deposit "will be", OSF link |
| S6 | T1 | OSF API `nodes/v9hw4` (view-only link from S5) | created 2026-02-13, modified 2026-08-07 | 2026-10-22 | `public: false`, `node_license: null` |
| S7 | T1 | OSF API `nodes/v9hw4/files/osfstorage` (view-only) | file modified 2026-05-04 | 2026-10-22 | one file: annotation guidelines `.docx` |
