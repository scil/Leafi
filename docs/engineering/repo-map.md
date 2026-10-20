# Repo map

Curated; every path below exists or is created by the active plan (marked *planned*).

| Path | Owns | Entry points |
|---|---|---|
| `AGENTS.md`, `CLAUDE.md` | agent instruction map (layer 0) | — |
| `GLOSSARY.md` | domain vocabulary | — |
| `docs/` | plans, product, architecture, ADRs, engineering, research, ownership map, archive | `docs/ownership-map.md` |
| `leafi/` *planned* | the hardware-agnostic agent | `python -m leafi {study,devices,doctor,export}` |
| `leafi/core/` | ports, hub, config, storage, audio/text helpers | `hub.Hub.from_yaml()` |
| `leafi/devices/` | adapters: go2rtc camera, local PC, console, Frigate presence, notifiers; later xiaozhi, Wyoming | registry in `devices/__init__.py` |
| `leafi/services/{asr,tts,ocr,pronunciation,brain,vision}/` | model services with backend registries and mocks | `services.<name>.get()` |
| `leafi/study/` | book-study track | `study.session.run()` |
| `agent/` | legacy habit track (scheduler, session state machine, presence, speaker, verifier, task editor) | `python -m agent.main`, `python -m agent.webui` |
| `config/devices.yml` *planned* | device declarations | — |
| `config/tasks.yml` | habit tasks (written by the task editor) | — |
| `config/frigate/config.yml`, `docker-compose.yml` | Frigate + mosquitto | `docker compose up -d` |
| `tools/go2rtc/` | patched host go2rtc, `PATCHES.md`, host yaml | `scripts/win/go2rtc-host.bat` |
| `scripts/win/*.bat`, `scripts/*.py` | console buttons (Obsidian) and smoke scripts | — |
| `tests/` | pytest suite; `conftest.py` provides mock hub and services | `.venv\Scripts\python -m pytest -q` |
| `models/` *planned, gitignored* | downloaded model files | `python -m leafi doctor` |
| `data/`, `cache/` (gitignored) | SQLite stores; TTS/page/audio caches | — |
| `.claude/skills/` | junctions to shared skills (`obsidian-vault-ops`, …) | — |
| `.scratch/` *planned, gitignored* | local markdown issue tracker for Matt Pocock's skills | `docs/agents/issue-tracker.md` |
