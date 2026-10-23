Increment review of `docs/plans/active/2026-10-23-m5-egress-design.md` revision 3. Revision 3 answers the
previous increment review, `docs/plans/active/reviews/2026-10-23-m5-design-rev2-codex.md` (items 1–28, cited in
the design as R1–R28); round 1 and the owner's decisions are in
`docs/plans/active/reviews/2026-10-23-m5-design-round-1-comparison.md`. Governing ADR:
`docs/adr/0018-learners-and-privacy-v2.md`; code under `leafi/` and `agent/`.

1. For each of R1–R28: closed, partly (what remains) or open.
2. What did revision 3 introduce that is new and wrong — in particular `leafi.bootstrap` instead of
   `leafi/__init__`, transmission-owned connections with no pool, the `x-leafi-token` header removed by the
   transport, field-level encoding in `prepare`, the token removed from the store on first entry, the version
   scheme and its check before each transmission, migration 6 (D19), the HF adapter in a child process, and the
   step order M5a–M5e.
3. Is anything still High enough that code should not start?

Report a numbered list, each with severity (High / Medium / Low), the decision it concerns, the concrete
failure and a suggested fix. Say plainly what is sound. Do not edit any file.
