---
status: accepted
date: 2026-10-19
---

# Documentation lives in the repository `docs/`, organised by loading layer

## Context

Before this change the design was one Chinese document (`方案.md`), a Chinese `CLAUDE.md`, and human tutorials plus a control console in the owner's Obsidian vault. Agents (Claude Code, Codex) are the first readers of project facts, and the owner's global rule is that repository documentation is English-only.

## Decision drivers

- `docs-maintainer`: one owner per fact, routed by loading layer; code wins over prose.
- Matt Pocock's engineering skills expect `GLOSSARY.md` at the root and ADRs under `docs/adr/`.
- The Obsidian vault is where the owner keeps human-facing consoles and tutorials.

## Considered options

1. Keep the system of record in the Obsidian vault (docs-maintainer allows it).
2. In-repo `docs/` for agent-facing facts; the vault keeps consoles and tutorials and points at the repo.

## Decision outcome

Option 2. Layers: 0 `AGENTS.md` (+ `CLAUDE.md` bridge) · 1 `docs/plans/` · 2 `docs/product.md`, `docs/architecture/`, `docs/adr/` (MADR shape, Matt's `docs/adr/` path), `docs/engineering/` · 5 skills via junctions in `.claude/skills/` · 6 `docs/ownership-map.md`. Research corpora go to `docs/research/`. Diagrams are Mermaid because GitHub and Obsidian render it and no PlantUML toolchain exists here (recorded in `engineering/conventions.md`). `方案.md` moves to `docs/archive/` unchanged.

## Consequences

- The Obsidian console note keeps its buttons and links to the repo; it is updated for the rename but is not a documentation owner.
- Chinese text in repository docs is replaced by English on the next touch of each file; code comments may stay as they are until touched.

## Confirmation

`docs/ownership-map.md` names an owner and a check for every node; a link check over `docs/` passes.
