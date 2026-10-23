Increment review of `docs/plans/active/2026-10-23-m5-egress-design.md` revision 2. Round 1's themes, who
found them, the intended fix direction and the owner's decisions are in
`docs/plans/active/reviews/2026-10-23-m5-design-round-1-comparison.md`; the round-1 records are beside it. The
governing ADR is `docs/adr/0018-learners-and-privacy-v2.md`; the code is under `leafi/` (start with
`leafi/core/netguard.py`, `leafi/core/storage.py`, `leafi/services/brain/claude.py`,
`leafi/services/tts/`, `leafi/devices/notifiers.py`, `leafi/study/harness/inputs.py`, `leafi/study/phrases.py`).

1. For each theme T1–T22: does revision 2 close it? Say "closed", "partly" (what remains) or "open".
2. What did revision 2 introduce that is new and wrong: holes in D2's grant active set and transport-opened
   grants, D6's token id via ContextVar, D7's claim, D10's stored surrogates and script-aware matching, D12's
   revalidation, D18 and steps M5a–M5e (can each land green with no window where the old enforcement is gone
   and the new one is not in place)?
3. Do the owner's four decisions (surrogate in notifications; list-only fallback; checkbox confirmation;
   structured age only) conflict with ADR-0018 or AGENTS.md's boundary in a way the design does not
   acknowledge?

Report a numbered list, each with severity (High / Medium / Low), the decision it concerns, the concrete
failure and a suggested fix. Say plainly what is sound. Do not edit any file.
