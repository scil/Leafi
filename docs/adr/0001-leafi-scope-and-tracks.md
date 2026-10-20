---
status: accepted
date: 2026-10-19
---

# Leafi is a household agent with tracks; book study is the current track

## Context

The project started as Carema-Kis-AI, a single-purpose habit coach (brushing, drinking water) built around one hallway camera. The owner renamed it Leafi and widened the purpose: a family AI that runs several kinds of tasks, with helping a 10-year-old study physical English books as the immediate focus, and with hardware that will vary (cameras, speakers, microphones, an ESP32 screen, or nothing but a PC).

## Decision drivers

- One codebase, one process, one set of devices shared by every task.
- The habit track works today and must keep working during the change.
- The study track needs capabilities the habit track never had (hearing, reading text, remembering knowledge).

## Considered options

1. Fork a new repository for study and leave the habit coach alone.
2. Grow the `agent/` package in place, adding study modules beside the habit ones.
3. A new `leafi/` package with a hardware-agnostic core and *tracks*; `agent/` stays as the habit track until migrated.

## Decision outcome

Option 3. `leafi/core` owns ports, hub, config and storage; `leafi/study` is the first track built on it; `agent/` keeps running unchanged and is migrated onto the hub as a later ticket (product.md T2). Dependencies point inward (overview.md).

## Consequences

- Two packages coexist for a while; the import-graph test keeps `agent/` from leaking into `leafi/`.
- Some duplication (two `config.py`, two SQLite files) until T2.
- The design doc `方案.md` (v0.2, 2026-08) is archived under `docs/archive/` as the habit track's history.

## Confirmation

`tests/test_architecture.py` passes; `python -m agent.main --mock --now brush_pm` still runs after the rename.
