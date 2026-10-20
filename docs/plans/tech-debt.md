# Technical debt

| id | Item | Owner | Grade | Trigger to pay |
|---|---|---|---|---|
| TD-1 | `anthropic` SDK is 0.120.2; current major is 1.x (httpx2). The brain service may need `fallbacks: "default"` / `output_config.format`, which must be checked against the installed version. | brain | B | first brain ticket; run `/claude-api upgrade python` in its own commit |
| TD-2 | No linter/formatter configured (ruff). | repo | C | first `leafi/` commit adds `ruff` to `requirements-dev.txt` and a `[tool.ruff]` table |
| TD-3 | Frigate (15000) and MQTT (18830) are host-mapped without auth. | deployment | C | when any device outside the PC joins the LAN services |
| TD-4 | `agent/` (habit track) talks to go2rtc and MQTT directly instead of through the Hub; two config modules, two SQLite files. | habits | B | product.md T2, after the study track is stable |
| TD-5 | Chinese comments and log strings in `agent/` (owner rule: repository text is English). | habits | D | translate per touched line |
| TD-6 | `codex-review` skill says the CLI rejects `gpt-6-astra`; it accepts it as of codex-cli 0.155.0 (checked 2026-10-19). | shared skill `codex-review` | D | harvest into the skill (one line) |
| TD-7 | docs-maintainer refresh gate was due (34 days); 10 sources changed. A quick read found no rule change affecting this repo; the skill's changelog and fingerprints are not updated here (another repo). | shared skill `docs-maintainer` | D | run the Refresh path in `ai-skills` |
| TD-8 | Obsidian console note still named "Carema Console"; links fixed, filename kept to preserve wikilinks. | vault | D | when the four tutorial notes are revised for the study track |
