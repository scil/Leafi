# Prior art for Leafi book study (reference collection)

Checked: 2026-10-19. Method: `tiered-research` (authority tiers) + `gather-code-references` (dossiers → decision pool). Tier 1 = the owner's own docs; Tier 2 = empirical studies; Tier 3 = exemplar projects; Tier 4 = blogs and secondary coverage. A single Tier 2 or Tier 4 row never decides a choice by itself.

Decision it serves: the architecture and plan in [`../plans/active/2026-10-19-leafi-book-study.md`](../plans/active/2026-10-19-leafi-book-study.md) and the ADRs in [`../adr/`](../adr/).

## 1. Project facts (not research)

| Fact | Value | Source |
|---|---|---|
| Python | 3.12.10 venv, `uv` 0.12.19 available, venv has no `pip` | `importlib.metadata` listing |
| GPU | RTX 5070 Ti 16 GB, driver 610.88, `torch==2.11.0+cu128` installed | `nvidia-smi`, package list |
| Installed packages of note | anthropic 0.120.2, edge-tts 7.2.8, httpx 0.28.1, opencv-python 5.0.0, ultralytics 8.4.115, paho-mqtt 2.1, APScheduler 3.11, pydantic 2.13, pytest 9.1 + pytest-asyncio 1.4 | package list |
| Ollama | scoop 0.32.1 installed, server not running, no models pulled | `ollama list` error, port 11434 refused |
| Anki | desktop open, AnkiConnect v6 reachable at 127.0.0.1:8765; decks `ai-teach-me, Default, En, En2, Gurmukhi, IT, Phrases`; note types include `问答题`, `填空题` | live `deckNames` / `modelNames` |
| Camera | Xiaomi Smart Camera 3 PTZ via patched host go2rtc (`tools/go2rtc`, v1.9.14 + 2 local patches), speaker works (opus 16 k mono); host go2rtc was not running at check time | `tools/go2rtc/PATCHES.md`, port 2984 refused |
| ffmpeg | `D:\A\Scoop\shims\ffmpeg.exe` | `Get-Command` |
| codex CLI | 0.155.0; accepts `-c model="gpt-6-astra"` (the `codex-review` skill says it was rejected since 2026-09-18; it is accepted again) | live `codex exec` |
| Candidate wheels resolvable for py3.12/win | sherpa-onnx 1.13.8, kokoro-onnx 0.6.1, rapidocr 3.10.0, onnxruntime 1.31.0, openpronounce 0.3.0, sounddevice 0.5.6, zxing-cpp 3.1.1, rapidfuzz 3.14.6, g2p-en 2.1.0 | `uv pip install --dry-run` |

## 2. Dossiers

### 2.1 Reading tutors (what "help the child read" looks like)

| Resource | Tier | What it is | Adoptable | Not adoptable |
|---|---|---|---|---|
| Microsoft Reading Coach FAQ, https://support.microsoft.com/en-US/education/reading-coach-faq | T1 (vendor) | Free oral-reading practice tool. Real-time feedback on pronunciation and syllabification; after a passage, **Word Practice** on the words the reader missed (hear the model, record, compare); progress insights (accuracy, time, words to practice); voice processed on device. Explicitly does **not** test comprehension. | The loop *read → list missed words → practice each → re-read*; on-device voice; per-passage insights. | Closed; no camera; no comprehension (we add it). |
| Project LISTEN Reading Tutor (CMU), https://www.ri.cmu.edu/publications/why-and-how-our-automated-reading-tutor-listens | T2 (research, 2003–2012) | Classic ASR reading tutor for grades 1–4. Aligns recognizer output to the *target text* so detected misreads are credited, instead of reporting raw WER. | Alignment-to-expected-text as the core metric; "accept the child's reading as the hypothesis space". | Kaldi/GMM era code. |
| DART tutor (Radboud) and Utrecht thesis on wav2vec2 for Dutch children, https://www.ru.nl/en/research/research-news/learning-to-read-better-with-software-that-listens-and-gives-feedback | T2 | Word-level correct/incorrect feedback for first-graders; wav2vec2 phone-level detection beat a GOP baseline. | Word-level verdicts are achievable; phoneme-level needs a phone recognizer. | Dutch. |
| Kid-Whisper (AAAI/AIES 2024), https://ojs.aaai.org/index.php/AIES/article/view/31618 | T2 | Fine-tuning Whisper-small on child speech cut MyST WER 13.9 % → 9.1 %. | Expect child-speech WER well above adult; design alignment to tolerate ~10–15 % ASR noise; a later fine-tune is a known lever. | — |
| arXiv 2605.28833 (2026), nine ASR models on Dutch child speech (Whisper, Parakeet, wav2vec2) | T2, not read in full | Comparison exists; results not extracted here. | Read before swapping ASR backends. | — |

