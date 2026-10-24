# M7 design rev 3 — codex increment round 3 (aborted)

Reviewer: codex `gpt-6-astra`, reasoning effort high, read-only sandbox, prompt `reviews/prompts/m7-design-rev3.md`, run 2026-10-23. It stopped at the account's usage limit ("try again at Oct 24th, 2026 2:00 AM") after 125,402 tokens, before writing a report. The round was rerun by the `codex-review` skill's fallback, a fresh Claude agent on the same prompt (`2026-10-23-m7-design-rev3-claude.md`).

One result survives in its log, from an in-memory probe it ran on a throwaway database against the current code:

- `D2 unchanged admission after zero accepted by gate: source learner 0 is gone` — with `_gate` changed to accept source `0`, egress's admission still refuses the token, because its source-version snapshot treats `0` as a learner that no longer exists. D2 must exclude `learner_store.PARENT_SOURCE` wherever egress reads sources (`prepare`'s `sources` and `privacy` map, `versions.snapshot`, and the admission re-check), not only in `_gate` and the fenced insert.
- The same probe found the fenced insert, once changed to skip `0`, accepts `[0, 1]`; refuses it after learner 1 is marked `forgetting`; and the source rescan (`json_each(source_learners)`) deletes it — D19's fence and deletion work as designed.
