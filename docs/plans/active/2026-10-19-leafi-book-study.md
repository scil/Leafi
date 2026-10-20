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
    drain_s: float                                          # read once by the listening gate after play()
    async def play(self, clip: AudioClip) -> None: ...      # returns at estimated playback end
    async def stop(self) -> None: ...                       # cancel current playback
class Face(Protocol):
    async def show(self, msg: Display) -> None: ...        # Display(kind: say|status|listening|alert, text, lang)
class Listener(Protocol):
    async def next_utterance(self, timeout_s: float) -> Utterance | None: ...   # Utterance.audio_ref is None for typed input
    async def pause(self) -> None: ...                      # discard buffered audio
    async def resume(self, after_s: float = 0.0) -> None: ...
class Presence(Protocol):
    def subscribe(self, fn: Callable[[PresenceEvent], None]) -> Callable[[], None]: ...
class Notifier(Protocol):
    async def notify(self, title: str, body: str) -> None: ...   # text only (ADR-0011)
class Synthesizer(Protocol):                                # implemented by services/tts; injected into the Hub
    async def synth(self, text: str, lang: str, *, slow: bool = False) -> AudioClip: ...

class Hub:                                                  # constructed by leafi/app.py (composition root)
    def __init__(self, *, mouths, faces, eyes, listeners, notifiers, synthesizer, policy, primary_mouth): ...
    async def say(self, text: str, lang: str = "en", *, slow: bool = False) -> None: ...   # Faces first, then TTS → Mouths per policy, SAY_TIMEOUT_S, never raises for a device error
    async def stop_speaking(self) -> None: ...
    def listener(self) -> Listener: ...                     # the configured study.listener, else console
    def eye(self) -> Eye | None: ...                        # the configured study.eye
```

`leafi/app.py` reads `devices.yml`, expands `${VAR}`, asks `leafi.devices.registry` for adapter factories (a device with a missing option is disabled with a warning), builds services from the registries, composes voice Listeners (Ear + VAD + ASR) when an Ear and an ASR backend exist, and constructs the Hub. `python -m leafi devices` prints the result.

Acceptance: `python -m leafi devices` prints the parsed table; `say()` with 0/1/2 mouths; console device echoes.

### S1 — Study loop in text mode (B3, B5, B6, B7, B8, B9, B11)

Deliverables: `leafi/study/{books,pages,alignment,miscues,coach,session,knowledge,anki,review,corrections,lexicon,phrases}.py`, `leafi/services/{brain,tts}/` with `mock` + real backends (brain: Claude via official SDK; TTS: Kokoro + edge; both lazily imported), `python -m leafi study --text --book "<title>" --page-text <file>`.

Key behaviours (revised after codex review rounds 1–3; **ADR-0013 owns the reading algorithm**, ADR-0010 page revisions, ADR-0011 egress and v1 scope):
- `alignment.align(state: ReadingState, utterance: Utterance) -> (state, observations, events)` implemented exactly from ADR-0013's pseudocode (window, DP costs, acceptance rule with singleton accumulation, deleted-span rule, status updates, commit scan, `sentence_reached` events). Sentence completion, reposition, practice, interrupted-session resume, CHECK outcomes and the Difficulty formula are implemented from the same ADR's "Session rules" sections.
- Controls: spoken grammar for utterances ≤ 6 words while listening (`stop`, `skip`, `go back`, `next page`, `page N`, `I don't understand`, `what does X mean`, `the book says X not Y`); typed `/stop /skip /back N /page N /fix Y X /explain X /again /good`; a control that does not apply in the current state is a spoken no-op. Cancel during playback = console/Face only. Brain is not used for intent in v1; learner free text never leaves the LAN.
- Async Brain results carry `(session_id, page_revision_id, turn_id)`; skip/stop/state change/new sentence bumps `turn_id`; stale results are discarded.
- `--page-text <file> [--page N]` creates a fully verified `manual` revision (ADR-0010 §7).
- `agent/notify.py`: snapshot attachment gated by `NOTIFY_WITH_SNAPSHOT` (default false) + one test; `agent/speaker.py`: speech-lease check. These are the only changes to `agent/`.
- Immediate coach lines come from `study/phrases.py` (Coach voice, static, deny-list checked). The Brain is enrichment only (explain, questions, better line when in time), async, 12 s deadline, revision-guarded, strict schema + action allow-list; unavailable → skip without a Difficulty.
- Page identity and revisions per ADR-0010; corrections in one transaction; miscues invalidated with reason.
- Anki: deck `Leafi`, model `问答题`, tag `leafi-id::<uuid>` for dedupe, `anki_outbox`, learner-chosen ease (again/good); stateful fake AnkiConnect server in tests (lost-ack mode, parent edits).
- Speech lease `data/leafi.lock` held by the session; `agent/speaker.py` gains a 5-line check that logs instead of speaking while the lease is held (the only change to `agent/`).
- Storage per `data-model.md`; `export --session <id>` JSON (counts and items, no learner free text); `forget --session <id>`.

