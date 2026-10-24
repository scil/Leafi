Increment review of `docs/plans/active/2026-10-23-m7-brain-design.md` revision 5. The review of revision 4 is
`docs/plans/active/reviews/2026-10-23-m7-design-rev4-claude.md` (findings 1–12, cited in revision 5 as "round 4 #n").
Revision 5's main change: two decisions that every earlier round came back to are now stated once each as an
executable statement — **D21 input ownership** and **D22 the fenced writer** (section "The two rules every round
came back to") — and the other decisions refer to them. Earlier rounds, same folder: `2026-10-23-m7-design-rev3-claude.md`
(S1–S12), `2026-10-23-m7-design-rev2-codex.md` (R1–R14), `2026-10-23-m7-design-round-1-comparison.md` (T1–T24).
Owner decisions O1–O6: the plan's Decision log (`docs/plans/active/2026-10-22-ai-led-study.md`). Governing ADRs:
`docs/adr/0017-ai-led-study-session.md`, `docs/adr/0018-learners-and-privacy-v2.md`. Code: `leafi/study/harness/inputs.py`,
`leafi/services/asr/__init__.py`, `leafi/core/text.py` (`typed_utterance`), `leafi/core/hub.py` (`ListeningGate`),
`leafi/core/learner_store.py`, `leafi/study/records.py` (forget), `leafi/study/harness/rows.py`,
`leafi/study/anki.py`, `leafi/privacy/egress.py`, `leafi/privacy/versions.py`, `leafi/envedit.py`,
`leafi/envprotect.py`, `tests/test_architecture.py`.

1. For each of round 4's findings 1–12: "closed", "partly" (what remains) or "open".
2. **Hand-execute D21's pseudocode** on: a voice segment closing during A's `judge` and transcribed while B listens;
   A's console read in flight when B listens and the learner types B's answer; two voice segments, the first
   closing just before B's `set_owner` and the second just after; a typed `/stop` during a Brain wait in voice mode
   while the filler plays; a `/page` typed during a Brain wait followed by `practise_errors`; the Ear lost during
   `controls_only`. Is the rule "an input belongs to the prompt current when the learner finished it" right, and
   does the pseudocode implement it, including clock sources (`ended_at` from the Listener vs `now()` in `Inputs`)?
3. **Hand-execute D22** on: B's session writing a `brain_calls` row, an assessment UPDATE and a card event of A
   while `forget --learner A` runs, at each point between its transactions; `forget --session` with foreign keys on.
   Does the `test_architecture` rule catch every writer of a `DIRECT` or `PROVENANCE` table that exists today?
4. What did revision 5 introduce that is new and wrong elsewhere (D2, D5, D8's detector load, D9's fallback and
   fingerprint, D17's card return)?
5. Is the design ready to implement? If not, what blocks M7a specifically?

Report a numbered list, each with severity (High / Medium / Low), the decision it concerns, the concrete failure
and a suggested fix. Say plainly what is sound. Do not edit any file.
