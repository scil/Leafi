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
- [x] 2026-10-19 Codex design review round 4: `reviews/2026-10-19-codex-design-review-4.md`; hand execution exposed a cost-ordering bug (insertion cheaper than substitution) and gaps in completion, `/back`, control precedence and CHECK; ADR-0013 revised with exact costs, boundaries, completion history, control precedence, candidate settlement and an exhaustive CHECK partition; ADR-0010 §6 scope fixed; glossary/data-model/flow aligned.
- [x] 2026-10-19 Codex design review round 5 (final): `reviews/2026-10-19-codex-design-review-5.md`; five remaining decisions recorded in ADR-0013 (cursor invariant at completion, `/back N` = current + N−1, page settlement on departure incl. during PRACTICE, PRACTICE → CHECK/READ by page completion, practice retry timer vs session idle) and in the data model (`not_practised`, difficulties text). Review loop closed at the five-round budget; any further finding is an implementation decision to be logged here.
- [x] 2026-10-20 00:15 S0 core skeleton (ports, Hub, devices.yml, storage schema v1, text, lease, no-network guard, console/notifier adapters, `leafi devices|doctor`) — commit 9e3000a.
- [x] 2026-10-20 00:40 ADR-0013 alignment + reading-state rules, walkthroughs (a)–(f) as tests — 0961ed7.
- [x] 2026-10-20 01:00 Page revisions, located corrections, lexicon, Difficulties — a21c749.
- [x] 2026-10-20 01:45 S1 text-mode loop: Brain (Claude/Ollama/mock), coach, controls, phrases, session state machine, Anki outbox + review answers, records (export/forget), `leafi study --text` — 1bfac6a.
- [x] 2026-10-20 02:00 The two `agent/` changes (`NOTIFY_WITH_SNAPSHOT`, speech-lease check) and the privacy tests (canary recorder, `LEAFI_NO_NETWORK=1` subprocess runs) — 5986698, c2fe701.
- [x] 2026-10-20 02:30 S2 partial (OCR mock + RapidOCR, page tracker, book identification, catalog, go2rtc Eye/Mouth vs a fake go2rtc server) and S3 shells (ASR/VoiceListener, pronunciation, local PC) — 81a2d6f, b96c9c4.
- [x] 2026-10-20 02:50 Tests green: 62 → 218 passed, 3 hardware-marked skipped; ruff clean on `leafi/` and new tests; docs updated.
- [ ] Hardware steps on the PC: P-1, P-2, P-3, P-4, P-5, P-6; install `requirements-study.txt`; run `LEAFI_HW_TESTS=1`; S2/S3 real backends (OpenPronounce wiring, Silero VAD, camera Ear); acceptance 1 with the camera.
- [ ] codex-review loop on the implementation diff (`-c model="gpt-6-astra"`), plan step 5.

## Surprises & discoveries

