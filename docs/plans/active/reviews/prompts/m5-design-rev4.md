Increment review of `docs/plans/active/2026-10-23-m5-egress-design.md` revision 4. Revision 4 answers the
review of revision 3, `docs/plans/active/reviews/2026-10-23-m5-design-rev3-codex.md` (items 1–33, cited in the
design as S1–S33). Earlier rounds and the owner's decisions:
`docs/plans/active/reviews/2026-10-23-m5-design-round-1-comparison.md`,
`docs/plans/active/reviews/2026-10-23-m5-design-rev2-codex.md`. Governing ADR:
`docs/adr/0018-learners-and-privacy-v2.md`; code under `leafi/`, `agent/` and `scripts/`.

1. For each item of the revision-3 review still partly or open there (S1, S2, S6, S8, S13, S14, S17, S18, S19,
   S22, S23, S24, S28–S33): closed, partly (what remains) or open.
2. What did revision 4 introduce that is new and wrong — in particular per-grant socket sets closed at
   revocation, grants living until the response stream closes, the SDK body parsed and its own bytes sent, the
   header value patterns, the `.env` policy fingerprint instead of a counter, the admission point and the
   stated one-request window, the reservation write before each transmission, `former:<id>` surrogates, the
   required school answer that refuses existing learners' cloud text until answered, the HF continuation
   capabilities, and the `migrate` chain.
3. Is anything still High enough that code should not start? Distinguish a design hole from detail that
   belongs in the implementation and its tests.

Report a numbered list, each with severity (High / Medium / Low), the decision it concerns, the concrete
failure and a suggested fix. Say plainly what is sound. Do not edit any file.
