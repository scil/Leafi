Confirming review of `docs/plans/active/2026-10-23-m7-brain-design.md` revision 6, the last round before
implementation. The review of revision 5 is `docs/plans/active/reviews/2026-10-23-m7-design-rev5-claude.md`
(findings 1–14, cited in revision 6 as "round 5 #n"). Revision 6 also reconciles the design with the practice design
`docs/plans/active/2026-10-24-practice-planning-design.md` (rev 3) and the owner's 2026-10-24 decisions; the
comparison and what rev 6 adopts (A1–A5, C1, C3) are in `docs/plans/active/reviews/2026-10-24-m7-rev5-vs-m7f.md`.
Owner decisions: the plan's Decision log (`docs/plans/active/2026-10-22-ai-led-study.md`, entries of 2026-10-23 and
2026-10-24). Governing ADRs: `docs/adr/0017-ai-led-study-session.md`, `docs/adr/0018-learners-and-privacy-v2.md`.
Code: `leafi/study/harness/inputs.py`, `leafi/devices/console.py`, `leafi/services/asr/__init__.py`,
`leafi/core/text.py`, `leafi/core/hub.py`, `leafi/core/learner_store.py`, `leafi/core/storage.py`,
`leafi/study/records.py`, `leafi/study/harness/` (`rows.py`, `activities.py`, `identify.py`, `guests.py`,
`negotiate.py`, `loop.py`), `leafi/study/anki.py`, `leafi/study/knowledge.py`, `leafi/privacy/egress.py`,
`leafi/privacy/versions.py`, `leafi/privacy/settings.py`, `leafi/core/config.py`, `tests/test_architecture.py`.

1. For each of round 5's findings 1–14: "closed", "partly" (what remains) or "open".
2. Hand-execute the restated **D21** on: an answer typed while B's question plays (text mode with a Mouth); a line
   typed before B's question started while no read was in flight; "skip" in voice `read_listen`; a `/page` typed
   during the `decide` wait followed by `practise_errors`; the Ear lost during `controls_only` then a new activity;
   a 5-minute listen across the 60 s pruning. Check `present(o)` against every place that speaks a prompt today
   (`negotiate`, activities, `identify`, `identify_book`).
3. Hand-execute **D22**'s one refusal rule on: an encounter explanation of B built from A's note; an `add_cards`
   card; a decision record; an audit row; each while `forget --learner A` runs. Run D22's `test_architecture` rule
   against today's code (grep every INSERT form and every UPDATE setting `learner_id` / `*_source_learners` /
   `*_provenance_class`): what does it flag, and is the exemption list complete and justified?
4. Does rev 6's adoption of A1–A5, C1 and C3 agree with the practice design and the owner's decisions, or introduce
   a conflict (the port's multi-turn `Turn`s, the second breakpoint, the school change in M7a, `forget
   --brain-records`, retention "until deleted")?
5. Anything new and wrong elsewhere in rev 6 (D8's detector states, D9's `effective_tiers`, D5's `CallAttempt`)?
6. **Readiness:** can M7a start? If not, exactly what blocks it; separately what blocks M7b–M7e.

Report a numbered list, each with severity (High / Medium / Low), the decision it concerns, the concrete failure
and a suggested fix. Say plainly what is sound. Do not edit any file.
