Increment round. Review **revision 2** of `docs/plans/active/2026-10-25-ocr-rotation-and-text-block-design.md` as a
design, not as prose. Round 1's findings and how rev 2 answers them: `docs/plans/active/reviews/2026-10-25-ocr-rotation-round-1-comparison.md`.
The owner's decisions are fixed and out of scope: rotations as an ordered setting with default `270,90,0`; the first
read finds the best angle and later reads reuse it unless the result is poor; a two-page spread keeps both pages;
an unsure read on an unchanged frame asks the learner at once; stored pages may re-match.

1. Hand-execute O3's `text_block` and O2's choice on concrete inputs: the rehearsal shape (one sideways page, desk
   text, the facing page's edge), an interleaved two-page spread with a 6-line label beside it, a picture-book page
   with text above and below a picture, a page with a printed number 4 line heights below and a chapter heading above,
   a page of short one-word lines, a hand-covered frame leaving one label. Where does the kept set, the order, the
   state or the chosen angle come out wrong?
2. Hand-execute O5 across a session: first read at 270°, then the book turned 180°, then 90°, then a hand over the
   page, then a cover read. Does `_angle` ever stick on a wrong angle, or cause a needless scan?
3. Check rev 2's claims against the code: `leafi/envedit.py` (validators, `agreement`, `empty_rule`, `normalise_list`),
   `leafi/core/envschema.py`, `config/env-schema.json`, `leafi/services/ocr/__init__.py`, `leafi/services/ocr/rapidocr.py`,
   `leafi/services/ocr/mock.py`, `leafi/study/page_tracker.py`, `leafi/study/books.py`, `scripts/probes/checks.py`,
   `leafi/doctor.py`, and `.venv/Lib/site-packages/rapidocr/` (`utils/load_image.py` accepts a PIL image).
   In particular O6's `wait_for` around `run_in_executor` and O1's validator wiring.
4. Anything that makes step 2 impossible to land as one commit with the full suite green.

If nothing needs to change, say so plainly. Otherwise report findings as a numbered list, each with severity
(High / Medium / Low), the decision or line, the concrete failure (inputs → outcome), and a suggested fix. Do not edit
any file.
