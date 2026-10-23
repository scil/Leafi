# Speaker-embedding model for voice recognition (reference collection)

Checked: 2026-10-22. Method: `tiered-research` + `gather-code-references`. T1 = the owner's own docs, model cards, licence fields, release assets, source code and the installed package; T2 = empirical studies; T3 = exemplar code or local inspection; T4 = secondary, "reported" only. Every claim traces to a row of §7. Rows marked *(inferred)* or *(not verified)* were not confirmed against a primary source. No model was downloaded and nothing played audio; the installed package was inspected with `python -I` only.

Decision it serves: plan `docs/plans/active/2026-10-22-ai-led-study.md` → M0.5 ("Decide the speaker-embedding model for ADR-0018 §1 … model, licence, version"), and ADR-0018 §1 *Recognition*: "Voice is primary: a sherpa-onnx speaker-embedding model, enrolled by averaging several clips; … thresholds come from this household's own probe". `identify()` accepts L when `best ≥ RECOG_ACCEPT[ear]` and `best − second ≥ RECOG_MARGIN[ear]` (ADR-0018 `identify` pseudocode).

Constraints every candidate is checked against:

- Local, offline, CPU acceptable; runs inside sherpa-onnx **1.13.8**, already in `.venv` for Parakeet TDT ASR and Silero VAD (S1).
- Learners are siblings aged about 6–12 plus guests; utterances are 1–3 s answers to "Hello! Who's reading today?".
- Ears: the DJI Mic Mini Bluetooth headset (16 kHz mono int16 from PortAudio, `docs/hardware/pc-dji-headset.md`) and possibly the Xiaomi camera microphone (Opus 48 kHz in the SDP, after camera AGC; `docs/hardware/xiaomi-camera-069a01.md`).
- Household speech is English with Chinese names and possibly Chinese speech (ADR-0018: "Mixed Chinese/English names … get their own probe cases").
- The weights' licence must allow use in a private household product without ambiguity; embeddings never leave the machine.

## 0. Findings that cut across candidates