- The venv was created by `uv` and has no `pip`; `python -m pip` prints nothing. Use `uv pip install --python .venv`.
- Ollama is installed via scoop but not running and no model is pulled; the vision judge and the local brain fallback are not yet usable on this machine.
- codex-cli 0.155.0 accepts `gpt-6-astra` although the `codex-review` skill says it is rejected (TD-6).
- AnkiConnect is reachable and the profile already has decks `En`, `En2`, `Phrases` and the `问答题` note type the shared skill uses.
- PaddlePaddle GPU on Windows + RTX 50-series needs a special CUDA 12.9 wheel → ONNX path chosen.
- The old repository path `Carema-Kis-AI` still appears in `.env`'s `SPEAKER_SRC_DIR` and in the vault console's `file:///` links; both are fixed in the rename step.
- 2026-10-20 `anthropic` 0.120.2 confirmed by inspection: `AsyncMessages.create` has `output_config` (`effort`, `format` = `{type: json_schema, schema}`) and `thinking`, no `fallbacks`. The Claude backend sends `output_config.format` and also parses JSON-in-text with local strict validation.
- 2026-10-20 `rapidfuzz` was not in the venv (ADR-0013 `sim` needs it); installed 3.14.6, plus `ruff` 0.17.1.
- 2026-10-20 With ADR-0013 costs a six-token line skip preceded by four read words in the same utterance is beaten by jumping ahead and substituting (4 × 1.0 + jump 0.6 = 4.6 < 6 × 0.8 = 4.8), and a word repeated inside the skipped line (e.g. "the") ties with the skip path and wins the lexicographic tie-break (one `deleted` candidate + a five-token skip). Walkthrough (f) holds with ≥ 5 words before the skip and no repeated word. Candidate for an ADR-0013 revision once real reading shows it.
- 2026-10-20 `/back 1` right after a sentence completes (also during its PRACTICE) reopens the *next* sentence: completion has already moved `pcur` into it, and ADR-0013 defines `cur` as the sentence containing `pcur`. `/back 2` reopens the one just read. Implemented literally; UX question for the owner. **Resolved 2026-10-20:** ADR-0013 now takes `cur` from `pcur − 1` at a sentence start or at `n`; `alignment.back` implements it and `/back 1` reopens the sentence just read (tests in `test_alignment.py`, `test_session_controls.py`).
- 2026-10-20 The 0.80 fuzzy threshold matches many OCR/ASR near-misses (`though`/`through`, `smell`/`small`, `though`/`thorough`), so such words never become candidates; a misread like that is caught by the correction flow, not by Practice.
- 2026-10-20 `.env` on this PC sets `BRAIN_MODEL=claude-haiku-4-5` for the habit track; config.md gives the study Brain the same name (default `claude-opus-5-5`), so on this machine the study Brain would run Haiku 4.5 until the owner changes `.env` or T2 splits the names. Not changed (agent/ change budget); the Claude backend sends no `effort`/`thinking` so either model works. **Resolved 2026-10-20:** the study track reads `STUDY_BRAIN_MODEL` (default `claude-opus-5-5`); `BRAIN_MODEL` is the habit track's only.
- 2026-10-20 `stop` / page turn with `pcur` at the start of an unread sentence completes that sentence by (iii), so all its tokens count as `unread` in the summary (literal ADR-0013).
- 2026-10-20 Windows: `os.kill(pid, 0)` would terminate the process; the lease's liveness check uses `OpenProcess` + `GetExitCodeProcess`.
- 2026-10-20 PowerShell `Add-Content`/`Set-Content` and Python `Path.write_text` write CRLF on this machine; files were normalised to LF before commit.

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
| 2026-10-19 | Round 5 decisions: completion sets `pcur = max(pcur, ccur)`; `/back N` reopens the current sentence and N−1 before; page settlement on stop/next page/page turn settles every open candidate (also mid-PRACTICE); after PRACTICE → CHECK if all sentences completed else READ; `PRACTICE_RETRY_S` 10 s per retry, `STUDY_IDLE_S` only in READ/CHECK/REVIEW_DUE; `unsure_reason` gains `not_practised`; difficulties: once a row exists every session contributes | codex round 5 |
| 2026-10-19 | ADR-0013 revised after round 4: insert 1.2 > substitute 1.0 so terminal substitutions become candidates; boundary penalty 0.5 keeps stray trailing words out of the next sentence; unique tie-break; internal gaps > 3 = `line_skipped` (unread, no candidates); candidates stay attempted at completion; `completed` set prevents duplicate events; `/back N` defined; control precedence (stop > page > back > skip) with candidate settlement; self_corrected = next utterance, else reread; corrections invalidate candidate/unsure/confirmed only; knowledge-item difficulties formula; exhaustive CHECK partition | codex round 4 |
| 2026-10-19 | Reading algorithm stated once as pseudocode (ADR-0013): acceptance rule with singleton-at-cursor accumulation; ties resolved toward advance (identical sentences read twice = progress; `/back N`); sentence completion by `sentence_reached`, pause/typed line end, or control; practice-before-CHECK; a matching retry withdraws in voice and text alike; interrupted sessions close candidates as `unsure(interrupted)` and offer resume; CHECK outcomes correct/incorrect/unavailable; one Difficulty formula; `forget --book` defined | codex round 3 F1–F8, §1 → ADR-0013, ADR-0010 §6/§9 |
| 2026-10-20 | Test seams (tdd skill; recorded instead of asked): `alignment.align` + the pure state rules; `Hub.say` / `ListeningGate`; `StudySession.run` with a scripted listener; storage-backed modules on temp SQLite; adapters against fakes (fake go2rtc HTTP server, stateful AnkiConnect transport) | plan "Concrete steps"; testing.md layers |
| 2026-10-20 | DP costs are integers ×10; tie-break operation order match < fuzzy < substitute < delete < insert, and ending the path sorts before any further operation | makes "lexicographically earliest" exact; ADR-0013 names no operation order |
| 2026-10-20 | "Aligned token" (jump, boundary, run) = match, fuzzy or substitute; a sentence is "entered" when it holds ≥ 1 aligned token; a run needs adjacent tokens with no insertion between; page-wide alignment uses run ≥ 3 and no singleton rule | simplest reading of ADR-0013 steps 2–3 consistent with walkthroughs (a)–(f) |
| 2026-10-20 | Utterance `seq` counts every reading utterance of the page read, unanchored ones included; `self_corrected` = created by `seq − 1` | "the utterance immediately after" taken literally |
| 2026-10-20 | `line_skipped` makes only unattempted/provisional tokens `unread` (committed, settled, candidate unchanged) | never regress settled reading |
| 2026-10-20 | Practice retry test compares the whole normalised retry (`" ".join(norm(w))`) with `norm(expected)` | ADR-0013 says `norm(retry)` |
| 2026-10-20 | ~~A spoken control phrase that equals the expected text within `pcur − 2 … pcur + 2` is reading, not a command~~ **Reversed by codex implementation review 1 #10:** control precedence wins everywhere ("skip always"); a spoken utterance longer than 6 words is never a control (the grammar's own limit, now applied to "the book says X not Y" too) | testing.md line read as "a page sentence (longer than the grammar) containing stop is read" |
| 2026-10-20 | `study --text` forces voice policy `none` unless `--voice-policy`; `--mock` = console-only devices, mock TTS/Brain, no Anki | never speak on the camera from a typed session (AGENTS.md) |
| 2026-10-20 | An explanation target is kept only if it occurs on the page; otherwise the current sentence is explained and the knowledge key is that sentence | learner free text never leaves the LAN or becomes a card |
| 2026-10-20 | Correction locate: nearest whole-word occurrence inside the reread window, then once page-wide (the "retry once"), else an unlocated `corrections` row (`char_start` null); no "Do you mean…?" question in v1 | flows/reading-session.md B5 steps 1–2, simplest form |
| 2026-10-20 | After a correction the same `page_reads` row continues on r+1 (`page_revision_id` and state updated in the correction transaction); miscues keep their own revision | ADR-0013 re-tokenises the active ReadingState |
| 2026-10-20 | Schema additions: `utterances.session_id`, utterance kinds `practice` and `answer`, `observations.sim`, `encounters.example` | forget --session must find CHECK/REVIEW answers; card back needs the example |
| 2026-10-20 | Page identity: a new page when the best observation score < 0.75; confident ≥ 0.9; two candidates within 0.05 → uncertain | count terms alone give unrelated pages ≈ 0.3 |
| 2026-10-20 | OCR revision merge = character-level `difflib` opcodes; any opcode touching a verified span keeps the old text | "a later OCR never overwrites verified spans" |
| 2026-10-20 | `page_reads` counts: committed = committed + settled, matched = committed, unread = unread | data-model names the columns only |
| 2026-10-20 | Anki: the outbox stops at the first transport failure and stays `pending`; explicit AnkiConnect errors retry up to 5 attempts, then `failed`; deck created before the first add; review turn ≤ 5 cards (`REVIEW_MAX_CARDS`); spoken/typed `good`/`again` | ADR-0004 amendment; Anki closed is the common case |
| 2026-10-20 | CHECK `incorrect` writes a `fact` knowledge item keyed by the Brain's `item_key` (the page's spelling when found); CHECK window = last 3 completed sentences | ADR-0013 → CHECK outcomes; ≤ 3-sentence payload |
| 2026-10-20 | `confirmed` only when `PRON_AUTO_JUDGE` is on, the scorer ran on both disagreeing retries, and score < 0.5; a matching retry still withdraws | ADR-0013 → Practice ("the scorer may set confirmed") |
| 2026-10-20 | SQLite calls stay synchronous on the event loop; ruff `ASYNC240` ignored | small local writes; models still go through executors |
| 2026-10-20 | Claude backend sends `output_config.format` json_schema and no `effort`/`thinking` (Opus 5.5 runs adaptive at default effort medium); one retry inside the 12 s deadline; refusal/invalid → unavailable | ADR-0003/0011; works with any `BRAIN_MODEL` |
| 2026-10-20 | `BOOK_LOOKUP` defaults to `off`; `devices.yml` gains `${VAR:-default}` for optional variables | privacy-first default; notifier options are optional |
| 2026-10-20 | Fixture pages are rendered by PIL at test time with ground truth in PNG text chunks that the mock OCR reads | no binary fixtures; deterministic OCR in CI |
| 2026-10-20 | `leafi/runner.py` (not `study/`) builds the session, because it uses the composition root | architecture rule 2 (tracks never import `leafi.app`) |
| 2026-10-20 | Speech lease: wall-clock expiry 60 s (`LEASE_TTL_S`), renewed every 20 s; stale or dead-pid leases are taken over | device-routing.md "pid + expiry" |
| 2026-10-20 | Study-track env names added: `BRAIN_BACKEND`, `TTS_VOICE_ZH_EDGE`, `TTS_VOICE_EN_EDGE`, `SENTENCE_PAUSE_S`, `REVIEW_KNOWN_INTERVAL_DAYS`, `REVIEW_MAX_CARDS`, `LEASE_TTL_S`, `DATA_DIR`, `CACHE_DIR`, `MODELS_DIR`, `DEVICES_FILE`, `BOOK_LOOKUP` (config.md) | defaults in `leafi/core/config.py` |
| 2026-10-20 | Study Brain model is `STUDY_BRAIN_MODEL` (default `claude-opus-5-5`); `BRAIN_MODEL` stays the habit track's; `BRAIN_MODEL_CHEAP` unchanged | the shared name made the study Brain run the habit's Haiku 4.5 on this PC; no `agent/` change needed |
| 2026-10-20 | Deviations in this run: review logic lives in `study/anki.py` (Anki calls) + `StudySession.review_due` (the turn) instead of `study/review.py`; no `services/vision/` (the habit track keeps its own); no `frigate_presence` adapter and no `whisper` ASR backend; `doctor --download` prints the commands only; the fake AnkiConnect is a stateful httpx transport, the fake go2rtc a real loopback server; P-1 not run (no model download) | out of this run's scope or smallest working form; each is a follow-up, none changes an ADR |

## Outcomes & retrospective

(filled when the plan closes)
