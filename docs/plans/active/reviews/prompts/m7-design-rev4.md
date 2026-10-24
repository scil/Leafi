Increment review of `docs/plans/active/2026-10-23-m7-brain-design.md` revision 4. The review of revision 3 is
`docs/plans/active/reviews/2026-10-23-m7-design-rev3-claude.md` (findings 1–12, cited in revision 4 as S1–S12; the
author marked S5's ADR contradiction a false positive, citing ADR-0017 §6.2 — check that call); the aborted codex
round's probe is in `docs/plans/active/reviews/2026-10-23-m7-design-rev3-codex-aborted.md`. Earlier rounds:
`2026-10-23-m7-design-rev2-codex.md` (R1–R14) and `2026-10-23-m7-design-round-1-comparison.md` (T1–T24), both in
the same folder. Owner decisions O1–O6: the plan's Decision log (`docs/plans/active/2026-10-22-ai-led-study.md`).
Governing ADRs: `docs/adr/0017-ai-led-study-session.md`, `docs/adr/0018-learners-and-privacy-v2.md`. Code:
`leafi/privacy/egress.py` (`prepare`, `_gate`, `admit`), `leafi/privacy/versions.py`, `leafi/privacy/settings.py`,
`leafi/privacy/destinations.py`, `leafi/core/learner_store.py`, `leafi/study/records.py` (forget),
`leafi/study/harness/` (`inputs.py`, `menu.py`, `construct.py`, `loop.py`, `activities.py`), `leafi/study/anki.py`,
`leafi/services/asr/__init__.py`, `leafi/core/config.py`.

1. For each of S1–S12: "closed", "partly" (what remains) or "open".
2. What did revision 4 introduce that is new and wrong? Hand-execute in particular: D2's `PARENT_SOURCE` through
   `prepare`, `versions.snapshot`/`stale`, `_gate`, `stated_sources` and the fence, for a `[A, 0]` leaf to a local and
   a cloud destination; D8's worked example on a real clock, including a cancellation during `standard`; D12's
   per-request stamping when B's `listen` requests a reader that is still busy with A's request; D17's hand-run of
   revision 4 step by step, and `card_gone` followed by the card reappearing; D19's deletion order under
   `forget --learner` with foreign keys on, and an insert racing the mark; D9's read-time fallback with
   `STUDY_BRAIN_MODEL` set and no tier keys.
3. Can each step M7a–M7e land with the suite green in the order given?

Report a numbered list, each with severity (High / Medium / Low), the decision it concerns, the concrete failure
and a suggested fix. Say plainly what is sound, and say whether the design is ready to implement. Do not edit any
file.
