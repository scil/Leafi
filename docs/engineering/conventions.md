# Conventions that differ from defaults

| Convention | Enforced by |
|---|---|
| Code, commit messages, repository docs are English. Legacy Chinese comments/log strings in `agent/` are translated when a line is touched, not in bulk. | review (advisory) |
| Diagrams are Mermaid fenced blocks (GitHub and Obsidian render them); docs-maintainer's PlantUML default is not used because no renderer exists here. | advisory |
| ADRs under `docs/adr/` use Matt Pocock's short `domain-modeling` format with `status` frontmatter (ADR-0015; 0001–0014 keep their MADR sections); accepted ADRs are superseded, never edited. | review |
| `.scratch/` (Matt Pocock's issue tracker, gitignored) is scratch, not a record: a decision made there moves to the active plan's Decision log or an ADR before the work closes. | advisory |
| Every port and service has a `mock` implementation; a test that needs hardware or a model is marked `@pytest.mark.hardware` and skipped by default. | `pytest.ini` markers |
| Async everywhere in `leafi/`; blocking model calls go through `loop.run_in_executor`. | review |
| Adapters have no import-time side effects (no sockets, no model loads). | `tests/test_hub.py::test_import_is_pure` |
| Settings come from pydantic-settings; no `os.environ` reads outside `core/config.py`. | `tests/test_architecture.py` grep |
| Ruff for lint/format (`ruff check . && ruff format --check .`) once added (TD-2). | CI-less for now: run before commit |
| No attribution trailers in commits. | owner rule |
