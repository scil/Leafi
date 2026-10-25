# Page OCR: orientation, the page's text block, skewed reading order (research, 2026-10-25)

Serves `docs/plans/active/2026-10-25-ocr-rotation-and-text-block-design.md`. Checked 2026-10-25. Tier 1 = the
owner's docs, source or release notes; tier 2 = maintainer-run registries; "reported" = community. Local measurements
are on the rehearsal snapshot of 2026-10-25 09:43 (not committed; it shows the home).

## R§1 How mature tools choose page orientation

- OCRmyPDF runs Tesseract OSD (`--psm 0`) and rotates only when `Orientation confidence` ≥
  `--rotate-pages-threshold` (default 14.0, "arbitrary units"; the cookbook calls it conservative, 2.0 rotates more
  with more false positives) [S1–S4].
- Tesseract OSD's confidence is a **margin**: per orientation it sums `log p` over blobs; confidence = best − second.
  Blobs under 10 px tall or with aspect > 2 are skipped; too few characters → no decision [S5].
- docTR applies its page-orientation classifier only above `min_confidence` (0.2); below it the angle stays 0 [S6].
- Neither compares absolute OCR scores across rotations; both demand a best-versus-runner-up margin or a floor.

## R§2 Page-orientation classifiers (an alternative to reading every rotation)

- PaddleOCR 3.x `PP-LCNet_x1_0_doc_ori`: 0/90/180/270 for a whole document image, top-1 99.06 %, 7 MB, ~1–3 ms CPU;
  Apache-2.0; first stage of the PaddleOCR pipeline [S7, S8]. ONNX exports exist only as community uploads [S9].
- RapidAI `rapid-orientation` 0.0.11 (2026-02-03): document-image 0/90/180/270, PaddleClas PULC model as ~6.5 MB ONNX
  in the wheel, Apache-2.0 [S10, S11].
