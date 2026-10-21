# Implementation review, round 5 — full pass (fallback reviewer: a fresh Claude subagent, read-only)

Run 2026-10-21 on fc9d40c (whole implementation from 62e4b6c^). Prompt: prompts/env-impl-round-5.md. Codex was still at its usage limit. Service behaviour (item 5) and leaks (item 1): no findings; the 183 env tests passed.

## Findings

- Medium — leafi/envedit.py → leafi/ops/timing.py:80: `KEEP_CRASH_EXITS=1` followed by 400 zeros passes pydantic, then `timing.resolve` raises OverflowError; the save got no response (server traceback, nothing written). The same `.env` value would crash the supervisor itself (pre-existing). Fix: out-of-range numbers fall back to defaults before the invariants; `save` answers on any unexpected exception.
- Medium — leafi/ops/timing.py: `KEEP_CRASH_WINDOW_MIN=inf` and `TASK_REPEAT_MIN=2147483648` commit without warnings and reach keep.ps1 / install-tasks.ps1, which reject them (`[double]"inf"`, Int32 overflow). Fix: finite and Int32-range values only; others fall back with the `range` problem.
- Low — leafi/envprotect.py: switching `LEAFI_NO_NETWORK` off needs no confirmation although it widens what may leave the house. Fix: add to PRIVACY_FLOOR and mark it privacy.
- Low — leafi/envedit.py `env_example` vs agreement: a commented example or a default that cannot be stored passes agreement and crashes `python -m leafi env-example`. Fix: agreement encodes every value env_example writes.
- Low — leafi/envedit.py `view`: an unreadable `.env` (a directory, locked) raises in GET /api/env. Fix: report it as a problem, read-only.

Not clean.
