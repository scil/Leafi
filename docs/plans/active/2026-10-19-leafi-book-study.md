# Plan: Leafi — hardware-agnostic core and the book-study track

Living document (ExecPlan shape). Progress, Surprises & Discoveries, Decision Log and Outcomes & Retrospective are mandatory and are updated at every stopping point.

## Purpose / big picture

Turn Carema-Kis-AI into Leafi: a household agent whose core does not care which camera, speaker, microphone or screen exists, and whose first new track helps a 10-year-old study physical English books with the Xiaomi camera already on the desk. Acceptance (owner's words, 2026-10-19):

1. With the Xiaomi camera, help the learner read a physical book: words read wrong get help; words the camera misread accept the learner's correction; things not understood get explained; review happens; books, pages, difficulties and new knowledge are stored.
2. Clear documentation, maintained with the `docs-maintainer` skill.

## Context and orientation

- Repo facts, prior art and the decision pool: `docs/research/2026-10-19-prior-art-book-study.md`.
- Architecture: `docs/architecture/overview.md`; decisions ADR-0001…0008; vocabulary `GLOSSARY.md`; requirements `docs/product.md`.
- The habit track (`agent/`) keeps working untouched except for the rename.
- Work order required by the owner: research → design → install skills → codex (latest model) reviews the design → Opus implements → tests → docs.

## Plan of work (vertical slices)

Each slice ends green with tests and a runnable command. Ticket files live under `.scratch/leafi-book-study/issues/` when a slice is started.

### S0 — Core skeleton and the typed-text device (no hardware)

Deliverables: `leafi/core/{ports,hub,config,storage,text}.py`, `leafi/devices/{console,notifiers}.py`, `config/devices.yml`, `python -m leafi devices|doctor`, `tests/test_hub.py`, `tests/test_architecture.py`, `tests/test_storage.py`.

Port sketch (Python 3.12, `typing.Protocol`, all async):

```python
class Eye(Protocol):
    async def snapshot(self, max_width: int | None = None) -> Frame | None: ...
class Ear(Protocol):
    def listen(self) -> AsyncIterator[AudioChunk]: ...      # 16 kHz mono int16
class Mouth(Protocol):
    async def play(self, clip: AudioClip) -> None: ...
class Face(Protocol):
    async def show(self, msg: Display) -> None: ...        # Display(kind: say|status|listening|alert, text, lang)
class Listener(Protocol):
    async def next_utterance(self, timeout_s: float) -> Utterance | None: ...
class Presence(Protocol): ...
class Notifier(Protocol):
    async def notify(self, title: str, body: str, frame: bytes | None = None) -> None: ...

class Hub:
    @classmethod
    def from_yaml(cls, path, settings) -> "Hub": ...        # disables devices with missing options, never raises for them
    mouths: list[Mouth]; faces: list[Face]; eyes: list[Eye]; listeners: list[Listener]; notifiers: list[Notifier]
    async def say(self, text: str, lang: str = "en", *, slow: bool = False) -> None: ...   # Faces first, then TTS → Mouths per policy, timeout
    def listener(self) -> Listener: ...                     # voice listener if an Ear + ASR exist, else console
```

Acceptance: `python -m leafi devices` prints the parsed table; `say()` with 0/1/2 mouths; console device echoes.

### S1 — Study loop in text mode (B3, B5, B6, B7, B8, B9, B11)

Deliverables: `leafi/study/{books,pages,alignment,miscues,coach,session,knowledge,anki,review,corrections,lexicon,phrases}.py`, `leafi/services/{brain,tts}/` with `mock` + real backends (brain: Claude via official SDK; TTS: Kokoro + edge; both lazily imported), `python -m leafi study --text --book "<title>" --page-text <file>`.

Key behaviours:
- `alignment.align(expected: list[str], utterance: Utterance, *, unsure_below=0.5) -> AlignResult(verdicts, cursor_advance)` per ADR-0007.
- Intent classification for learner Utterances: `read` (default), `correct_page_text`, `explain`, `stop`, `next_page`, `repeat` — rule-based first (`"the book says X not Y"`, `"what does X mean"`, `"I don't understand"`), Brain only when rules fail.
- Coach turns use structured output `{line, action, words_to_practice, question?}`; Chinese appears only inside explanations (`meaning_zh`) and never in the spoken English practice.
- Static phrases (`study/phrases.py`) in the Coach voice for every coach action, used when the Brain is unavailable.
- Anki: deck `Leafi`, model `问答题`, English-first bilingual fields; fake AnkiConnect server in tests.
- Storage per `data-model.md`; `export --session <id>` JSON.

Acceptance script (`tests/test_study_text_mode.py`): a scripted console listener reads a fixture page with one substitution, one skip, one correction utterance, one "what does X mean", answers one comprehension question; assertions on miscues, correction precedence, knowledge items, Anki push through the fake, summary content.

### S2 — See the book (B1, B2)

Deliverables: `leafi/devices/go2rtc_camera.py` (Eye via `GET /api/frame.jpeg?src=&width=`, Mouth via the existing `POST /api/streams` push — port `agent/speaker.py` logic, keep its comments' facts), `leafi/services/ocr/{rapidocr,qwen_vl,mock}.py`, `leafi/study/page_tracker.py` (frame-diff settle → OCR → page number regex / fingerprint match → `pages` upsert), book identification (`zxing-cpp` barcode → Open Library lookup by ISBN text only; else cover OCR title; else ask), `python -m leafi study` (voice listener still optional).

Acceptance: fixture pages rendered with PIL are OCR'd to ≥ 98 % word accuracy by RapidOCR in a hardware-marked test; page tracker picks the right page among 5 fixtures; a correction on a fixture page changes `Page.text` and the lexicon.

### S3 — Hear the reader (B3 voice, B4)

Deliverables: `leafi/devices/local_pc.py` (Ear via `sounddevice`, Mouth via ffplay/sounddevice, Face console), optional `go2rtc_camera` Ear (ffmpeg pulls `rtsp://127.0.0.1:2554/<stream>` audio → 16 kHz PCM) gated by prototype P-2, `leafi/services/asr/{sherpa,mock}.py` with Silero VAD and Parakeet TDT v2 int8 (timestamps; hotwords if P-1 confirms), `leafi/services/pronunciation/{openpronounce,mock}.py`, Practice loop with slow TTS modelling and re-scoring, `doctor` downloads.

Acceptance: hardware-marked tests with Kokoro-synthesised fixture audio: correct reading → all `read`; one substituted word → that word `mispronounced`; practice retry resolves it. Turn latency bench ≤ 1.5 s on the PC.

### S4 — Device breadth (H5)

xiaozhi WebSocket server adapter (Ear/Mouth/Face with subtitles), Wyoming client, Tapo camera profile. Acceptance per ADR-0008.

### S5 — Habits on the Hub (T2)

Move `agent/speaker.py`, `notify.py`, `presence.py` behind Hub ports; one config; one SQLite. Acceptance: existing 58+ habit tests still green; `--mock --now brush_pm` runs through the Hub.

### Prototypes (answer before the slice that depends on them)

- P-1 (before S3): sherpa-onnx Parakeet via `OfflineRecognizer.from_transducer(model_type="nemo_transducer")` — do `result.timestamps`/`tokens` exist and do hotwords apply? Throwaway script under `scripts/proto/`.
- P-2 (before S3 camera Ear): can ffmpeg pull audio from the host go2rtc Xiaomi stream, at what codec/rate, and is a child reading at ~1 m intelligible?
- P-3 (before S2): RapidOCR PP-OCRv5 vs v6 vs qwen3-vl on three photos of the current book taken through the camera at `snapshot_width` 1920 and 2304.

## Concrete steps for the implementer (Opus)

1. Read `AGENTS.md`, `GLOSSARY.md`, ADR-0001…0007, `docs/architecture/overview.md`, `data-model.md`, `flows/reading-session.md`, this plan. Keep the `tdd` skill's loop: one seam, one failing test, minimal code.
2. S0 then S1 in full; S2's OCR service + page tracker with the mock and the PIL fixtures; S3 only the service shells with mocks plus the `sounddevice` Ear (real ASR/pronunciation backends may be written but are hardware-marked).
3. Add `requirements-study.txt` (sherpa-onnx, kokoro-onnx, rapidocr, onnxruntime, openpronounce, sounddevice, zxing-cpp, rapidfuzz, websockets, numpy) and `requirements-dev.txt` (ruff); do not install heavy packages into the venv unless a hardware test is being run.
4. Update `README.md` run instructions, `docs/engineering/repo-map.md` (remove *planned* marks), `docs/engineering/code-locator.md` entries that now have files, and the Progress section here.
5. Run `.venv\Scripts\python -m pytest -q`; everything green; then `codex-review` loop on the diff (`-c model="gpt-6-astra"`, read-only sandbox).

## Validation and acceptance

- `pytest -q` green, including the existing habit tests.
- `python -m leafi study --text --book "Fixture" --page-text tests/fixtures/pages/p1.txt` runs the scripted scenario interactively.
- `python -m leafi doctor` reports each backend as ok / missing model / disabled, with download commands.
- Owner's acceptance 1 is reachable once S2 + S3 hardware steps are done on the PC with the camera; this plan's software part is accepted when the text-mode scenario and the fixture-image OCR tests pass.

## Idempotence and recovery

Re-running any slice is safe: storage migrations are versioned; model downloads are skipped when present; `.scratch/` tickets record state. A failed session is closed on next start.

## Progress

- [x] 2026-10-19 Survey of repo, Obsidian notes, shared skills; uncommitted diff reviewed (prompt-guard work in `agent/tasks.py`, kept).
- [x] 2026-10-19 Research corpus written (`docs/research/…`); refresh gate of `docs-maintainer` run (10 sources changed; no rule change affecting this repo; TD-7).
- [x] 2026-10-19 Skills audit: `mattpocock-skills@claude-plugins-official` 1.3.1 installed and contains every skill in the upstream repo; `docs/agents/*` written by hand per `setup-matt-pocock-skills` (local tracker, single context). Shared skills to junction: `docs-maintainer`, `codex-review`, `code-plan-review`, `anki-cards`, `tiered-research`.
- [x] 2026-10-19 Docs set written (product, glossary, architecture, ADR-0001…0008, engineering, ownership map, this plan).
- [ ] Rename to Leafi in README, CLAUDE/AGENTS, code strings, Frigate template, `.env.example`, vault console.
- [ ] Codex design review (gpt-6-astra) and fixes.
- [ ] Opus implements S0, S1, S2 (mock + fixtures), S3 shells.
- [ ] Tests green; commit; docs updated after change.
- [ ] Hardware steps on the PC: P-1, P-2, P-3; S2/S3 real backends; acceptance 1 with the camera.

## Surprises & discoveries

- The venv was created by `uv` and has no `pip`; `python -m pip` prints nothing. Use `uv pip install --python .venv`.
- Ollama is installed via scoop but not running and no model is pulled; the vision judge and the local brain fallback are not yet usable on this machine.
- codex-cli 0.155.0 accepts `gpt-6-astra` although the `codex-review` skill says it is rejected (TD-6).
- AnkiConnect is reachable and the profile already has decks `En`, `En2`, `Phrases` and the `问答题` note type the shared skill uses.
- PaddlePaddle GPU on Windows + RTX 50-series needs a special CUDA 12.9 wheel → ONNX path chosen.
- The old repository path `Carema-Kis-AI` still appears in `.env`'s `SPEAKER_SRC_DIR` and in the vault console's `file:///` links; both are fixed in the rename step.

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-10-19 | New package `leafi/` with tracks; `agent/` kept until S5 | ADR-0001 |
| 2026-10-19 | Capability ports + Hub + voice policy | ADR-0002; user requirement for 0–N mouths |
| 2026-10-19 | Default backends: sherpa-onnx Parakeet, Kokoro, RapidOCR + qwen3-vl, OpenPronounce-style, Claude Opus 5.5 + Ollama | ADR-0003; research §2 |
| 2026-10-19 | SQLite system of record; Anki schedules | ADR-0004 |
| 2026-10-19 | Docs in repo `docs/`, Mermaid, MADR under `docs/adr/` | ADR-0005 |
| 2026-10-19 | Improvement = data loops | ADR-0006 |
| 2026-10-19 | Alignment-based verification | ADR-0007 |
| 2026-10-19 | Local markdown issue tracker for Matt Pocock's skills | solo project; no external side effects |
| 2026-10-19 | Reply language in this repo: English only | owner instruction (token saving); recorded in CLAUDE.md |

## Outcomes & retrospective

(filled when the plan closes)
