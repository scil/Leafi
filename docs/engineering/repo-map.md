# Repo map

Curated; every path below exists or is created by the active plan (marked *planned*).

| Path | Owns | Entry points |
|---|---|---|
| `AGENTS.md`, `CLAUDE.md` | agent instruction map (layer 0) | — |
| `GLOSSARY.md` | domain vocabulary | — |
| `docs/` | plans, product, architecture, ADRs, engineering, research, ownership map, archive | `docs/ownership-map.md` |
| `leafi/` | the hardware-agnostic agent; `app.py` = composition root, `runner.py` = study entry, `doctor.py` | `python -m leafi {study,devices,doctor,export,forget,setup}` (`cli.py`) |
| `leafi/core/` | ports, hub (+ devices.yml parsing, listening gate), config, storage (schema), text, audio, speech lease, no-network guard | `hub.Hub(...)`, `storage.Store(path)` |
| `leafi/devices/` | adapters: go2rtc camera (Eye+Mouth), local PC (Ear, Mouth), console (Listener, Face), notifiers; later Frigate presence, xiaozhi, Wyoming | registry in `devices/__init__.py` |
| `leafi/services/{asr,tts,ocr,pronunciation,brain,catalog}/` | model services with backend registries and mocks (`vision` stays in `agent/` for now) | `services.<name>.REGISTRY.create(name, settings)` |
| `leafi/study/` | book-study track: alignment, session, pages, corrections, lexicon, knowledge, anki, coach, controls, phrases, page_tracker, books, records | `study.session.StudySession(...).run()` |
| `agent/` | legacy habit track (scheduler, session state machine, presence, speaker, verifier, task editor) | `python -m agent.main`, `python -m agent.webui` |
| `config/devices.yml` | device declarations | `python -m leafi devices` |
| `config/tasks.yml` | habit tasks (written by the task editor) | — |
| `config/frigate/config.yml`, `docker-compose.yml` | Frigate + mosquitto | `docker compose up -d` |
| `tools/go2rtc/` | patched host go2rtc, `PATCHES.md`, host yaml | `scripts/win/go2rtc-host.bat` |
| `scripts/win/*.bat`, `scripts/*.py` | console buttons (Obsidian) and smoke scripts | — |
| `tests/` | pytest suite; `conftest.py` (isolated `settings`, hardware skip), `fakes/` (faces, mouths, synth, scripted listener, AnkiConnect), `fixtures/pages/` (PIL renderer, `p1.txt`), `seed.py` | `.venv\Scripts\python -m pytest -q` |
| `pyproject.toml`, `requirements-study.txt`, `requirements-dev.txt` | ruff config; study and dev dependencies (install path stays `requirements*.txt`) | `.venv\Scripts\python -m ruff check leafi tests` |
| `models/` *planned, gitignored* | downloaded model files | `python -m leafi doctor` |
| `data/`, `cache/` (gitignored) | SQLite stores; TTS/page/audio caches | — |
| `.claude/skills/` | junctions to shared skills (`obsidian-vault-ops`, …) | — |
| `.scratch/` *planned, gitignored* | local markdown issue tracker for Matt Pocock's skills | `docs/agents/issue-tracker.md` |
