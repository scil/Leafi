Increment round. Review **revision 4** of `docs/plans/active/2026-10-25-ocr-rotation-and-text-block-design.md` as a
design, not as prose. Round 3's findings: `docs/plans/active/reviews/2026-10-25-ocr-rotation-round-3-codex.md`
(S1–S11). Rev 4 is single page: it answers S1, S2, S3, S5, S8, S9, S10, adds the angle probe (O3) and the left/right
question for a spread (O9); S4, S6, S7, S11 belong to a later two-page design and are out of scope. The owner's
decisions are fixed: an ordered rotations setting with default `270,90,0`; the probe; a remembered angle reused unless
the result is poor; the book found by its paper with OpenCV; a spread asked as left or right; an unsure read on an
unchanged frame asks at once; stored pages may re-match.

1. Hand-execute O6's choice with O3, O4 and O5 on: the rehearsal shape (sideways page, the camera clock, a white
   object touching the book, a label, the facing page cut off by the frame edge); a numbered spread with expected 13;
   an unnumbered spread; a picture-book page with two lines above and three below a picture; a hand over half of a
   stored page; a second white sheet with more text than the book, with and without a region hint; a cover read
   sideways. Where do the probe, the paper, the page, its number or the state come out wrong?
2. Hand-execute O6's serialised `read` on Python 3.12: a caller's `wait_for` timeout during the worker, a second read
   meanwhile, cancellation of the second while it waits for the lock, process shutdown with a task in `_tasks`.
3. Hand-execute O8 and O9 through `PageTracker.find`/`choose` and `World._from_request` / `acquire_page`
   (`leafi/study/harness/world.py`) and `leafi/study/controls.py`: does any path write a page or revision it should
   not, lose a learner's answer, or loop? Check the partial rule against `leafi/study/pages.py` (`current_revision`,
   `add_ocr_revision`) and ADR-0010.
4. Check claims against the code: `leafi/services/ocr/`, `leafi/study/page_tracker.py`, `leafi/study/books.py`,
   `scripts/probes/checks.py`, `scripts/probes/p3_ocr_compare.py`, `tests/test_page_tracker.py`, and
   `.venv/Lib/site-packages/rapidocr/` (three instances with `use_det`/`use_rec` off: do they load or skip models; is
   `det(...).boxes` the right field).
5. Anything that makes step 2 impossible to land as one commit with the full suite green.

If nothing needs to change, say so plainly. Otherwise report findings as a numbered list, each with severity
(High / Medium / Low), the decision or line, the concrete failure (inputs → outcome), and a suggested fix. Do not edit
any file.
