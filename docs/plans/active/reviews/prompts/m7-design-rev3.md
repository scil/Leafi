Increment review of `docs/plans/active/2026-10-23-m7-brain-design.md` revision 3. Your review of revision 2 is
`docs/plans/active/reviews/2026-10-23-m7-design-rev2-codex.md` (findings 1–14, cited in revision 3 as R1–R14);
round 1's themes are in `docs/plans/active/reviews/2026-10-23-m7-design-round-1-comparison.md`; the owner's
decisions O1–O6 are in the plan's Decision log (`docs/plans/active/2026-10-22-ai-led-study.md`). Governing ADRs:
`docs/adr/0017-ai-led-study-session.md`, `docs/adr/0018-learners-and-privacy-v2.md`. Code: `leafi/privacy/egress.py`
(`prepare`, `_gate`, `admit`), `leafi/privacy/destinations.py`, `leafi/core/learner_store.py` (the fenced insert),
`leafi/core/text.py`, `leafi/core/ports.py`, `leafi/study/harness/` (`inputs.py`, `world.py`, `settings.py`,
`activities.py`, `construct.py`, `menu.py`), `leafi/study/anki.py`, `leafi/study/records.py` (forget),
`leafi/core/storage.py`.

1. For each of R1–R14 and for T23: "closed", "partly" (what remains) or "open".
2. What did revision 3 introduce that is new and wrong? Hand-execute in particular: D2's source `0` through
   `_gate`, the fenced insert, `forget --learner` and every reader of `*_source_learners`; D1's model binding for the
   anthropic SDK body and for the v1 Ollama adapter; D7's checks inside the retried reservation; D8's route walk for
   `decide` under O1 when `fast` times out at 3 s and when `standard` then returns `invalid`; D12's parking with a
   voice main source and a console control source while the filler speaks; D17's fold on the hand-run of revision 3
   and on a card whose outbox row is later `failed`; D19's `decision_records` insert racing `forget --learner`.
3. Can each step M7a–M7e land with the suite green in the order given, with every prerequisite earlier?

Report a numbered list, each with severity (High / Medium / Low), the decision it concerns, the concrete failure
and a suggested fix. Say plainly what is sound. Do not edit any file.
