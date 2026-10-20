# Technical debt

| id | Item | Owner | Grade | Trigger to pay |
|---|---|---|---|---|
| TD-1 | `anthropic` SDK is pinned at 0.120.2: it has `output_config` and `thinking` but no `fallbacks` parameter (checked 2026-10-19), so refusal fallback is application-owned. Upgrade to 1.x (httpx2) is a separate ticket once a reason exists. | brain | C | a feature that needs 1.x; run `/claude-api upgrade python` in its own commit |
| TD-9 | Resolved 2026-10-19 (ADR-0011 amendment): habit snapshot becomes opt-in `NOTIFY_WITH_SNAPSHOT` (default false); implementation + test in S1. Owner may flip it in `.env`. | habits | — | done when S1 lands |
| TD-10 | Frigate/MQTT host ports and host go2rtc RTSP 2554 are bound without auth (merged into TD-3 scope: all supporting services, not only Frigate). | deployment | C | any non-PC device on the LAN |
| TD-2 | No linter/formatter configured (ruff). | repo | C | first `leafi/` commit adds `ruff` to `requirements-dev.txt` and a `[tool.ruff]` table |
| TD-3 | Frigate (15000) and MQTT (18830) are host-mapped without auth. | deployment | C | when any device outside the PC joins the LAN services |
| TD-4 | `agent/` (habit track) talks to go2rtc and MQTT directly instead of through the Hub; two config modules, two SQLite files. | habits | B | product.md T2, after the study track is stable |
| TD-5 | Chinese comments and log strings in `agent/` (owner rule: repository text is English). | habits | D | translate per touched line |
| TD-6 | `codex-review` skill says the CLI rejects `gpt-6-astra`; it accepts it as of codex-cli 0.155.0 (checked 2026-10-19). | shared skill `codex-review` | D | harvest into the skill (one line) |
| TD-7 | docs-maintainer refresh gate was due (34 days); 10 sources changed. A quick read found no rule change affecting this repo; the skill's changelog and fingerprints are not updated here (another repo). | shared skill `docs-maintainer` | D | run the Refresh path in `ai-skills` |
| TD-8 | Obsidian console note still named "Carema Console"; links fixed, filename kept to preserve wikilinks. | vault | D | when the four tutorial notes are revised for the study track |
