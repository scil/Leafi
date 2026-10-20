# Leafi

<!-- Every line here is non-inferable, costly when wrong, or a verification rule. Target < 4 KB. Growth: an agent fails twice → hook/test if enforceable → one line here with Instance: and date. -->

Household AI agent: hardware-agnostic core (`leafi/`), book-study track (`leafi/study/`), legacy habit track (`agent/`). Read `GLOSSARY.md` before naming anything.

## Boundaries

- MUST NOT send images, audio, face labels, the learner's name or the learner's own words to any cloud service; every outbound call is in the egress table of `docs/architecture/quality-attributes/security.md` (ADR-0011), text only. The one opt-in: the habit track's parent snapshot when the owner sets `NOTIFY_WITH_SNAPSHOT=true`. Enforced by: `tests/test_privacy.py` (canary recorder + no-network run).
- MUST NOT commit `.env`, `data/`, `cache/`, `models/`, `config/frigate/go2rtc_homekit.yml` (gitignored; keep it so). Enforced by: `.gitignore`.
- MUST NOT replace `tools/go2rtc/go2rtc.exe` with a stock build; read `tools/go2rtc/PATCHES.md` first. Enforced by: advisory.
- MUST NOT play audio on the camera speaker during tests or unasked (it is in a child's home); use `--mock` or `SPEAKER_BACKEND=local`. Enforced by: advisory.
- Vision-judge prompts MUST state that identity is not inferred (红线 01). Enforced by: `agent/tasks.py::validate`, `tests/test_tasks.py`.

## Commands

- Python: `.venv\Scripts\python` (3.12, created by `uv`; the venv has no `pip` — install with `uv pip install --python .venv <pkg>`). The system Python is 3.9: never use it.
- Tests: `.venv\Scripts\python -m pytest -q` (all green before commit). Hardware/model tests run only with `LEAFI_HW_TESTS=1`.
- Habit mock run: `.venv\Scripts\python -m agent.main --mock --now brush_pm`; task editor: `python -m agent.webui` → 127.0.0.1:8770.
- Study (planned): `python -m leafi study --text` needs no hardware; `python -m leafi doctor` lists models to download.
- Containers: `docker compose up -d`; host go2rtc: `scripts\win\go2rtc-host.bat`. MQTT host port is 18830, Frigate 15000, host go2rtc 2984 (Windows reserves the usual ports).

## Verification

- A change under `leafi/` or `agent/` MUST pass the full pytest suite before being reported done.
- A change to alignment, corrections or storage MUST add a regression test (`docs/engineering/testing.md` → never mocked).
- A design change MUST be reviewed by codex before code (`codex-review` skill; `-c model="gpt-6-astra"` is accepted as of 2026-10-19).

## Architecture rules

- `leafi.core` imports nothing from `leafi.devices`, `leafi.services`, `leafi.study`; tracks never import adapters or backends directly (ADR-0002/0003). Enforced by: `tests/test_architecture.py`.
- Page text is read through `pages.current_text()`; corrections add revisions and invalidate with a reason, never delete (ADR-0010). Enforced by: `tests/test_corrections.py`.
- The reading algorithm (alignment, commitment, completion, practice, difficulties, CHECK outcomes) has one owner, ADR-0013; implement it from the pseudocode and never restate its rules elsewhere. `confirmed` needs acoustic evidence; ≤ 2 retries; skip always. Enforced by: `tests/test_alignment.py`, `tests/test_practice.py`.
- Zero mouths is valid: `hub.say()` returns with text shown on Faces; half-duplex listening gate; one speaker at a time (ADR-0002, ADR-0011). Enforced by: `tests/test_hub.py`.

## Conventions that differ from defaults

- Repository text, commits and docs are English; no attribution trailers in commits. Enforced by: advisory.
- Mermaid diagrams, MADR ADRs under `docs/adr/` with `status` frontmatter. Enforced by: review.

## Known traps

- go2rtc API source strings may not contain spaces; pad silence into the file in `tts.py`, not via `#raw=`. Instance: 2026-08-07.
- `.env` is reread only when the Frigate container is recreated (`scripts\win\apply-env.bat`). Instance: 2026-08.
- Xiaomi camera needs internet to fetch P2P keys per connection; do not firewall it. Instance: 2026-08-07.
- The `anthropic` package here is 0.120 (pre-1.x); check `fallbacks` / `output_config.format` support before using them (TD-1).

## Pointers

- What to build and in what order: `docs/plans/active/2026-10-19-leafi-book-study.md` (Progress first, then Decision Log).
- Why things are the way they are: `docs/adr/`; vocabulary: `GLOSSARY.md`; requirements and states: `docs/product.md`.
- Where a fact lives: `docs/ownership-map.md`. A symptom: search `docs/engineering/code-locator.md`, do not read it whole.
- Prior-art evidence for the stack: `docs/research/2026-10-19-prior-art-book-study.md`.
- Hardware bring-up and the human console: Obsidian vault `scil/Leafi/` (owner's), buttons call `scripts/win/*`.

## Agent skills

### Issue tracker

Local markdown under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `GLOSSARY.md` + `docs/adr/`. See `docs/agents/domain.md`.