Conclusion: the industry pattern is *expected-text alignment + word-level verdict + targeted word practice*; phoneme-level feedback is an add-on, and comprehension is a separate, LLM-shaped step.

### 2.2 Pronunciation assessment (phoneme level)

| Resource | Tier | Notes | Decision |
|---|---|---|---|
| OpenPronounce, https://github.com/Halleck45/OpenPronounce (MIT, PyPI 0.3.0) | T3 | wav2vec2 phone recognizer `facebook/wav2vec2-lv-60-espeak-cv-ft` + `wav2vec2-large-960h` + espeak-ng phonemization; aligns expected vs heard phones by edit distance; flags a word at ≥40 % mismatched sounds or 2 sounds; English calibrated (ρ≈0.65 vs humans on 500 speechocean762 utterances, self-reported). Needs espeak-ng + ffmpeg; ~1.2 GB per checkpoint; CPU ok, CUDA auto. 143 stars, small maintainer base. | **Adopt the method; depend on the package behind a port** so the backend can be replaced. |
| `pronounce-assess`, `mimora` (PyPI) | T3/T4 | Same family (wav2vec2 phoneme CTC vs reference IPA). mimora page did not load. | Alternatives, not chosen. |
| speechocean762, https://arxiv.org/abs/2104.01378 | T2 | 5 000 English utterances, 250 non-native speakers, half children; free for any use. | Calibration/eval corpus when we tune thresholds. |
| arXiv 2506.12067 (logit-based GOP), 2603.25150 (GOP without alignment) | T2 | Current research direction: GOP from CTC logits, no forced alignment. | Watch; not v1. |

### 2.3 ASR (local, English, word timestamps)

| Resource | Tier | Notes |
|---|---|---|
| sherpa-onnx pretrained index, https://k2-fsa.github.io/sherpa/onnx/pretrained_models/index.html | T1 | Offline NeMo transducer **Parakeet TDT 0.6B v2 int8** (English), v3 (25 languages), Parakeet CTC 110M; streaming Zipformer EN; Whisper; SenseVoice; Moonshine. PyPI `sherpa-onnx` 1.13.8 resolves on Windows/py3.12. |
| NVIDIA Parakeet TDT 0.6B v2 collection, https://catalog.ngc.nvidia.com/orgs/nvidia/-/collections/parakeet-tdt-0.6b-v2 | T1 | English-only, native punctuation/capitalization, **word-level timestamps**, 600M params. |
| sherpa-onnx hotwords, https://k2-fsa.github.io/sherpa/onnx/hotwords/index.html | T1 | Contextual biasing only for **transducer** models with `modified_beam_search`; file = one phrase per line with optional `:score`; needs `modeling-unit` (`bpe` for English) and `bpe.vocab`. Whether the NeMo-transducer loader honours hotwords is **unverified** → prototype. |
| faster-whisper / Whisper | T2 (via child-speech papers) | Works; needs `language="en"` forced; no hotwords; heavier. Fallback backend. |

Decision: `sherpa-onnx` + Parakeet TDT v2 int8 as the default ASR (offline, timestamps, Apache-2.0 model). Silero VAD through sherpa-onnx for endpointing. Hotword biasing from the page's vocabulary is a prototype question, not a promise.

### 2.4 TTS (local English, child-friendly latency)

| Resource | Tier | Notes |
|---|---|---|
| kokoro-onnx, https://github.com/thewh1teagle/kokoro-onnx (MIT; model Apache-2.0; PyPI 0.6.1) | T3 | 82M-param Kokoro v1.0 via ONNX Runtime; needs `kokoro-v1.0.onnx` + `voices-v1.0.bin`; CPU near real-time; voices listed in Kokoro-82M `VOICES.md`. |
| Picovoice on-device TTS benchmark, https://picovoice.ai/blog/on-device-tts/ | T4 (vendor-run) | Piper ≈2× real-time on one core but ~1.5 s first audio; Kokoro higher quality, ~2.9 s first audio on a Ryzen 5700X. Treat as one data point. |
| Piper license change to GPL-3.0 (reported in the same survey) | T4 | Reason not to pick Piper. |
| edge-tts (already in use) | T3 | Cloud, unofficial, rate-limit risk; best Chinese voices; keep as the Chinese/secondary backend with local fallback. |

Decision: Kokoro (local) for English model pronunciations and coach lines; edge-tts kept for Chinese and as a quality alternative; file cache in front of both (existing `cache/tts`).

