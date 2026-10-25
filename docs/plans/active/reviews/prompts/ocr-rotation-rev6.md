Confirming round. Review **revision 6** of `docs/plans/active/2026-10-25-ocr-rotation-and-text-block-design.md` (stage
1) as a design, not as prose. Rev 6 answers round 5 (`docs/plans/active/reviews/2026-10-25-ocr-rotation-round-5-codex.md`,
V1–V5) in O4, O7 and O8. The book's paper, desk text and spreads are stage 2 and out of scope, as are the stated
limits under "Known limits of stage 1". The owner's decisions are fixed (ordered rotations with default `270,90,0`,
the angle probe, the remembered angle, an unsure read on an unchanged frame asks at once, stored pages may re-match).

1. Check that V1–V5 are answered: hand-execute O7's missing-words guard (`difflib` opcodes) on a partial read, a
   reformatted revision, a page stored with OCR errors read correctly, a page with verified corrections read with the
   old misreads, a read that inserts extra desk words, and a page whose stored text is short (1–5 words); O4's cover
   rule through `books.identify`; `OCR_ROTATIONS=0`; the moved-book path.
2. Check that each answer reached every place the old decision was stated (no passage still says `COVERAGE`, "say
   'page N'", "the two highest scores" without the one-pass case, or the old cover rule).
3. Anything else in rev 6 that would make step 2 fail to land as one commit with the full suite green.

If nothing needs to change, say so plainly. Otherwise report findings as a numbered list, each with severity
(High / Medium / Low), the decision or line, the concrete failure (inputs → outcome), and a suggested fix. Do not edit
any file.