- RapidOCR 3.10.0 (2026-10-08) and `main` (2026-10-25) have no page-orientation stage; `Cls` is the text-line
  0/180 classifier, `cls_thresh` 0.9 [S12, S13]. Unreleased on `main`: EXIF orientation (#755), cls fix for long
  lines (#748), resize-ratio fix (#761) [S13].
- Fit: unmeasured on a wide desk shot where the page is ~20 % of the frame (training data are document photos and
  scans). Deferred, not rejected: a candidate to cut four passes to one once captures exist (design O6).

## R§3 Keeping the main text block

- Tesseract advises cropping to the text area (~10 px border); large borders hurt [S14]. OCRmyPDF: no region step.
- docTR `resolve_blocks` clusters line boxes (`fclusterdata`, 0.1 relative distance); EasyOCR `get_paragraph`
  (`x_ths=1`, `y_ths=0.5`) grows groups by multiples of the mean box height [S15, S16]. Neither picks a dominant
  block; PaddleOCR uses layout/unwarping models (UVDoc, PP-Structure).
- No tier-1 pipeline selects one block from detection boxes; clustering in median-line-height units is the closest
  precedent.

## R§4 Reading order for skewed lines

- PaddleOCR `sorted_boxes` / PaddleX `SortQuadBoxes` and RapidOCR 3.10: sort by first vertex, swap neighbours when
  |dy| < 10 px (fixed); no angle handling [S17, S18, local].
- docTR `_sort_boxes`: estimates the page angle, rotates box centres by −angle, groups rows within
  `median_height / 2`; `estimate_orientation` uses `median_low` of elongated contour angles (w/h > 3) [S6, S15].
- Tesseract: segmentation degrades on skew; deskew first [S14].

## R§5 Detector scaling

- RapidOCR 3.10: `Det.limit_type min`, `limit_side_len 736`, `Global.max_side_len 2000` [S12, local]. A 1920×1080
  frame is not downscaled (det at ~1920×1088). A crop whose short side < 736 is upscaled to 736 automatically.
- No tier-1 evidence that upscaling small text helps PP-OCR detection; Tesseract asks for ≥ 300 DPI [S14, S19].

## Local measurements (rapidocr 3.10.0, PP-OCRv6, this PC)

| Pass | all confident chars | wide boxes only | time |
|---|---|---|---|
| 0° / 90° / 270° / 180°, `use_cls` on | 324 / 191 / 427 / 413 | 7 / 191 / 427 / 0 | 1.8–2.0 s |
| 0° / 90° / 270° / 180°, `use_cls` off | 11 / 0 / 427 / 413 | 7 / 0 / 427 / 0 | 1.1–1.6 s |

- Why the scores tie: `get_rotate_crop_image` turns crops with h/w ≥ 1.5 by 90°, `Cls` flips 180°, so lines read at
  almost any frame rotation; only order and short lines differ.
- Page crop re-read at 270°, ×1/×2/×3: 13/12/13 confident of 14 lines; no word better than the full-frame pass,
  some worse (`siser`, `poinis`). Keeping only the main block's lines of the full pass gave the same 14 lines and
  dropped all 8 desk lines.
- Residual errors (`noodle`, `necdle`, `grosned`) appear in every variant: resolution, a camera-placement matter.

## R§6 Finding the book's paper (design rev 3)

- OpenCV 5.0.0 (installed with rapidocr) provides the primitives: HSV conversion, thresholding incl. Otsu,
  morphology, connected components with stats, contours and point-in-polygon [S20–S22].
- Measured on the rehearsal frame at ¼ scale (17–40 ms): Otsu on V puts the threshold at 130 and marks 72 % of the frame
  (the light desk) as paper. A colour model seeded from the non-ink pixels between the body lines (V 235, S 7; desk V
  101, S 18) with V ≥ V−25, S ≤ S+20, close 1.5·h, open 2·h → one component holding all 14 body lines, 15–16 % of the
  frame, both pages of the open book. A white power bank touching the book stays joined (opening up to 4·h).
- Paper share of a 0.5·h ring around each line: book lines 0.72–0.99, "POWER BANK" 0.44, medicine label 0.01.
- Not used: contour → quadrilateral "document scanner" pipelines (reported, tier 4) assume a flat sheet with a visible
  outline; a hand or a touching object breaks the quad.

## Sources

| # | URL | Tier | source-date | checked |
|---|---|---|---|---|
| S1 | https://github.com/ocrmypdf/OCRmyPDF/blob/main/src/ocrmypdf/_pipeline.py | 1 | main | 2026-10-25 |
| S2 | https://github.com/ocrmypdf/OCRmyPDF/blob/main/src/ocrmypdf/cli.py | 1 | main | 2026-10-25 |
| S3 | https://github.com/ocrmypdf/OCRmyPDF/blob/main/src/ocrmypdf/_defaults.py | 1 | main | 2026-10-25 |
| S4 | https://ocrmypdf.readthedocs.io/en/latest/cookbook.html | 1 | latest | 2026-10-25 |
| S5 | https://github.com/tesseract-ocr/tesseract/blob/main/src/ccmain/osdetect.cpp | 1 | main | 2026-10-25 |
| S6 | https://github.com/mindee/doctr/blob/main/doctr/models/_utils.py | 1 | main | 2026-10-25 |
| S7 | https://paddleocr.ai/latest/en/version3.x/module_usage/doc_img_orientation_classification.html | 1 | 3.x | 2026-10-25 |
| S8 | https://paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html | 1 | 3.x | 2026-10-25 |
| S9 | https://huggingface.co/monkt/paddleocr-onnx | reported | undated | 2026-10-25 |
| S10 | https://pypi.org/project/rapid-orientation/ | 2 | 0.0.11, 2026-02-03 | 2026-10-25 |
| S11 | https://github.com/RapidAI/RapidOrientation | 1 | main | 2026-10-25 |
| S12 | https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/config.yaml | 1 | main | 2026-10-25 |
| S13 | https://github.com/RapidAI/RapidOCR/releases | 1 | v3.10.0, 2026-10-08 | 2026-10-25 |
| S14 | https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html | 1 | undated living page | 2026-10-25 |
| S15 | https://github.com/mindee/doctr/blob/main/doctr/models/builder.py | 1 | main | 2026-10-25 |
| S16 | https://github.com/JaidedAI/EasyOCR/blob/master/easyocr/utils.py | 1 | master | 2026-10-25 |
| S17 | https://github.com/PaddlePaddle/PaddleOCR/blob/main/tools/infer/predict_system.py | 1 | main | 2026-10-25 |
| S18 | https://github.com/PaddlePaddle/PaddleX (common/sort_boxes.py, develop) | 1 | develop | 2026-10-25 |
| S19 | https://paddleocr.ai/v3.0.0/en/version3.x/module_usage/text_detection.html | 1 | 3.0.0 | 2026-10-25 |
| S20 | https://docs.opencv.org/5.x/d7/d4d/tutorial_py_thresholding.html | 1 | 5.x living docs | 2026-10-25 |
| S21 | https://docs.opencv.org/5.x/d9/d61/tutorial_py_morphological_ops.html | 1 | 5.x living docs | 2026-10-25 |
| S22 | https://docs.opencv.org/5.x/d3/dc0/group__imgproc__shape.html (`connectedComponentsWithStats`, `findContours`, `pointPolygonTest`) | 1 | 5.x living docs | 2026-10-25 |
| local | `.venv/Lib/site-packages/rapidocr` (config.yaml, utils/process_img.py, main.py, utils/load_image.py); `cv2` 5.0.0, numpy 2.4.6 | 1 | 3.10.0 | 2026-10-25 |