### 2.5 OCR for photographed book pages

| Resource | Tier | Notes |
|---|---|---|
| RapidOCR docs, https://rapidai.github.io/RapidOCRDocs/main/install_usage/rapidocr/usage/ (PyPI `rapidocr` 3.10.0) | T1 | ONNX Runtime default; `ocr_version` per stage (PP-OCRv4/v5/v6), `model_type` tiny/small/mobile/medium; `list_supported_langs("rec", "PP-OCRv6", "medium")`; output `boxes (N,4,2)`, `txts`, `scores`, `word_results` with `return_word_box=True`. GPU only via torch engine. |
| PaddleOCR site, https://www.paddleocr.ai/latest/ | T1 (vendor claims) | PP-OCRv6 (2026-06) medium ≈34.5M params; vendor says it beats PP-OCRv5 server and Qwen3-VL-235B on its benchmark. Windows + RTX 50-series needs a special CUDA 12.9 wheel for PaddlePaddle → avoid the Paddle runtime, use ONNX. |
| Roboflow OmniDocBench round-up (2026-08), https://blog.roboflow.com/best-open-source-ocr-models/ | T4 | Small document specialists (PaddleOCR-VL-1.6 96.3 %, MinerU2.5-Pro, GLM-OCR) beat Qwen3-VL-235B (89.8 %) on document parsing; Qwen3-VL wins on versatility (QA over the page). |
| Qwen3-VL via Ollama (`qwen3-vl:8b`, Q4 ≈12 GB VRAM) | T4 (guides) | Fits 16 GB; book-page transcription accuracy unverified; useful as *reader of last resort* and for layout/illustration questions. Ollama 0.32.1 is installed but not running; model not pulled. |
| page-dewarp (PyPI), https://pypi.org/project/page-dewarp | T3 | Cubic-sheet dewarping of curved pages (Zucker 2016 fork). Slow-ish; optional pre-step when curvature hurts OCR. |

Decision: RapidOCR (PP-OCRv5/v6 English, ONNX, CPU) is the primary OCR; `qwen3-vl` behind the same port as a second opinion and for "what is on this page" questions; both local. User corrections override OCR (see §2.8).

### 2.6 Hardware abstraction (many devices, 0–N mouths)

| Resource | Tier | What to take |
|---|---|---|
| Wyoming protocol, https://github.com/OHF-Voice/wyoming (MIT) | T1 | JSONL header + binary payload; events `audio-start/chunk/stop`, `transcribe/transcript`, `synthesize/synthesize-*`, `detect/detection`, satellite `run-pipeline(start_stage,end_stage)`, `describe/info` where a server **advertises capabilities by domain** (`asr`, `tts`, `wake`, `mic`, `snd`, `satellite`). **Take: capability advertisement by domain, pipeline start/end stage, and audio framing.** Later: a Wyoming adapter makes any HA satellite a Leafi ear/mouth. |
| Home Assistant Assist pipeline, https://developers.home-assistant.io/docs/voice/pipelines/ | T1 | Four stages wake → stt → intent → tts with `start_stage` / `end_stage`; satellites map Wyoming domains onto stages. **Take: a session asks for a pipeline slice, not for a device.** |
| xiaozhi-esp32 WebSocket protocol, https://github.com/78/xiaozhi-esp32/blob/main/docs/websocket.md | T1 | ESP32 client: `hello` handshake (Opus 16 kHz mono, 60 ms frames; v2/v3 headers for AEC), device→server `listen start/stop/detect`, `abort`, `mcp`; server→device `stt` (shows recognized text), `tts start/stop/sentence_start{text}` (**subtitles on the screen**), `llm{emotion}`, `alert{status,message}`, binary Opus to play. **Take: an ESP32 is an Ear+Mouth+Face in one; subtitles come for free from `sentence_start`.** |
| xiaozhi-esp32-server (xinnan-tech, ~9.6k stars) and the Go rewrite | T3 | Pluggable ASR/LLM/TTS providers behind one streaming pipeline, provider switch by config. **Take: provider registry by config; do not take its Java/Vue management stack.** |
| go2rtc API, https://raw.githubusercontent.com/AlexxIT/go2rtc/master/website/api/openapi.yaml | T1 | `GET /api/frame.jpeg?src=&width=&height=&rotate=` snapshot; `POST /api/streams?src=&dst=` to push audio to a camera speaker (already used); `PUT/PATCH/DELETE /api/streams`. Xiaomi source has two-way audio; mic audio codec undocumented → probe in prototype. |
| Pipecat / LiveKit Agents comparisons, https://livekit.io/field-guides/guide/livekit-vs-pipecat | T4 (vendor) | Frame-based pipelines with Silero VAD and turn detection; barge-in handled by upstream cancel frames. **Not adopted** for v1: we need a turn-based reading loop, not a telephony pipeline; revisit if barge-in becomes a requirement. |

