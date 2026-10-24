Increment review of `docs/plans/active/2026-10-23-m7-brain-design.md` revision 2. Round 1's themes T1–T24, who
found them and the intended fix direction are in `docs/plans/active/reviews/2026-10-23-m7-design-round-1-comparison.md`
(the round-1 records are beside it); the owner's decisions O1–O6 are in the plan's Decision log
(`docs/plans/active/2026-10-22-ai-led-study.md`, entry "2026-10-23 Owner decisions on the M7 design round 1").
The research added for T10 is `docs/research/2026-10-23-item-status-evidence.md`. Governing ADRs:
`docs/adr/0017-ai-led-study-session.md`, `docs/adr/0018-learners-and-privacy-v2.md`. Code: `leafi/privacy/egress.py`
(`prepare`, `_gate`, `admit`, the mediating transport), `leafi/privacy/destinations.py`, `leafi/study/harness/`
(`inputs.py`, `latch.py`, `construct.py`, `negotiate.py`, `menu.py`, `loop.py`), `leafi/study/anki.py`,
`leafi/study/records.py`, `leafi/core/storage.py`, `leafi/core/ports.py`, `leafi/envprotect.py`.

1. For each theme T1–T24: does revision 2 close it? Say "closed", "partly" (what remains) or "open".
2. What did revision 2 introduce that is new and wrong? Hand-execute in particular: D1's resolver against every
   caller of `prepare`; D2's join rule on a local tier that copies a learner note into an assessment; D7's
   charge-after-commit with a busy reservation and with a cancel between commit and the first byte; D8's
   escalation rules on a timeout of `fast` for `decide` under O1's route; D12's `controls_only` parking an answer
   while a Brain call runs inside an activity; D14's per-boundary cache across `Reobserve`; D17's fold on an item
   that is ignored, unignored, then gets a card, and on `forget --session` of its only session; D19's line
   rewriting under `forget --learner` while a session is writing the same file.
3. Do the owner's decisions (O1 Haiku first for `decide`; O2 replay set on by default) conflict with ADR-0017,
   ADR-0018 or `security.md` in a way revision 2 does not acknowledge?
4. Can each step M7a–M7e land with the suite green, and is anything in ADR-0017's Confirmation still without a step?

Report a numbered list, each with severity (High / Medium / Low), the decision it concerns, the concrete failure
and a suggested fix. Say plainly what is sound. Do not edit any file.
