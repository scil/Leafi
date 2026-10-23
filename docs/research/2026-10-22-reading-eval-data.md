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

## 4. Sources

| id | tier | title / url | source-date | checked | supports |
|---|---|---|---|---|---|
| S1 | T1 | OpenSLR SLR101 — https://openslr.org/101/ | undated page | 2026-10-22 | licence CC BY 4.0, file 520 MB, citation |
| S2 | T1 | Zhang et al., "speechocean762", Interspeech 2021 — https://arxiv.org/pdf/2104.01378 | 2021 | 2026-10-22 | speakers, recording, Table 1 rubric, free use |
| S3 | T3 | Hugging Face `mispeech/speechocean762` — https://huggingface.co/datasets/mispeech/speechocean762 | living page | 2026-10-22 | fields (age 6–37), splits 2.5k/2.5k, card licence (loader) |
| S4 | T1 | ACL Anthology 2026.conll-main.35 — https://aclanthology.org/2026.conll-main.35/ | CoNLL 2026, pp. 588–600 | 2026-10-22 | abstract; no availability text on the page |
| S5 | T1 | Rose et al., "A Dataset for Oral Reading in Young English Readers" — https://aclanthology.org/2026.conll-main.35.pdf | 2026 | 2026-10-22 | size, labels, consent for 239 recordings, LDC deposit "will be", OSF link |
| S6 | T1 | OSF API `nodes/v9hw4` (view-only link from S5) | created 2026-02-13, modified 2026-08-07 | 2026-10-22 | `public: false`, `node_license: null` |
| S7 | T1 | OSF API `nodes/v9hw4/files/osfstorage` (view-only) | file modified 2026-05-04 | 2026-10-22 | one file: annotation guidelines `.docx` |
