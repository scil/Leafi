# Leafi

<!-- Every line here is non-inferable, costly when wrong, or a verification rule. Target < 4 KB. Growth: an agent fails twice → hook/test if enforceable → one line here with Instance: and date. -->

Household AI agent: hardware-agnostic core (`leafi/`), book-study track (`leafi/study/`), legacy habit track (`agent/`). Read `GLOSSARY.md` before naming anything.

## Boundaries

- MUST NOT send anything from `leafi/` to a cloud service except through `leafi.privacy.egress`, under the egress table and privacy settings of `docs/architecture/quality-attributes/security.md` (ADR-0018). The habit track (`agent/`) keeps ADR-0011; its one opt-in is the parent snapshot when the owner sets `NOTIFY_WITH_SNAPSHOT=true`. Enforced by: `tests/test_privacy.py`, `tests/test_netguard.py`.
- MUST NOT commit `.env`, `data/`, `cache/`, `models/`, `config/frigate/go2rtc_homekit.yml` (gitignored; keep it so). Enforced by: `.gitignore`.
- MUST NOT replace `tools/go2rtc/go2rtc.exe` with a stock build; read `tools/go2rtc/PATCHES.md` first. Enforced by: advisory.
- MUST NOT play audio on the camera speaker during tests or unasked (it is in a child's home); use `--mock` or `SPEAKER_BACKEND=local`. Enforced by: advisory.
- Vision-judge prompts MUST state that identity is not inferred (红线 01). Enforced by: `agent/tasks.py::validate`, `tests/test_tasks.py`.

## Commands

- Python: `.venv\Scripts\python` (3.12, created by `uv`; the venv has no `pip` — install with `uv pip install --python .venv <pkg>`). The system Python is 3.9: never use it.
- Tests: `.venv\Scripts\python -m pytest -q` (all green before commit). Hardware/model tests run only with `LEAFI_HW_TESTS=1`.
- Habit mock run: `.venv\Scripts\python -m agent.main --mock --now brush_pm`; task editor and `.env` settings page: `python -m agent.webui` → 127.0.0.1:8770.
- Study: `python -m leafi study --text --mock --book X --page-text <file> [--learner NAME]` needs no hardware and speaks nowhere; `python -m leafi doctor` lists models to download; `python -m leafi devices` prints the Hub.
- `data/leafi.db` below schema 6 refuses to open: `python -m leafi backup`, then `python -m leafi migrate` (only from schema 4: add `--learner` and the child's real first name in quotes; a placeholder such as `<name>` is refused) with every Leafi process stopped (ADR-0018 §7.2). Never run `migrate` on the owner's file unasked.
- Containers: `docker compose up -d`; host go2rtc: `scripts\win\go2rtc-host.bat`. MQTT host port is 18830, Frigate 15000, host go2rtc 2984 (Windows reserves the usual ports).

## Verification

- A change under `leafi/` or `agent/` MUST pass the full pytest suite before being reported done.
- A change to alignment, corrections or storage MUST add a regression test (`docs/engineering/testing.md` → never mocked).
- A design that adds a mechanism, a dependency or a data shape, or touches privacy, egress, concurrency or migrations, MUST be derived from research before it is written: `tiered-research` → `gather-code-references` (libraries and alternatives) → `derive-project-plan` (one provenance line per mechanism) → the ADR or plan. Wording or value changes skip this.
- A design change MUST be reviewed before code (`codex-review` skill): codex (`gpt-6-astra`), `code-plan-review` and a fresh Claude session on the same prompt file, run in parallel and independently, then compared, for the risky designs above; codex plus `code-plan-review` otherwise; one reviewer for an increment round. A change whose only risk is privacy needs no review before code (owner, 2026-10-24).
- A new Ear/Mouth device or pairing MUST be measured before a design relies on it, and again after firmware or go2rtc upgrades (`docs/hardware/README.md`).

## Architecture rules

- `leafi.core` imports nothing from `leafi.devices`, `leafi.services`, `leafi.study`; tracks never import adapters or backends directly (ADR-0002/0003). Enforced by: `tests/test_architecture.py`.
- Page text is read through `pages.current_text()`; corrections add revisions and invalidate with a reason, never delete (ADR-0010). Enforced by: `tests/test_corrections.py`.
- The reading algorithm (alignment, commitment, completion, practice, difficulties, CHECK outcomes) has one owner, ADR-0013; implement it from the pseudocode and never restate its rules elsewhere. `confirmed` needs acoustic evidence; ≤ 2 retries; skip always. Enforced by: `tests/test_alignment.py`, `tests/test_practice.py`.
- Zero mouths is valid: `hub.say()` returns with text shown on Faces; half-duplex listening gate; one speaker at a time (ADR-0002, ADR-0011). Enforced by: `tests/test_hub.py`.

## Conventions that differ from defaults

- Repository text, commits and docs are English; no attribution trailers in commits. Enforced by: advisory.
- Mermaid diagrams; short ADRs (Matt Pocock's format, ADR-0015) under `docs/adr/` with `status` frontmatter. Enforced by: review.

## Known traps

- go2rtc API source strings may not contain spaces; pad silence into the file in `tts.py`, not via `#raw=`. Instance: 2026-08-07.
- `.env` is reread only when the Frigate container is recreated (`scripts\win\apply-env.bat`). Instance: 2026-08.
- Xiaomi camera needs internet to fetch P2P keys per connection; do not firewall it. Instance: 2026-08-07.
- `anthropic` is 1.17 on `httpx2`, and `import leafi` / `import agent` alias `httpx` to `httpx2`: nothing may import `httpx` before them (RuntimeError), and a test that patches `httpx` sees SDK traffic only through the alias (TD-1). 2.x changes the API version; do not bump unasked.
- The Python install's `DLLs\sqlite3.dll` is hand-replaced (SQLite 3.54.1; stock 3.49.1 has the WAL-reset bug). `scoop update python312` reverts it and `leafi.db` silently leaves WAL; `leafi doctor` shows it; redo ADR-0019 §2. Instance: 2026-10-22.

## Pointers

- What to build and in what order: `docs/plans/active/2026-10-22-ai-led-study.md` (Progress first, then Decision Log); the earlier `2026-10-19-leafi-book-study.md` holds S0–S3 and the owner-present hardware steps.
- Why things are the way they are: `docs/adr/`; vocabulary: `GLOSSARY.md`; requirements and states: `docs/product.md`.
- Where a fact lives: `docs/ownership-map.md`. A symptom: search `docs/engineering/code-locator.md`, do not read it whole.
- Hardware bring-up and the human console: Obsidian vault `scil/Leafi/` (owner's); the console's buttons and cards live in `Leafi Console buttons · 控制台按钮.md`; each button's 动作 is a key of `scripts/win/run_for_obsidian_console.ps1`, the project's one console entry point (add a case there, never a Shell commands entry), and the console is verified with `node <ai-skills>/skills/obsidian-console/scripts/check-console.js <vault>/_views/console-grid/view.js "<data note>" <vault>/.obsidian/plugins/obsidian-shellcommands/data.json scripts/win/run_for_obsidian_console.ps1`.

## Agent skills

### Issue tracker

Local markdown under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `GLOSSARY.md` + `docs/adr/`. See `docs/agents/domain.md`.