Acceptance script (`tests/test_study_text_mode.py`): a scripted console listener reads a fixture page with one substitution, one mid-sentence skip, a hesitation split across two utterances, a reread of three words, one correction utterance, one "what does X mean", a `/skip` during practice, answers one comprehension question (Brain mock), then `/stop`; assertions on observations and the persisted reading state, one candidate practised to `withdrawn(practice)` and one to `unsure(disagreed)` with `practices` rows `evidence=none`, one self-corrected candidate → `withdrawn(self_corrected)`, correction revision chain with edit map, span transform and cross-revision invalidation, knowledge items + encounters, Anki outbox through the fake (one lost ack deduped by tag; one `sent` review answer never replayed), summary counts including `tokens_unread`, lease released; plus `tests/test_alignment.py` walkthroughs (a)–(d) from ADR-0013.

### S2 — See the book (B1, B2)

Deliverables: `leafi/devices/go2rtc_camera.py` (Eye via `GET /api/frame.jpeg?src=&width=`, Mouth via the existing `POST /api/streams` push — port `agent/speaker.py` logic, keep its comments' facts), `leafi/services/ocr/{rapidocr,qwen_vl,mock}.py`, `leafi/study/page_tracker.py` (frame-diff settle → OCR → page number regex / fingerprint match → `pages` upsert), book identification (`zxing-cpp` barcode → Open Library lookup by ISBN text only; else cover OCR title; else ask), `python -m leafi study` (voice listener still optional).

Acceptance: fixture pages rendered with PIL are OCR'd to ≥ 98 % word accuracy by RapidOCR in a hardware-marked test; page tracker picks the right page among 5 fixtures; a correction on a fixture page changes `Page.text` and the lexicon.

### S3 — Hear the reader (B3 voice, B4)

Deliverables: `leafi/devices/local_pc.py` (Ear via `sounddevice`, Mouth via ffplay/sounddevice, Face console), optional `go2rtc_camera` Ear (ffmpeg pulls `rtsp://127.0.0.1:2554/<stream>` audio → 16 kHz PCM) gated by prototype P-2, `leafi/services/asr/{sherpa,mock}.py` with Silero VAD and Parakeet TDT v2 int8 (timestamps; hotwords if P-1 confirms), `leafi/services/pronunciation/{openpronounce,mock}.py`, Practice loop with slow TTS modelling and re-scoring, `doctor` downloads.

Acceptance: hardware-marked tests with Kokoro-synthesised fixture audio: a correct reading → every token committed, no candidates; one substituted word → a `substituted` observation and a candidate at that token; a practice retry that matches → `withdrawn (practice)`, one that disagrees twice → `unsure` (never `confirmed` while `PRON_AUTO_JUDGE` is off). End-to-audible local feedback ≤ 1.5 s on the PC speaker, ≤ 2.5 s on the camera (performance.md). These tests prove plumbing, not tutoring accuracy; the child-speech evaluation (P-4) is separate.

### Out of this plan (ADR-0011): S4 device breadth (ESP32/Wyoming/Tapo) and S5 habits-on-the-Hub get their own plans once the loop is proven with the v1 device set (console, PC, Xiaomi Eye+Mouth).

### Prototypes (decisive ones run before the slice that depends on them; P-1 may run during S1 since S1 does not need audio)

- P-1 (before S3, can start now): sherpa-onnx Parakeet TDT 0.6B v2 int8 via `OfflineRecognizer.from_transducer(model_type="nemo_transducer")`: token→word reconstruction, timing granularity, whether confidence exists (else `None`), behaviour on silence, and whether hotwords apply with `modified_beam_search`. Throwaway script `scripts/proto/p1_parakeet.py`; result recorded in Surprises.
- P-2 (before S3 camera Ear): ffmpeg pulls audio from the host go2rtc Xiaomi stream — codec, rate, latency; a child reading at ~1 m intelligible? Owner runs it (camera needed).
- P-3 (before S2 real OCR): RapidOCR PP-OCRv5 vs v6 on three desk captures (hands, curvature, glare, a spread) at `snapshot_width` 1920 and 2304; report reading order, missing lines and page-number detection separately from word accuracy. Owner takes the captures; Opus runs the comparison.
- P-4 (before enabling `PRON_AUTO_JUDGE`): OpenPronounce Windows smoke test offline (`LEAFI_NO_NETWORK=1`), then the parent-labelled child-speech evaluation (≥ 40 flagged words, false-correction rate ≤ 15 %).
- P-5 (before S3): Kokoro → prepared clip → camera end-to-audible latency and truncation for a word and a line (owner present; audible).
- P-6 (before S3): `sounddevice` capture lifecycle on this PC: device selection, 16 kHz resampling, overflow signalling, unplug/replug, pause/resume under model load.

## Concrete steps for the implementer (Opus)

1. Read `AGENTS.md`, `GLOSSARY.md`, ADR-0001…0007, `docs/architecture/overview.md`, `data-model.md`, `flows/reading-session.md`, this plan. Keep the `tdd` skill's loop: one seam, one failing test, minimal code.
2. S0 then S1 in full (text mode, mock/static speech, Brain mock + real Claude backend behind the registry, Anki outbox with the stateful fake, speech lease incl. the 5-line check in `agent/speaker.py`); S2's OCR service + page identity/revisions + page tracker with the mock OCR and PIL fixtures, plus the go2rtc Eye/Mouth adapter against a fake server; S3 only the service shells with mocks plus the `sounddevice` Ear skeleton (real ASR/pronunciation backends may be written but are hardware-marked). P-1 (Parakeet contract) may be run as a throwaway script if the model download is acceptable (~600 MB); record the result in Surprises.
3. Add `requirements-study.txt` (sherpa-onnx, kokoro-onnx, rapidocr, onnxruntime, openpronounce, sounddevice, zxing-cpp, rapidfuzz, numpy, websockets) and `requirements-dev.txt` (ruff); pin versions resolved on 2026-10-19 (research §1); do not install heavy packages into the venv unless a hardware test or P-1 is being run.
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
- [x] 2026-10-19 Rename to Leafi in README, CLAUDE/AGENTS, code strings, Frigate template, `.env.example`, `.env`, vault console (commit 8204ac1).
- [x] 2026-10-19 Codex design review round 1 (gpt-6-astra, reasoning high): `reviews/2026-10-19-codex-design-review-1.md`; resolved by ADR-0009/0010/0011 and the revised data model, flows, security, performance, testing docs.
- [x] 2026-10-19 Codex design review round 2: `reviews/2026-10-19-codex-design-review-2.md`; resolved by ADR-0012 and amendments to ADR-0004/0006/0009/0010/0011, data model, flows, security, config, this plan.
- [x] 2026-10-19 Codex design review round 3: `reviews/2026-10-19-codex-design-review-3.md`; the recurring class (interacting prose rules) resolved structurally by ADR-0013 (one algorithm, pseudocode) superseding ADR-0009/0012; F5–F8 and the two §1 leftovers fixed in ADR-0010 §6/§9, ADR-0011, data model, flows, reliability.
- [ ] Codex design review round 4 (confirming, narrow).
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
| 2026-10-19 | Alignment = observations + committed cursor; miscues are candidates until practice/acoustic evidence; ≤ 2 retries, skip always; text mode records no acoustic evidence | codex review A1/A2/D3/D4/G4 → ADR-0009 (supersedes 0007) |
| 2026-10-19 | Stable page ids, immutable revisions, located corrections, invalidation with reason, revision-guarded async results | codex review A3/A4/D2/B7 → ADR-0010 |
| 2026-10-19 | One egress table; study notifications text-only; habit snapshot = owner's open decision (TD-9); OpenPronounce offline; Ollama/VLM fallbacks deferred; `PRON_AUTO_JUDGE`, `ASR_HOTWORDS` off until evaluated; v1 = console + PC + Xiaomi Eye/Mouth; S4/S5 are future plans | codex review D1/G1/G3/C1–C4/E3 → ADR-0011 |
| 2026-10-19 | Composition root `leafi/app.py`; `Synthesizer` protocol in core; audio ownership on `Utterance.audio_ref`; half-duplex listening gate; speech lease between processes | codex review B1/B2/A5/B3/D5 → overview.md, device-routing.md |
| 2026-10-19 | Three latency budgets (ack 0.3 s, local feedback 1.5 s PC / 2.5 s camera, enrichment 6 s); Brain off the fast path | codex review A6 → performance.md |
| 2026-10-19 | `anthropic` pinned at 0.120.2 (has `output_config`, no `fallbacks`); application-owned fallback | codex review E7 → TD-1 |
| 2026-10-19 | Reading state across utterances; reconciliation withdraws candidates; reposition flow; sentence completion by cursor or pause; `confirmed` only with acoustic evidence; input routing by state; turn-scoped async guard; cancel during playback via console/Face | codex round 2 §3–4 → ADR-0012 |
| 2026-10-19 | Half-open code-point spans, tokenizer version, edit maps; corrections transform verified spans and reading state atomically; `forget --session` is the one sanctioned deletion | codex round 2 §2.10, §3.2 → ADR-0010 amendment |
| 2026-10-19 | Habit snapshot = owner opt-in `NOTIFY_WITH_SNAPSHOT` (default false); learner free text never leaves the LAN; comprehension judged locally; `REDACT_TERMS` via `leafi setup` | codex round 2 §2.1–2.2, §3.5 → ADR-0011 amendment |
| 2026-10-19 | Anki: `anki_item_key` + outbox replaces `anki_note_id`; review answers `pending→sent→acked`, never replayed; parent edits win via last-acked hashes | codex round 2 §2.8, §3.3–3.4 → ADR-0004 amendment |
| 2026-10-19 | Drain applied once by the listening gate; `play()` returns at estimated end; Brain deadline 12 s everywhere | codex round 2 §2.9 |
| 2026-10-19 | Review prompts are kept with the reports under `docs/plans/active/reviews/` for reruns | — |
| 2026-10-19 | Reading algorithm stated once as pseudocode (ADR-0013): acceptance rule with singleton-at-cursor accumulation; ties resolved toward advance (identical sentences read twice = progress; `/back N`); sentence completion by `sentence_reached`, pause/typed line end, or control; practice-before-CHECK; a matching retry withdraws in voice and text alike; interrupted sessions close candidates as `unsure(interrupted)` and offer resume; CHECK outcomes correct/incorrect/unavailable; one Difficulty formula; `forget --book` defined | codex round 3 F1–F8, §1 → ADR-0013, ADR-0010 §6/§9 |

## Outcomes & retrospective

(filled when the plan closes)
