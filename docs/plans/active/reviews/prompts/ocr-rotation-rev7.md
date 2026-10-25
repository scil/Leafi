Confirming round, scoped. Review **revision 7** of `docs/plans/active/2026-10-25-ocr-rotation-and-text-block-design.md`
(stage 1), only O4 and O7 and the tests and steps they touch. Rev 7 answers round 6
(`docs/plans/active/reviews/2026-10-25-ocr-rotation-round-6.md`, W1–W9). Everything else in the design passed earlier
rounds and is out of scope, as are stage 2 and the stated limits.

1. Hand-execute O7's missing-words guard (run `difflib` and `rapidfuzz.fuzz.ratio` from `.venv` on made-up word
   lists): a moved line, a repeated-word shift, a refrain with misreads, a page stored with OCR errors read correctly,
   a corrected page read with its old misreads, half the page missing, half missing plus desk words, a 4-word page
   with one merged word, an empty stored text, a page where a short word ("a", "I") is dropped and a similar word
   exists elsewhere. Does it refuse a good read or accept a partial one?
2. Hand-execute O4 on a first read with no probe nomination, `OCR_ROTATIONS=0`, a moved book, and a cover with a
   three-letter title.
3. Check that W1–W9 reached every place they apply.

If nothing needs to change, say so plainly. Otherwise report findings as a numbered list, each with severity
(High / Medium / Low), the decision or line, the concrete failure (inputs → outcome), and a suggested fix. Do not edit
any file.
