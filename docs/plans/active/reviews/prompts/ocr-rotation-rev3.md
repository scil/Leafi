Increment round. Review **revision 3** of `docs/plans/active/2026-10-25-ocr-rotation-and-text-block-design.md` as a
design, not as prose. Round 2's findings: `docs/plans/active/reviews/2026-10-25-ocr-rotation-round-2-codex.md`
(R1–R6); rev 3 answers them and adds O3 (the book's paper) and O11 (a spread stored as two pages). Measurements:
`docs/research/2026-10-25-ocr-orientation-and-text-block.md` R§6. The owner's decisions are fixed and out of scope:
an ordered rotations setting with default `270,90,0`; a remembered angle reused unless the result is poor; the book
found by its paper with OpenCV; a spread stored as two pages, each with its own number and revision; an unsure read on
an unchanged frame asks at once; stored pages may re-match.

1. Hand-execute O3 and O4 on concrete inputs: the rehearsal shape (sideways page, a white object touching the book,
   a label, the facing page cut off by the frame edge), a numbered spread `[left, "12", right, "13"]`, a spread where one
   page is a full-page picture, a two-column layout on one page, a picture-book page with two lines above and three
   below a picture, a dim or warm-lit room, a hand over half the page, a white sheet with text beside the book. Where do
   the paper, the pages, their numbers or the kept lines come out wrong?
2. Hand-execute O5 across a session including a timeout: first read at 270°, the book turned 180°, a read that times
   out followed by a new read, a hand over the page, a cover read. Is the lock-plus-`shield` scheme right with
   `asyncio.wait_for` and `run_in_executor` on Python 3.12? Can `_angle` stick wrong or a worker run twice at once?
3. Hand-execute O11 through `PageTracker.find` and `World.acquire_page` / `_from_request` (`leafi/study/harness/world.py`):
   a numbered spread, an unnumbered spread, one side uncertain, a spread whose left page was already stored, a page turn
   after the spread. Does any path store a page twice, return the same page twice, skip a page, or attach a revision
   to the wrong page? Check against `leafi/study/pages.py` (`observations_of`, `match_page`, `create_page`,
   `add_ocr_revision`, `confirm_observations`) and ADR-0010.
4. Check claims against the code: `leafi/services/ocr/`, `leafi/study/page_tracker.py`, `leafi/study/books.py`,
   `scripts/probes/checks.py`, `leafi/envedit.py`, `config/env-schema.json`, `tests/test_env_validators.py`,
   `tests/test_architecture.py` (may `leafi.services.ocr` import `cv2`?).
5. Anything that makes step 2 impossible to land as one commit with the full suite green.

If nothing needs to change, say so plainly. Otherwise report findings as a numbered list, each with severity
(High / Medium / Low), the decision or line, the concrete failure (inputs → outcome), and a suggested fix. Do not edit
any file.
