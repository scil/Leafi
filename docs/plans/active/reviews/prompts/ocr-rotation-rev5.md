Increment round. Review **revision 5** of `docs/plans/active/2026-10-25-ocr-rotation-and-text-block-design.md` as a
design, not as prose. Rev 5 is stage 1 (owner, 2026-10-25): ordered rotations, the angle probe, the remembered angle,
the wide-box score, skew order, confident page numbers and a word-coverage guard on revisions. The book's paper, desk
text and spreads are stage 2 and out of scope; so are the stated limits under "Known limits of stage 1". Earlier
rounds: `docs/plans/active/reviews/2026-10-25-ocr-rotation-round-4-codex.md` (U1–U11) and the files it cites.

1. Hand-execute O2–O4 on: the rehearsal shape (sideways page, the camera clock, desk text); a session where the first
   read is at 270°, then the book is turned 180°, then moved across the desk, then a hand covers it, then a cover is
   read sideways next to upright desk text. Where do the probe, the remembered angle, the region check or the state
   come out wrong, beyond the stated limits?
2. Hand-execute O5 on Python 3.12: a caller's `wait_for` timeout during the worker, a second read meanwhile, its
   cancellation while waiting, `aclose` with a running and a queued read, a worker that raises.
3. Hand-execute O7 and O8 through `PageTracker.read`/`find` and `World._from_request`/`acquire_page`
   (`leafi/study/harness/world.py`): the coverage guard on a matched page (a partial read, a reformatted revision, a
   corrected revision, a better OCR of a page whose stored text has OCR errors), the number rule, the help path. Does
   any path write what it should not, refuse a good read, or loop? Check against `leafi/study/pages.py` and ADR-0010.
4. Check claims against the code: `leafi/services/ocr/`, `leafi/study/page_tracker.py`, `leafi/study/books.py`,
   `leafi/runner.py`, `scripts/probes/checks.py`, `scripts/probes/p3_ocr_compare.py`, `tests/test_page_tracker.py`,
   `tests/test_ocr_pipeline.py`, `leafi/envedit.py`, `config/env-schema.json`, `tests/test_env_validators.py`.
5. Anything that makes step 2 impossible to land as one commit with the full suite green.

If nothing needs to change, say so plainly. Otherwise report findings as a numbered list, each with severity
(High / Medium / Low), the decision or line, the concrete failure (inputs → outcome), and a suggested fix. Do not edit
any file.
