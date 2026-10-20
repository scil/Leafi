---
status: accepted
date: 2026-10-19
---

# Model services sit behind ports with replaceable backends; defaults are local-first

## Context

Study needs speech recognition, speech synthesis, page OCR, pronunciation scoring and a language model. Each field has several usable open options and moves quickly. The privacy stance (security.md) forbids cloud vision and, by default, cloud audio.

## Decision drivers

- Red lines: images and audio local; cloud receives text only.
- Latency budgets (performance.md): feedback within 1.5 s of the end of an utterance.
- Windows + RTX 50-series: CUDA 12.8 torch is installed; PaddlePaddle GPU needs a special wheel; ONNX Runtime is the safe common path.
- Testability: every service needs a mock.

## Considered options (per service)

| Service | Options weighed | Chosen default | Why |
|---|---|---|---|
| ASR | sherpa-onnx Parakeet TDT 0.6B v2 int8 · faster-whisper · cloud ASR | **sherpa-onnx + Parakeet TDT v2** | offline, English, word timestamps, Apache-2.0 model, transducer (hotwords possible), ONNX |
| VAD | Silero via sherpa-onnx · webrtcvad | **Silero (sherpa-onnx)** | same runtime |
| TTS (en) | Kokoro-onnx · Piper · edge-tts · Chatterbox | **Kokoro-onnx** | local, Apache-2.0, best CPU quality; Piper rejected (GPL relicense, quality) |
| TTS (zh) | edge-tts · Kokoro zh | **edge-tts** (existing) with file cache | voice quality; local fallback stays possible |
| OCR | RapidOCR (PP-OCRv5/v6, ONNX) · PaddleOCR runtime · Qwen3-VL via Ollama · Surya · cloud OCR | **RapidOCR primary, qwen3-vl second opinion** | small specialists beat large VLMs on document text; VLM answers layout/illustration questions |
| Pronunciation | OpenPronounce (wav2vec2 phonemes) · GOP research code · cloud assessment | **OpenPronounce-style wav2vec2 phoneme comparison behind a port** | local, MIT, calibrated on child-inclusive corpus; replaceable |
| Brain | Claude API · Ollama only · Claude Agent SDK · Managed Agents | **Claude API (`claude-opus-5-5`, adaptive thinking, effort `medium`, structured outputs, `fallbacks: "default"`), Ollama `qwen3:8b` fallback, static phrases last** | tutoring quality for a child; text-only requests keep the red line; Managed Agents rejected because the loop and tools must stay on the LAN |
| Vision judge | Ollama qwen3-vl:8b (existing) | unchanged | — |

`claude-haiku-5-5` remains configurable for the habit track's one-line phrases (`BRAIN_MODEL_CHEAP`); the first track's choice of Haiku for cost is the owner's and is kept there.

## Amendments

ADR-0011 (2026-10-19) defers the Ollama Brain fallback and the qwen3-vl OCR second opinion out of v1 (ports kept), gates automatic pronunciation judgement behind an evaluation threshold, and records that the installed `anthropic` 0.120.2 exposes `output_config.format` but no `fallbacks` parameter, so fallback is application-owned (static phrases) and the SDK is pinned rather than upgraded for v1.

## Decision outcome

Each service is a package `leafi/services/<name>/` with a `Protocol`, a registry keyed by the `.env` backend name, one module per backend and `mock.py`. Backends load lazily; a missing model file reports a download command through `python -m leafi doctor`.

## Consequences

- Model downloads (~2–3 GB total: Parakeet int8, Kokoro, wav2vec2 ×2, RapidOCR) are a setup step, scripted by `doctor`.
- Two runtimes in the venv (torch for wav2vec2, onnxruntime for the rest); acceptable on this machine.
- If `anthropic` 0.120 lacks `fallbacks`/`output_config.format`, the SDK is upgraded to 1.x in its own ticket (tech-debt TD-1) before the brain ships.

## Confirmation

`python -m leafi doctor` lists every backend as `ok`, `missing model` or `disabled`; `tests/test_services_mock.py` runs the study loop with all mocks.
