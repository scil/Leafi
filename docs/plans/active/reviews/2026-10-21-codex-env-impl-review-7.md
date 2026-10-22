# Implementation review, round 7 — final full pass (Claude Opus 5.5 subagent, read-only; owner's request)

Run 2026-10-21 on 69839bb (62e4b6c^..69839bb). Prompt: prompts/env-impl-round-7.md. Claude verified M1 (agent/vision/vlm.py posts camera frames to OLLAMA_URL) and M3 (encode rejected an apostrophe; the pre-change setup wrote it) by probe; Compose was then run on the new double-quoted form.

Checked without findings: leaks (60,000-case fuzz of EnvFile.parse against python-dotenv, 0 inner lines named as keys; logs carry key and exception class names only); writes (ReplaceFileW outcome table matches Win32 documentation); service behaviour (parsers byte-equivalent and evaluated where they were; only the five intended `KEY=''` lines of .env.example read differently; new constants have no runtime reader).

## Medium

- M1 — leafi/envprotect.py, leafi/envedit.py: `OLLAMA_URL` (the vision judge posts camera frames to `{OLLAMA_URL}/api/chat`) and `TELEGRAM_CHAT_ID` (destination of snapshot frames) change without confirmation; moving either off the LAN sends images out (ADR-0011 red line). Fix: add both to PRIVACY_FLOOR and the manifest.
- M2 — tests/test_env_protections.py, tests/test_webui_env.py: weakening `_check_op` to accept any confirmation still passes every test; no test sends a confirmation for a different value. Fix: refuse `confirm` bound to another value, for every privacy key, including `unset`.
- M3 — leafi/core/envfile.py encode, leafi/cli.py: `setup --redact "Ann O'Brien,..."` fails ("cannot be stored"), a regression; editing by hand makes the file non-canonical. A learner name with an apostrophe cannot be redacted. Fix: one apostrophe-safe canonical form that every reader agrees on.

## Low

- L1 — leafi/envedit.py: bool values `off`, `1`, `yes`, `T` are saved verbatim although only `true`/`false` are offered; the page then shows "(默认)" for a set value. Fix: require an offered spelling for bool.
- L2 — tests/test_envedit.py: the overflow case passes through the catch-all ("could not validate") even with the range fallback removed. Fix: assert ok and a `range` warning.
- L3 — leafi/cli.py: `setup --redact` with an unreadable .env exits with a PermissionError traceback (current_digest outside save). Fix: catch OSError, print, return 1.

Not clean at the time of review; all six fixed in the following commit with tests (each new test fails without its fix, except M2's, which pins down behaviour that was already correct).
