# Implementation review, round 6 — confirming (fallback reviewer: a fresh Claude subagent, read-only)

Run 2026-10-21 on 7acc738. Prompt: prompts/env-impl-round-6.md. Codex was still at its usage limit.

## Round-5 findings

- OverflowError on a huge KEEP_CRASH_EXITS: resolved (falls back with `range`; save answers 200).
- Non-finite / beyond-Int32 values reaching the PowerShell readers: partially resolved (finding A).
- LEAFI_NO_NETWORK without confirmation: resolved.
- Unstorable env_example value: resolved (agreement reports it).
- Unreadable .env in view: resolved.

## Behaviour change of `_in_range`

40,000 random finite, Int32-range settings combinations resolve identically under fc9d40c and 7acc738 (0 differences); `as_env` of the defaults is unchanged. Only non-finite or out-of-range values change: they now report `range` (e.g. `SUPERVISOR_POLL_S=nan` was `resume-gap, resume-grace, healthy`; `KEEP_CRASH_WINDOW_MIN=inf` was no problem; a huge KEEP_CRASH_EXITS was an OverflowError).

## Finding

- A (Low/Medium) — leafi/ops/timing.py `_in_range`: Int32 is not keep.ps1's limit for a backoff: `KEEP_BACKOFF_S=5,30,120,3000000` (with a long enough crash window) resolves with no problem, and Windows PowerShell 5.1 `Start-Sleep -Seconds` rejects values above 2147483, so keep.ps1 restarts without delay from the fourth exit. Fix: backoff entries above 2147483 fall back with `range`. Fixed in the next commit, with a test.

Not clean at the time of review; finding A fixed afterwards and not re-reviewed (the five-round budget plus the confirming round is spent).