1. **Every published error rate for these models is on adult speech** (VoxCeleb = celebrity interviews, CN-Celeb = Chinese celebrities, 3D-Speaker / "200k speakers" internal Chinese data, NeMo's mix of VoxCeleb, Fisher, Switchboard, LibriSpeech, SRE) (C1–C9). No sherpa-onnx model card or upstream card reports a child test set.
2. **Two independent studies agree that adult-trained embeddings degrade sharply on young children.** An ECAPA-TDNN trained on VoxCeleb (0.80 % EER on VoxCeleb1-O) gives 30.65 % (K), 31.75 % (grade 2), 23.90 % (grade 4), 12.55 % (grade 5) and 6.15 % (grade 10) on the OGI kids corpus (P4). A separate VoxCeleb2-trained ECAPA-TDNN gives 24–29 % EER for grades K–5 on CSLU Kids scripted speech, falling to 14–19 % at grades 8–10 (P3). Leafi's 6–12-year-olds sit in the worst band of both. Neither study tested CAM++, ERes2Net, ResNet34 or TitaNet; that the gap carries over to them is *inferred*.
3. **Children's voices drift year to year.** On an ECAPA-TDNN trained on child speech, intra-year EER at grades 1–4 is 15.5–22.5 % and inter-year EER rises to 23.4–40.3 % (P5). This supports ADR-0018's "probe repeated … every 6 months" and argues for re-enrolment on the same cadence. One study only.
4. **Short utterances cost accuracy even for adults.** ERes2NetV2 (VoxCeleb2-trained) goes from 0.61 % (full) to 0.98 % (3 s) and 1.48 % (2 s) on VoxCeleb1-O; in the same table ResNet34 is 1.47 % / 2.12 % and ECAPA-TDNN 1.27 % / 1.95 % at 3 s / 2 s (P2). These are the model authors' own numbers (one study). No source measured 1 s trials or children at 1–3 s.
5. **The household task is not the published task.** EER is measured on open verification across thousands of strangers. Leafi does closed-set identification among 2–4 enrolled siblings, plus rejection of guests. Siblings can be easier (few candidates) or harder (shared vocal traits); no source measured siblings *(not verified; research gap)*. This is why ADR-0018 takes the thresholds from a household probe.
6. **sherpa-onnx's manager does exactly what ADR-0018 needs except the margin.** `SpeakerEmbeddingManager.search(v, threshold)` returns only the best name (or ""), not its score or the runner-up (S3). The C++ `GetBestMatches(p, threshold, n)` returns sorted name+score pairs but is **not exposed in the 1.13.8 Python binding** (S2, S3). Leafi computes `best` and `second` with `score(name, v)` per candidate, or with its own cosine over stored vectors.

## 1. Candidates sherpa-onnx ships

All files are assets of the release tag `speaker-recongition-models` (spelling as upstream), published 2023-12-08, ONNX files re-uploaded 2024-10-14 (S4); SHA-256 values are in its `checksum.txt` (S5). All are 16 kHz, 80-dim fbank input (S6, S7). "Weights licence" is the licence attached to the upstream checkpoint the ONNX file was exported from.

| sherpa-onnx file | Size | Source / arch | Emb dim | Training data, language | Published EER (test set) | Weights licence | Notes |
|---|---|---|---|---|---|---|---|
| **`3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx`** | 28.3 MB | 3D-Speaker CAM++ (7.2 M params) | 192 (C2) | "large-scale Chinese and English speaker data" (C1); zh + en | CN-Celeb test 5.98 %, VoxCeleb1-O 1.16 % (C1) | **Apache-2.0** (ModelScope field, C1) | only bilingual model; 1.72 GFLOPs, RTF 0.013 single-thread CPU (P1) |
| `3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx` | 29.6 MB | CAM++ | 512 (C2) | VoxCeleb2 dev, 5,994 speakers; en (C3) | Vox1-O 0.73 %, E 0.89 %, H 1.76 % (C3, P1) | Apache-2.0 (C3) | dataset licence of VoxCeleb not restated by the card |
| `3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx` | 28.3 MB | CAM++ | 192 (C2) | ~200 k Chinese speakers (C4) | CN-Celeb test 4.32 % (C4) | Apache-2.0 (C4) | Chinese only |
| `3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx` | 71.4 MB | 3D-Speaker ERes2NetV2 (17.8 M) | 192 (C2) | ~200 k Chinese speakers (C5) | CN-Celeb test 3.81 % (C5) | Apache-2.0 (C5) | designed for short-duration SV (P2); 12.6 GFLOPs ≈ 7 × CAM++ (P2) |
| `3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx` | 26.5 MB | ERes2Net (6.6 M) | 192 (C2) | VoxCeleb2 dev (C6) | Vox1-O 0.83 % (C6); 3.28 % at 2 s (P2) | Apache-2.0 (C6) | weakest at 2 s in P2 |
| `3dspeaker_speech_eres2net_*_zh-cn_*` (base, base_200k, large, common) | 39.6–220.6 MB | ERes2Net variants | 192 (common, C2); others *not verified* | Chinese | 3D-Speaker test 6.34–7.21 % (README, C7) | Apache-2.0 (base_200k, common: C7) | Chinese only; large/common are heavy |
| `wespeaker_en_voxceleb_resnet34_LM.onnx` | 26.5 MB | WeSpeaker ResNet34-TSTP (6.63 M) | 256 (C8) | VoxCeleb2 dev, 5,994 speakers; en (C8) | Vox1-O-clean 0.797 %, E 0.937 %, H 1.695 % (C8) | **disputed**: HF card `cc-by-4.0` (C8); WeSpeaker docs "follows the license of it's corresponding dataset" (C9); VoxCeleb metadata now CC BY-SA 4.0, audio licence not stated (C10) | attribution at least; share-alike unclear |
| `wespeaker_en_voxceleb_resnet34.onnx`, `…_CAM++(_LM)`, `…_resnet152/221/293_LM` | 26.5–114.3 MB | WeSpeaker | 256 (ResNet34; others *not verified*) | VoxCeleb | per WeSpeaker docs (C9) | same dispute; HF `Wespeaker/wespeaker-voxceleb-resnet34` says apache-2.0 (C8) | the HF tag and the project rule disagree |
| `wespeaker_zh_cnceleb_resnet34(_LM).onnx` | 26.5 MB | WeSpeaker ResNet34 | 256 *(inferred)* | CN-Celeb; zh | — | HF tag apache-2.0 (C8) vs project rule → CN-Celeb is **CC BY-SA 4.0** (C11) | share-alike via the dataset rule |
| `nemo_en_titanet_large.onnx` | 101.4 MB | NeMo TitaNet-L (~23 M) | 192 *(not verified)* | VoxCeleb1+2, Fisher, Switchboard, LibriSpeech, SRE 2004–10; en (C12) | VoxCeleb1 cleaned 0.66 % (C12) | **CC-BY-4.0** (C12) | card warns of domain drop outside telephone/non-telephone data (C12) |
| `nemo_en_titanet_small.onnx` | 40.3 MB | TitaNet-S (~6 M, P6) | *not verified* | *not verified* | 0.68 % family figure is for the paper's models (P6) | *not verified* (NGC card not fetched) | fastest in the sherpa diarization example (S8) |
| `nemo_en_speakerverification_speakernet.onnx` | 23.4 MB | NeMo SpeakerNet | *not verified* | *not verified* | *not verified* | *not verified* (HF API answered 401) | superseded by TitaNet upstream *(inferred)* |

ECAPA-TDNN is **not** in the sherpa-onnx release (S4), although WeSpeaker publishes ECAPA checkpoints (C9). Using one would mean exporting it with `scripts/wespeaker/add_meta_data.py` (S7) — out of scope here.

## 2. sherpa-onnx APIs and versions

Installed: `sherpa_onnx` 1.13.8 (S1). Latest release: **v1.13.8, 2026-09-10** (S9); the default branch's last commit is 2026-10-22 (S9).

Python surface in 1.13.8 (S1, S3):

- `SpeakerEmbeddingExtractorConfig(model, num_threads=1, debug=False, provider="cpu")`; `SpeakerEmbeddingExtractor(config)` with `create_stream()`, `is_ready(stream)`, `compute(stream) -> list[float]`, `dim`.
- A stream takes `accept_waveform(sample_rate, samples)` and `input_finished()`; the upstream example states the sample rate "can be arbitrary" and passes the file's own rate (S10). Samples are float in [-1, 1] (3D-Speaker metadata `normalize_samples=1`, WeSpeaker `0` handled inside the runtime) (S6, S7).
- `SpeakerEmbeddingManager(dim)` with `add(name, v)`, `add(name, list_of_v)`, `remove`, `search(v, threshold) -> str`, `verify(name, v, threshold) -> bool`, `score(name, v) -> float`, `all_speakers`, `num_speakers`, `dim`.

Semantics read from the C++ source (S2):

- `add(name, list)` **sums the raw embeddings and normalises the sum** (comment: the mean is not needed because of the normalisation). Clips whose embeddings have larger norms weigh more. To get a plain mean of directions, Leafi normalises each clip's embedding before passing the list *(design choice, not upstream)*.
- `search`, `score` and `verify` normalise the query and use the dot product with unit rows, i.e. cosine similarity in [-1, 1]. `score` returns −2.0 for an unknown name.
- The upstream example's default threshold is 0.6 (S10); it is a demo value, not a calibration.

Changes on the default branch after v1.13.8 (S11):

- 2026-09-14, #3950 "Add GetEmbedding to SpeakerEmbeddingManager" (C++; lets a caller read back a stored vector).
- 2026-10-21, #4048 "Check the embedding size in the Python SpeakerEmbeddingManager methods". In 1.13.8 a wrong-length vector is therefore not checked in Python *(inferred from the fix)*; Leafi asserts `len(v) == manager.dim` itself.
- No change to the extractor implementation since 2026-08-04 (WebAssembly only) (S11). Nothing requires an upgrade; 1.13.8 runs every model in §1 (WeSpeaker runtime since 2024-01, the score function since 2024-04, S11).

Storage: ADR-0018 keeps embeddings in `data/learners/<id>/`. Leafi should store per-clip normalised vectors plus the model file name and SHA-256 (S5), and rebuild the in-memory manager at start. A model change invalidates every enrolment (vectors from different models are not comparable *(inferred)*).

## 3. Children and short utterances (tier 2)

| id | Study | Data (ages) | Model, training | Result | Scope limits |
|---|---|---|---|---|---|
| P3 | Singh, Sahidullah, Kinnunen, *ChildAugment* (arXiv 2402.15214, 2024) | CSLU Kids, K–grade 10 (≈ 5–16 y); single-word clips excluded | ECAPA-TDNN on VoxCeleb2 (Vox1-O 1.15 %) | scripted, cosine, no aug: boys 18.86 %, girls 22.38 % (S2S); per grade with aug: K–5 boys 23.6–27.2 %, girls 25.7–29.2 % | open-set EER; ≈ 3 s utterances (estimated from totals by the fetcher, *inferred*) |
| P4 | Zheng, Shetty, Balaji Shankar, Alwan, *AASV* (arXiv 2508.01637, Interspeech 2025 WOCCI) | OGI kids, K00–K10 | ECAPA, VoxCeleb1 + 2 | K00 30.65 %, K02 31.75 %, K04 23.90 %, K05 12.55 %, K10 6.15 %; Vox1-O 0.80 % | utterance length not stated |
| P5 | Shetty, Zheng, Lulich, Alwan (arXiv 2502.10511, ICASSP 2025) | CSLU K–10; IU set, 8 children grades 1–4, segments ≥ 2 s | ECAPA trained on child speech (CSLU) | intra-year G1–G4 15.5–22.5 %; inter-year 23.4–40.3 % | trained on children, so not an adult-model number |
| P2 | Chen et al., *ERes2NetV2* (arXiv 2406.02167, 2024) | VoxCeleb1-O, adults | VoxCeleb2 dev | 2 s / 3 s / full: ERes2NetV2 1.48 / 0.98 / 0.61 %; ERes2Net 3.28 / 1.89 / 0.83 %; ResNet34 2.12 / 1.47 / —; ECAPA 1.95 / 1.27 / — | authors' own model; adults |
| P7 | Tabatabaee et al. (arXiv 2608.03623, 2026) | classroom English (ages not stated on the abstract page) | ECAPA baseline vs WavLM-TDNN | relative EER −24 % vs ECAPA baseline; no absolutes on the abstract page | reported here only as direction |

What the studies agree on (P3, P4): adult-trained embeddings lose an order of magnitude or more on children under ~10, and fine-tuning or augmentation recovers part of it. What no study covers: CAM++/ERes2Net/TitaNet on children, 1–3 s child utterances, siblings, Bluetooth HFP or Opus channels. Fine-tuning on child data is out of scope for Leafi (no child corpus may be collected for training under ADR-0011); the household probe is the only calibration.

## 4. Recommendation

**Adopt `3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx`** (3D-Speaker CAM++, Chinese + English, 192-dim, 28.3 MB, SHA-256 `aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2`, Apache-2.0) from the sherpa-onnx release `speaker-recongition-models`, run by sherpa-onnx **1.13.8** on CPU with `num_threads=1`, as the primary candidate for the probe.

Provenance: Apache-2.0 on the ModelScope card of the exact checkpoint (C1) + bilingual training matching a household with English speech and Chinese names (C1) + lowest compute of the candidates, RTF 0.013 single-thread CPU (P1), i.e. ≈ 26 ms for a 2 s answer *(inferred)* + already runnable by the installed 1.13.8 (S1, S4).

Why not the others:

- **ERes2NetV2 zh-cn** (Apache-2.0, best CN-Celeb EER, built for short durations, P2) is the **challenger** in the probe: Chinese-only training and 7 × the compute, 71 MB. Choose it if it beats CAM++ on the household's 1–3 s trials.
- **WeSpeaker ResNet34-LM** has a licence dispute between its HF tag and the project's own rule (C8, C9, C10); with CN-Celeb the rule implies share-alike (C11). Use only if the probe shows a clear gain and the owner accepts CC BY attribution.
- **TitaNet-L** (CC-BY-4.0, attribution required, 101 MB) is English-only; a third probe candidate only if both 3D-Speaker models fail the probe.
- SpeakerNet, TitaNet-S: licence and data not verified.

Published EERs (0.7–6 %) do not predict Leafi's accuracy (finding 0.2). Plan for voice to be a **suggestion confirmed by "Is that you, <name>?"**, which ADR-0018 `identify` already does; the probe decides whether voice is good enough to offer a guess at all.

## 5. What the household probe must measure

Per Ear (DJI headset; camera microphone over Opus if TD-14 lands), per model (CAM++ zh_en; ERes2NetV2 zh-cn), with the owner present and the children consenting (ADR-0018 enrolment):

1. **Enrolment clips.** Each sibling records 8 clips of 2–4 s on that Ear across two sittings (different times of day). Measure accuracy with the first 3, 5 and 8 clips; pick the smallest count after which accuracy stops improving. Compare sherpa's sum-then-normalise against normalise-then-mean.
2. **Test trials.** ≥ 20 answers per child of the real kind ("It's <name>", "Me", Chinese and English), 1–3 s after VAD, recorded on a different day from enrolment; ≥ 20 impostor trials from adults and any available guest child. Also 1 s trials, to know where the floor is.
3. **Scores.** For every trial, the cosine to every enrolled learner: the distributions of `best` for genuine trials, of `best` for guests, and of `best − second` among siblings.
4. **Thresholds.** Choose `RECOG_ACCEPT[ear]` to keep guest false-accepts at ≤ 1 in the probe set (a guest wrongly named costs privacy, ADR-0018), then `RECOG_MARGIN[ear]` so that a sibling confusion is never accepted in the set. Report the genuine accept rate that results; if it is below about half *(owner to set)*, voice stays off for guessing on that Ear and identification falls back to names.
5. **Cross-Ear.** Enrol on Ear A, test on Ear B: whether one enrolment can serve both or enrolment is per Ear (ADR-0018 records the Ear).
6. **Conditions.** Bluetooth start-up noise on the first capture (pc-dji-headset datasheet), the camera's AGC and Opus, a TV or sibling speaking in the background.
7. **Latency.** Extractor wall time for 1, 2 and 3 s on the PC CPU with `num_threads=1` and 2, and model load time.
8. **Drift.** Repeat steps 2–4 after 6 months on the old enrolment and after re-enrolment (finding 0.3).

Retention of probe recordings needs an explicit owner decision: ADR-0018 says identification utterances are used in memory and never stored, and the probe needs recordings to score several models. Suggested: keep them only under `data/` (gitignored) until scoring is done, then delete them and keep only scores and thresholds.

## 6. Gaps

- Embedding dims of TitaNet, SpeakerNet and the minor WeSpeaker/ERes2Net variants were not verified (would need the ONNX metadata, i.e. a download).
- No source on sibling discrimination, on children at 1–3 s, or on Bluetooth HFP / Opus channels.
- NeMo NGC licence pages for TitaNet-S and SpeakerNet were not fetched.
- The 3D-Speaker card for the zh_en advanced model does not name its English training set; its VoxCeleb1-O 1.16 % may include VoxCeleb in training *(not verified)*.

## 7. Sources

All rows checked 2026-10-22. "Undated" = a living page or a file on a default branch.

| id | tier | title / url | source-date | checked | supports |
|---|---|---|---|---|---|
| S1 | T3 | Local inspection: `.venv\Scripts\python -I -c "import sherpa_onnx …"` (`__version__`, `dir()`, docstrings) | 1.13.8 installed | 2026-10-22 | installed version; Python API surface; no `get_best_matches` |
| S2 | T1 | sherpa-onnx `sherpa-onnx/csrc/speaker-embedding-manager.cc` — https://github.com/k2-fsa/sherpa-onnx/blob/master/sherpa-onnx/csrc/speaker-embedding-manager.cc | undated (last change 2026-09-14) | 2026-10-22 | sum-then-normalise, cosine, `GetBestMatches`, −2.0 sentinel |
| S3 | T1 | sherpa-onnx Python binding docstrings (in S1) and `sherpa-onnx/python/csrc/speaker-embedding-manager.cc` | 1.13.8 | 2026-10-22 | `search` returns name only; `score`, `verify`, `add` overloads |
| S4 | T1 | GitHub release `speaker-recongition-models` — https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models (via API) | published 2023-12-08; ONNX assets 2024-10-14 | 2026-10-22 | file list and sizes; no ECAPA |
| S5 | T1 | `checksum.txt` in S4 | 2026-05-20 | 2026-10-22 | SHA-256 of candidates |
| S6 | T1 | `scripts/3dspeaker/export-onnx.py` — https://github.com/k2-fsa/sherpa-onnx/blob/master/scripts/3dspeaker/export-onnx.py | undated | 2026-10-22 | metadata, 80-dim fbank, `normalize_samples=1`, model list |
| S7 | T1 | `scripts/wespeaker/add_meta_data.py` — https://github.com/k2-fsa/sherpa-onnx/blob/master/scripts/wespeaker/add_meta_data.py | undated | 2026-10-22 | WeSpeaker metadata, `normalize_samples=0` |
| S8 | T1 | sherpa docs, speaker diarization models — https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/models.html | undated | 2026-10-22 | example uses ERes2Net base and TitaNet-S; pipeline RTF only |
| S9 | T1 | GitHub API releases and commits — https://api.github.com/repos/k2-fsa/sherpa-onnx/releases | v1.13.8 2026-09-10; last commit 2026-10-22 | 2026-10-22 | latest release = installed |
| S10 | T3 | `python-api-examples/speaker-identification.py` — https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/speaker-identification.py | undated | 2026-10-22 | averaging per speaker, threshold 0.6, arbitrary sample rate |
| S11 | T1 | GitHub API commits by path (manager, Python binding, extractor impl) — https://api.github.com/repos/k2-fsa/sherpa-onnx/commits | #3950 2026-09-14; #4048 2026-10-21; extractor 2026-08-04 | 2026-10-22 | post-release changes |
| S12 | T1 | sherpa docs, speaker identification — https://k2-fsa.github.io/sherpa/onnx/speaker-identification/index.html | undated | 2026-10-22 | points to S4; no model list |
| C1 | T1 | ModelScope `iic/speech_campplus_sv_zh_en_16k-common_advanced` (API `License` field and README) — https://modelscope.cn/models/iic/speech_campplus_sv_zh_en_16k-common_advanced | updated 2024-06-24 | 2026-10-22 | Apache-2.0; zh+en training; CN-Celeb 5.98 %, Vox1-O 1.16 % |
| C2 | T1 | ModelScope `configuration.json` of the five 3D-Speaker models in §1 | per model | 2026-10-22 | `emb_size`/`embed_dim` 192 or 512; 16 kHz |
| C3 | T1 | ModelScope `iic/speech_campplus_sv_en_voxceleb_16k` | updated 2024-06-24 | 2026-10-22 | Apache-2.0; VoxCeleb2; Vox1 O/E/H; params, RTF |
| C4 | T1 | ModelScope `iic/speech_campplus_sv_zh-cn_16k-common` | undated revision | 2026-10-22 | Apache-2.0; 200 k speakers; CN-Celeb 4.32 % |
| C5 | T1 | ModelScope `iic/speech_eres2netv2_sv_zh-cn_16k-common` | updated 2024-07-10 | 2026-10-22 | Apache-2.0; CN-Celeb 3.81 % |
| C6 | T1 | ModelScope `iic/speech_eres2net_sv_en_voxceleb_16k` | updated 2024-06-24 | 2026-10-22 | Apache-2.0; Vox1-O 0.83 % |
| C7 | T1 | 3D-Speaker README — https://github.com/modelscope/3D-Speaker ; ModelScope licence fields of `eres2net_base_200k`, `eres2net_sv_zh-cn_16k-common` | undated | 2026-10-22 | repo Apache-2.0; benchmark table; weights licence per card |
| C8 | T1 | Hugging Face API and card `Wespeaker/wespeaker-voxceleb-resnet34-LM` (+ `…-resnet34`, `…-cnceleb-resnet34-LM` licence tags) — https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34-LM | modified 2024-05-06 | 2026-10-22 | cc-by-4.0 vs apache-2.0 tags; emb 256; VoxCeleb2 dev; EERs |
| C9 | T1 | WeSpeaker `docs/pretrained.md` — https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md | undated | 2026-10-22 | weights follow the dataset licence; model list incl. ECAPA |
| C10 | T1 | VoxCeleb1 page — https://www.robots.ox.ac.uk/~vgg/data/voxceleb/vox1.html | undated | 2026-10-22 | metadata CC BY-SA 4.0; audio licence not stated |
| C11 | T1 | OpenSLR 82 CN-Celeb — https://www.openslr.org/82/ | undated | 2026-10-22 | CC BY-SA 4.0 |
| C12 | T1 | HF `nvidia/speakerverification_en_titanet_large` — https://huggingface.co/nvidia/speakerverification_en_titanet_large | modified 2023-11-14 | 2026-10-22 | CC-BY-4.0; ~23 M; training sets; 0.66 %; domain warning |
| P1 | T2 | Wang et al., CAM++, Interspeech 2023, pp. 5301–5305, doi 10.21437/Interspeech.2023-1513 — https://arxiv.org/abs/2303.00332 | v3 2023-06-16 | 2026-10-22 | 7.18 M params, 1.72 GFLOPs, RTF 0.013 single-thread CPU; EER table |
| P2 | T2 | Chen et al., ERes2NetV2 — https://arxiv.org/abs/2406.02167 | 2024-06-04 | 2026-10-22 | 2 s / 3 s EERs; 17.8 M; 12.6 GFLOPs; emb 192 |
| P3 | T2 | Singh, Sahidullah, Kinnunen, ChildAugment — https://arxiv.org/abs/2402.15214 | 2024-02-23 | 2026-10-22 | adult-trained ECAPA on CSLU Kids by grade |
| P4 | T2 | Zheng et al., Age-Agnostic SV — https://arxiv.org/abs/2508.01637 | 2025-08-03 | 2026-10-22 | adult-trained ECAPA on OGI K00–K10 vs Vox1-O |
| P5 | T2 | Shetty et al., age-related robustness in child SV — https://arxiv.org/abs/2502.10511 | 2025-02-14 (ICASSP 2025) | 2026-10-22 | intra- vs inter-year EER for grades 1–4 |
| P6 | T2 | Koluguri, Park, Ginsburg, TitaNet — https://arxiv.org/abs/2110.04410 | 2021-10-08 | 2026-10-22 | TitaNet-S ~6 M; 0.68 % on VoxCeleb1 |
| P7 | T2 | Tabatabaee et al., SV under real classroom conditions — https://arxiv.org/abs/2608.03623 | v2 2026-08-06 | 2026-10-22 | direction only: classroom adaptation beats an ECAPA baseline |
| H1 | T1 | Leafi `docs/hardware/pc-dji-headset.md`, `docs/hardware/xiaomi-camera-069a01.md` | HEAD 8a3a0c0 | 2026-10-22 | Ear formats: 16 kHz int16; Opus after AGC |
| H2 | T1 | Leafi `docs/adr/0018-learners-and-privacy-v2.md` §1 | working tree | 2026-10-22 | `identify` acceptance rule, per-Ear thresholds, 6-month probe |
