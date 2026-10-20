# Performance budgets

Measured on the deployment PC (RTX 5070 Ti, Windows 11). Budgets are for one learner at one desk.

| Step | Budget | Rationale | Where measured |
|---|---|---|---|
| End of utterance → first spoken feedback | ≤ 1.5 s | a 10-year-old stops attending after ~2 s of silence | `scripts/bench_turn.py` (to write) |
| ASR on a 10-word sentence (Parakeet int8, CPU) | ≤ 0.6 s | fits the turn budget with TTS | same |
| TTS first audio (Kokoro, cached miss) | ≤ 1.0 s; cache hit ≤ 50 ms | Picovoice data point ≈ 2.9 s on a weaker CPU; GPU EP or shorter lines if missed | same |
| OCR of one page (RapidOCR, CPU) | ≤ 3 s | page turn is a natural pause | `scripts/bench_ocr.py` (to write) |
| Page-turn detection (frame diff) | ≤ 1 s after the page settles | — | same |
| Pronunciation score of one word | ≤ 1 s (GPU) | only on flagged words | — |
| Memory | ASR + TTS + OCR resident ≤ 4 GB RAM; vision judge loads on demand and unloads after 10 min idle (`keep_alive`) | leave VRAM for Frigate/TensorRT later | — |

Profiling: `python -m leafi doctor --bench` runs the two bench scripts and prints a table; results are appended to `docs/plans/active/<plan>.md` → Progress when they change a decision.