### 2.7 Review and spaced repetition

| Resource | Tier | Notes |
|---|---|---|
| AnkiConnect (local add-on, version 6) | T1 (live probe) | JSON over HTTP at 127.0.0.1:8765; Anki must be open. The shared `anki-cards` skill's `anki_lib.AnkiClient` already wraps it (UTF-8, retries). FSRS scheduling lives inside Anki. Upstream README fetch failed (sourcehut 502); action names are taken from the working scripts in `E:\GitHub\scil\ai-skills\skills\anki-cards\scripts`. |
| Lute v3, https://github.com/LuteOrg/lute-v3 (MIT, Python/Flask) | T3 | Reading-based language learning: per-term status, parent terms, sample sentences, Anki export. **Take: a term has a status and a parent form; sentences of all child forms count as examples.** |
| Tsunagi (Anki forum, 2026-10) | T4 | A newer add-on with an AnkiConnect-compatible shim; irrelevant while AnkiConnect works. |

### 2.8 Self-improvement without training

Sources above imply three cheap loops: (1) user corrections become page ground truth and never need OCR again; (2) the book's vocabulary becomes ASR hotwords and an OCR post-correction dictionary; (3) the learner's miscue history weights what the coach practises and what gets a card. All three are data, not weights (ADR-0006).

### 2.9 Agent harness and LLM

| Resource | Tier | Notes |
|---|---|---|
| `claude-api` bundled skill (Anthropic, cached 2026-10-06) | T1 | Default model `claude-opus-5-5` (adaptive thinking, effort default `medium`), `claude-haiku-5-5` for cheap workers; structured outputs via `output_config.format`; no prefill; `fallbacks: "default"` recommended by default; Python SDK 1.x is on `httpx2` (installed here: 0.120.2). |
| Tool Runner vs Claude Agent SDK vs Managed Agents (same skill) | T1 | A coach that calls a handful of local tools fits "Claude API + tool use" (manual loop or Tool Runner). Managed Agents would move the loop and sandbox to Anthropic, which the privacy stance rejects for anything touching audio/images. |

## 3. Decision pool

| # | Decision | State | Basis |
|---|---|---|---|
| D1 | Capabilities (Eye/Ear/Mouth/Face/Presence/Notifier) as ports; devices are adapters that implement several; a session asks the hub for a capability slice | **Adopted** | Reference (Wyoming domains, HA stages, xiaozhi) + user requirement (0–N mouths) |
| D2 | Zero mouths → every `say()` is rendered as text on Faces and the log; policy configurable | **Adopted** | User requirement |
| D3 | Model services (ASR/TTS/OCR/Pronunciation/LLM/VLM) behind ports with a `mock` backend each | **Adopted** | Reference (xiaozhi-server provider registry) + testability |
| D4 | Default backends: sherpa-onnx Parakeet TDT v2; Kokoro-onnx + edge-tts; RapidOCR + qwen3-vl; OpenPronounce-style wav2vec2 phonemes; Claude Opus 5.5 + Ollama fallback | **Adopted, backends replaceable** | References §2.3–2.5, §2.9 |
| D5 | Reading verification = align ASR transcript to expected page text → observations with a committed cursor; candidate miscues; phoneme scorer only on flagged words and only after evaluation | **Adopted (revised by ADR-0009/0011 after codex review)** | References §2.1–2.2 |
| D6 | Anki is the review scheduler (FSRS); Leafi's SQLite is the system of record; cards link back by note id | **Adopted** | Reference §2.7 + existing `anki-cards` tooling |
| D7 | Self-improvement = corrections/lexicon/learner profile as data; no fine-tuning in v1 | **Adopted** | §2.8 |
| D8 | Barge-in / full-duplex voice pipeline (Pipecat-class) | **Deferred** | Turn-based reading loop suffices for v1 |
| D9 | ASR hotwords from page vocabulary | **Needs prototype** | Unverified for NeMo transducer in sherpa-onnx |
| D10 | Camera mic as an Ear (go2rtc audio) vs PC USB mic | **Needs prototype** | Codec/sample rate undocumented; far-field quality unknown |
| D11 | PaddlePaddle GPU runtime on Windows/RTX 50 | **Rejected** | Special CUDA 12.9 wheel; ONNX path is enough |
| D12 | Piper TTS | **Rejected** | GPL-3.0 relicense; lower quality than Kokoro |

