# Performance budgets

Measured on the deployment PC (RTX 5070 Ti, Windows 11), one learner at one desk. Three budgets, because they are met by different mechanisms (codex review A6):

| Budget | Target | Mechanism | Measure |
|---|---|---|---|
| **Visible acknowledgement** — end of utterance → Face shows "heard: …" / listening indicator change | ≤ 300 ms | local; no model on the path except VAD end-pointing | `scripts/bench_turn.py`, p50/p95 |
| **Useful local feedback** — end of utterance → audible first word on the selected Mouth | ≤ 1.5 s on PC speaker; ≤ 2.5 s on the camera (its 0.9 s head pad is fixed cost) | ASR ≤ 0.6 s, static phrase or cached clip (≤ 50 ms), no Brain call | same, per output device, end-to-audible |
| **Generated enrichment** — explanation / question from the Brain | ≤ 6 s with a local filler line at 1.5 s; `unavailable` after 12 s | async, revision-guarded | same |

Component budgets behind them: ASR on a 10-word sentence (Parakeet int8, CPU) ≤ 0.6 s; TTS cache miss (Kokoro, CPU) ≤ 1.0 s to first audio (Picovoice's 2.9 s data point on a weaker CPU means this is to be measured, and lines are short); OCR one page (RapidOCR CPU) ≤ 3 s; page-turn settle ≤ 1 s; pronunciation score one word ≤ 1 s GPU / 3 s CPU (only in Practice, only when enabled).

Memory: ASR + TTS + OCR resident ≤ 4 GB RAM; wav2vec2 scorer loads on first use and is released after 10 min idle.

Timeouts that bound stalls: `say()` 20 s per call (hung Mouth cancelled), Brain 12 s overall deadline with at most 1 retry, OCR 15 s, ASR 10 s after VAD stop, Anki 10 s.

Prototype P-5 (before S3): Kokoro → prepared clip → camera, measuring audible start/end and truncation for a word and a full line.
