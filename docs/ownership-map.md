# Ownership map

One row per fact type → owner → layer → enforced by → reading rule. Nodes of the docs-maintainer structure with no owner are recorded as skipped.

| Fact / change type | Owner | Layer | Enforced by | Reading rule / notes |
|---|---|---|---|---|
| Boundaries, non-obvious commands, verification, architecture rules, traps, pointers | `AGENTS.md` (+ `CLAUDE.md` = `@AGENTS.md`) | 0 | size check (< 4 KB) in review; `tests/test_architecture.py` for the import rules it states | per `ai-agents-md`; no overview, no skill list |
| Work in progress, decisions, surprises, retrospective | `docs/plans/active/<date>-<slug>.md` → `completed/` | 1 | plan has the four required sections | the work record for this change |
| Known technical debt | `docs/plans/tech-debt.md` | 1 | reviewed at each plan close | item · owner · grade · trigger |
| Goals, users, principles, requirements with state, non-goals | `docs/product.md` | 2 | requirement ids referenced by tests (`B3` …) | decision states Candidate/Proposed/Accepted/Implemented |
| Vocabulary | `GLOSSARY.md` | 2 | Matt Pocock `domain-modeling` format | tests and docs use these terms |
| Architecture overview, boundaries, C4 L1/L2 | `docs/architecture/overview.md`, `c4-context.md`, `c4-container.md`, `device-ports.md` | 2 | `tests/test_architecture.py`; Mermaid renders on GitHub | |
| Data-model meaning | `docs/architecture/data-model.md` | 2 | `leafi/core/storage.py` schema is the fact; `tests/test_storage.py` | read with the schema |
| The reading algorithm (alignment, completion, practice, controls, difficulties, CHECK) | `docs/adr/0013-reading-algorithm-v1.md` (pseudocode) → `leafi/study/alignment.py`, `session.py` | 2 | `tests/test_alignment.py` walkthroughs, `tests/test_practice.py`, `tests/test_session_controls.py` | the ADR is the only place the rules are stated; flows draw them |
| Supervision and alerting (service policy, configuration checks, heartbeat, dashboard, alert outbox) | `docs/adr/0016-supervision-and-alerting.md` → `leafi/ops/`, `leafi/core/alerts.py`, `scripts/win/keep.ps1` | 2 | `tests/test_supervisor.py`, `tests/test_checks.py`, `tests/test_alerts.py` | the ADR states the rules; `flows/supervision.md` only draws them |
| Design review record | `docs/plans/active/reviews/*.md` + `prompts/` | 1 | — | five codex rounds (2026-10-19) and the implementation review; rerun with the stored prompts |
| Config semantics | `docs/architecture/config.md` + `.env.example` + `config/devices.yml` | 2 | pydantic validation; `python -m leafi devices` | |
| Runtime flows | `docs/architecture/flows/*.md` | 2 | the session test that walks each | one diagram per flow |
| Deployment topology | `docs/architecture/deployment.md` | 2 | `docker-compose.yml`, `scripts/win/*.bat` are the facts | |
| Measured device facts (duplex, mic suppression and recovery, latency, pads, SNR and ASR accuracy, capture lag, failure modes) and the Ear × Mouth matrix | `docs/hardware/<device>.md`, `docs/hardware/combinations.md` | 2 | each row names its probe in `scripts/probes/`; rule in `docs/hardware/README.md` | ADRs keep decisions and link here; tech-debt rows keep the work; the plan's Progress keeps the dated narrative |
| Security, reliability, performance | `docs/architecture/quality-attributes/*.md` | 2 | privacy test; fallback tests; bench scripts | |
| Consequential decisions | `docs/adr/NNNN-*.md` (short format + status, ADR-0015; 0001–0014 MADR) | 2 | status ∈ proposed/accepted/deprecated/superseded; never edit accepted | supersede, do not rewrite |
| Directory responsibilities | `docs/engineering/repo-map.md` | 2 | path-exists check (manual until CI) | |
| Problem → files → invariant → check | `docs/engineering/code-locator.md` | 2 | path-exists | search, do not read whole |
| Conventions differing from defaults | `docs/engineering/conventions.md` | 2 | each row names its enforcer | |
| Test strategy | `docs/engineering/testing.md` | 2 | suite structure | commands in `pytest.ini` |
| Research corpora and source tables | `docs/research/<date>-<topic>.md` | 2 | tiered-research source table with dates | input to plans, never a plan |
| Historical design (habit track v0.2) | `docs/archive/2026-08-habit-coach-design-v0.2.md` | 2 (history) | — | superseded by ADR-0001 |
| Generated artefacts (schema dump, API index) | skipped — reason: SQLite schema is small and lives in `storage.py`; no external API consumer | 3 | — | |
| Vendored third-party references | skipped — reason: none needed offline yet; `docs/research` cites URLs | 4 | — | |
| Procedures (setup, model download, release) | `python -m leafi doctor` output + shared skills via `.claude/skills/` junctions (`obsidian-vault-ops`, `docs-maintainer`, `codex-review`, `anki-cards`, `code-plan-review`) and the `mattpocock-skills` plugin | 5 | junction exists; `claude plugin list` | procedures never live in docs |
| Issue tracker and domain-doc layout for Matt Pocock's skills (their project bindings) | `docs/agents/issue-tracker.md`, `docs/agents/domain.md` | 5 | advisory | the skills read these fixed paths; `domain.md` repeats AGENTS.md pointers on purpose |
| Matt Pocock skills' specs and tickets | `.scratch/<feature>/` (gitignored) | 1 (scratch) | advisory | not a record: decisions move to the active plan's Decision log or an ADR before the work closes |
| Where every fact lives (this table) | `docs/ownership-map.md` | 6 | review at each plan close | |
| Freshness grades, gardening cadence | skipped until the first gardening run — reason: docs are one day old | 6 | — | |
| Incidents, changelog, evals | skipped — reason: none yet; first incident creates `docs/incidents/` | 2/6 | — | |
| Human console and tutorials | Obsidian vault `scil/Leafi/` (owner's), not a documentation owner | — | `obsidian-vault-ops` alias check | buttons call `scripts/win/*` |
