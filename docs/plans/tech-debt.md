# Technical debt

| id | Item | Owner | Grade | Trigger to pay |
|---|---|---|---|---|
| TD-1 | `anthropic` SDK is pinned at 0.120.2: it has `output_config` and `thinking` but no `fallbacks` parameter (checked 2026-10-19), so refusal fallback is application-owned. Upgrade to 1.x (httpx2) is a separate ticket once a reason exists. | brain | C | a feature that needs 1.x; run `/claude-api upgrade python` in its own commit |
| TD-9 | Resolved 2026-10-19 (ADR-0011 amendment): habit snapshot becomes opt-in `NOTIFY_WITH_SNAPSHOT` (default false); implementation + test in S1. Owner may flip it in `.env`. | habits | — | done when S1 lands |
| TD-10 | Frigate/MQTT host ports and host go2rtc RTSP 2554 are bound without auth (merged into TD-3 scope: all supporting services, not only Frigate). | deployment | C | any non-PC device on the LAN |
| TD-2 | Resolved 2026-10-20: ruff in `requirements-dev.txt`, `[tool.ruff]` in `pyproject.toml`, clean on `leafi/` and `tests/`; `agent/` not yet linted. | repo | D | lint `agent/` when it is next touched |
| TD-11 | ADR-0013 fuzzy threshold 0.80 accepts near-misses (`though`/`through`, `small`/`smell`), so such misreadings never become candidates; only the correction flow or the gated pronunciation scorer can catch them. | study | B | after P-4: lower the threshold for lexicon words, or require exact match for words ≤ 5 letters; decide with real sessions |
| TD-12 | ADR-0013 walkthrough (f): a six-token line skip after only four read words in the same utterance scores cheaper as substitutions (4.6 < 4.8), and a repeated word inside the skipped line flips the tie-break. | study | C | once real reading shows a skipped line misclassified: add "≥ 3 consecutive substitutions with no match = line skip" to ADR-0013 |
| TD-13 | `AGENTS.md` is 5.0 KB (target < 4 KB); Codex's 32 KiB chain budget is far away. | docs | D | next `ai-agents-md` review pass |
| TD-15 | A process whose speech lease expired (laptop suspended longer than `LEASE_TTL_S`) is still alive but treated as dead: a second launch closes its session while it may still write (`IllegalTransition` on the next status change). | study | B | before the first voice session: a live-owner check (lease renewal failure stops the session) |
| TD-16 | An exception inside `ear.listen()` kills the VoiceListener pump silently; every later `next_utterance` returns `None` at once. | study | B | before the first voice session: surface capture failure as `LISTENER_LOST` |
| TD-14 | Not built in the first implementation run: `services/vision` for the study track, the Frigate presence adapter, a Whisper ASR backend, `doctor --download` (prints commands only), Silero VAD, camera-as-microphone. | study | C | the hardware plan (P-1…P-6) |
| TD-3 | Frigate (15000) and MQTT (18830) are host-mapped without auth. | deployment | C | when any device outside the PC joins the LAN services |
| TD-4 | `agent/` (habit track) talks to go2rtc and MQTT directly instead of through the Hub; two config modules, two SQLite files. | habits | B | product.md T2, after the study track is stable |
| TD-5 | Chinese comments and log strings in `agent/` (owner rule: repository text is English). | habits | D | translate per touched line |
| TD-6 | `codex-review` skill says the CLI rejects `gpt-6-astra`; it accepts it as of codex-cli 0.155.0 (checked 2026-10-19). | shared skill `codex-review` | D | harvest into the skill (one line) |
| TD-7 | docs-maintainer refresh gate was due (34 days); 10 sources changed. A quick read found no rule change affecting this repo; the skill's changelog and fingerprints are not updated here (another repo). | shared skill `docs-maintainer` | D | run the Refresh path in `ai-skills` |
| TD-8 | Obsidian console note still named "Carema Console"; links fixed, filename kept to preserve wikilinks. | vault | D | when the four tutorial notes are revised for the study track |