## 4. Research gaps (carried into the plan as prototype tickets)

1. Parakeet via sherpa-onnx: confirm `timestamps`/`tokens` fields on the Python result and hotword support for `model_type="nemo_transducer"`.
2. Xiaomi camera as microphone: does the cs2 stream carry audio go2rtc can re-encode to 16 kHz PCM, and is far-field quality usable for a child reading at a desk?
3. RapidOCR vs qwen3-vl on real photographed pages from the child's current books (skew, curvature, illustrations, dialogue punctuation).
4. OpenPronounce false alarms on short function words; threshold tuning against speechocean762 child subset.
5. Whether `anthropic` 0.120 → 1.x upgrade is needed for `fallbacks: "default"` and `output_config.format` (check SDK changelog before coding the brain).

## 5. Source table

| id | tier | url | source-date | checked |
|---|---|---|---|---|
| reading-coach-faq | T1 | https://support.microsoft.com/en-US/education/reading-coach-faq | undated (living) | 2026-10-19 |
| project-listen | T2 | https://www.ri.cmu.edu/publications/why-and-how-our-automated-reading-tutor-listens | 2012 | 2026-10-19 |
| kid-whisper | T2 | https://ojs.aaai.org/index.php/AIES/article/view/31618 | 2024 | 2026-10-19 |
| child-asr-dutch-2026 | T2 | https://arxiv.org/pdf/2605.28833 | 2026-05 | 2026-10-19 (abstract only) |
| openpronounce | T3 | https://github.com/Halleck45/OpenPronounce | PyPI 0.3.0, 2026-08-15 | 2026-10-19 |
| speechocean762 | T2 | https://www.arxiv.org/pdf/2104.01378 | 2021 | 2026-10-19 |
| sherpa-onnx-models | T1 | https://k2-fsa.github.io/sherpa/onnx/pretrained_models/index.html | undated (living) | 2026-10-19 |
| sherpa-onnx-hotwords | T1 | https://k2-fsa.github.io/sherpa/onnx/hotwords/index.html | undated (living) | 2026-10-19 |
| parakeet-tdt-v2 | T1 | https://catalog.ngc.nvidia.com/orgs/nvidia/-/collections/parakeet-tdt-0.6b-v2 | undated | 2026-10-19 |
| kokoro-onnx | T3 | https://github.com/thewh1teagle/kokoro-onnx | PyPI 0.6.1 | 2026-10-19 |
| picovoice-tts-bench | T4 | https://picovoice.ai/blog/on-device-tts/ | undated | 2026-10-19 |
| rapidocr-usage | T1 | https://rapidai.github.io/RapidOCRDocs/main/install_usage/rapidocr/usage/ | undated (living) | 2026-10-19 |
| paddleocr-site | T1 | https://www.paddleocr.ai/latest/ | PP-OCRv6 2026-06-11 | 2026-10-19 |
| roboflow-ocr-roundup | T4 | https://blog.roboflow.com/best-open-source-ocr-models/ | 2026-08 | 2026-10-19 |
| page-dewarp | T3 | https://pypi.org/project/page-dewarp | undated | 2026-10-19 |
| wyoming | T1 | https://github.com/OHF-Voice/wyoming | undated (living) | 2026-10-19 |
| ha-pipelines | T1 | https://developers.home-assistant.io/docs/voice/pipelines/ | undated (living) | 2026-10-19 |
| xiaozhi-websocket | T1 | https://github.com/78/xiaozhi-esp32/blob/main/docs/websocket.md | undated (living) | 2026-10-19 |
| xiaozhi-server | T3 | https://github.com/xinnan-tech/xiaozhi-esp32-server | undated | 2026-10-19 (via listings) |
| go2rtc-openapi | T1 | https://raw.githubusercontent.com/AlexxIT/go2rtc/master/website/api/openapi.yaml | undated (living) | 2026-10-19 |
| go2rtc-xiaomi | T1 | https://go2rtc.org/internal/xiaomi/ | undated (living) | 2026-10-19 |
| pipecat-vs-livekit | T4 | https://livekit.io/field-guides/guide/livekit-vs-pipecat | undated | 2026-10-19 |
| lute-v3 | T3 | https://github.com/LuteOrg/lute-v3 | undated | 2026-10-19 |
| claude-api-skill | T1 | bundled skill `claude-api` (Claude Code 2.1.299) | cached 2026-10-06 | 2026-10-19 |
| mattpocock-skills | T3 | https://github.com/mattpocock/skills | plugin 1.3.1 | 2026-10-19 |
