Design round 4 (confirming). Review **revision 4** of `docs/plans/active/2026-10-25-study-session-panel-design.md`
as a design, not as prose, whole. Earlier rounds: round 1 (three reviewers, compared in
`reviews/2026-10-25-session-panel-round-1-comparison.md`), round 2 (`reviews/2026-10-25-session-panel-rev2-codex.md`),
round 3 on D7 (`reviews/2026-10-25-session-panel-rev3-codex.md`). Rev 4 moves `/do` to safe points (the running
activity's listens and `read_aloud`'s sentence gaps; boundary exits) instead of cancelling at any await. The owner's
decisions in the plan's Decision log (`docs/plans/active/2026-10-25-study-session-panel.md`) are fixed.

1. D7: hand-execute the safe-point rule on the code (`leafi/study/harness/inputs.py`, `negotiate.py`, `loop.py`,
   `activities.py`, `world.py`): is every listen an activity makes reached by the wake, including helpers and
   listens inside `controls_only` callers? Does any activity loop for a long time without a listen or a
   `read_aloud`-style check (a want then waits indefinitely)? Does `Jump` at each listen leave only states that
   `StaleInput` at the same listen leaves today? Is every negotiate exit covered, and does the silence path that
   rev 4 uses at a boundary interact badly with `negotiation.silence_reasks` or `wait_or_end`?
2. Did fixing rounds 2 and 3 break anything earlier rounds settled (D1 threads and lifecycle, D2 sources, D3
   snapshot, D4 files, D5 tab, D6 actions, D8 evidence table, D9 privacy)?
3. Is any decision still restating ADR-0013 or ADR-0017 instead of amending or referencing it? Any mechanism without
   a provenance line?
4. Anything that blocks landing the eight steps one commit each with the full suite green.

If nothing needs to change, say so plainly. Otherwise report findings as a numbered list, each with severity
(High / Medium / Low), the decision or line, the concrete failure (inputs → outcome), and a suggested fix. Do not edit
any file.
