Design round 1. Review **revision 1** of `docs/plans/active/2026-10-25-ocr-rotation-and-text-block-design.md` as a
design, not as prose. Its research and measurements are in `docs/research/2026-10-25-ocr-orientation-and-text-block.md`.
The owner's requests are fixed and out of scope: every read tries several rotations and keeps the best; the rotations
to try are a setting; the page is isolated from the desk.

1. Check the design's claims against the code as it is: `leafi/services/ocr/__init__.py` (`OcrLine`, `OcrResult`,
   `drop_overlay`, `reading_order`, the `Ocr` protocol), `leafi/services/ocr/rapidocr.py` (`engine`, `to_result`,
   `RapidOcr._read`), `leafi/services/ocr/mock.py`, `leafi/study/page_tracker.py` (`read`, `find`),
   `leafi/study/books.py` (`identify`), `scripts/probes/checks.py` (`ocr`, `_ocr_parameters`), `leafi/core/config.py`
   (`ocr_auto_rotate`), `config/env-schema.json` (`OCR_AUTO_ROTATE`, a `list` key such as `SUPERVISE`),
   `leafi/envedit.py` (`normalise_list`, `agreement`), `tests/test_ocr_pipeline.py`, `tests/test_envedit.py`, and the
   installed engine `.venv/Lib/site-packages/rapidocr/` (`main.py` `__call__`/`update_params`, `utils/process_img.py`
   `get_rotate_crop_image`, `config.yaml`).
2. What will be hard to get right, and what will keep going wrong? In particular: hand-execute O2's score and margin
   and O3's `text_block` on concrete inputs — a sideways page on a busy desk, an upright page, a picture-book page with
   text above and below an illustration, a two-page spread, a page with a large chapter heading, a page of short
   one-word lines, a blank or hand-covered frame — and say where the choice or the kept lines come out wrong. Is
   turning the line classifier off (`Global.use_cls = False`) safe for every caller of the engine, and does passing
   `use_cls` per call (or `update_params`) leave state behind? Does `rotation_sure` reach every place that decides
   "low confidence" (`PageTracker.read` and `find`)? Is O4's skew estimate from `quad[0] → quad[1]` right for the
   quads rapidocr returns after rotation? Does retiring `OCR_AUTO_ROTATE` break the settings page, `agreement`, or an
   owner's `.env` that still sets it?
3. Anything the tests list misses, and anything that makes the implementation impossible to land as one commit with
   the full suite green.

If nothing needs to change, say so plainly. Otherwise report findings as a numbered list, each with severity
(High / Medium / Low), the decision or line, the concrete failure (inputs → outcome), and a suggested fix. Do not edit
any file.
