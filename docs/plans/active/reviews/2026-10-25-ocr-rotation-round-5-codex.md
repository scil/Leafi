# OCR stage 1, design rev 5: round 5 (increment, codex) — 2026-10-25

Reviewer: codex `gpt-6-astra`, effort high, read-only sandbox, prompt `reviews/prompts/ocr-rotation-rev5.md`
(log `.scratch/review/ocr-rotation-rev5-codex.log`). `git log`/`git status` unchanged. O5 passed codex's Python 3.12.10
traces (caller timeout, queued-read cancellation, draining `aclose`, worker exception; peak concurrency one).

| # | Sev | Decision | Finding | Rev 6 answer |
|---|---|---|---|---|
| V1 | High | O7 | Word overlap counts substitutions as missing: a correct read of a stored page with 4 OCR errors in 12 words scores 0.667 and is refused; a recurring misread against 4 corrections likewise, though `add_ocr_revision` keeps verified spans (reproduced). | Measure missing words only: `difflib.SequenceMatcher` opcodes on normalised words, deletions plus the shortfall of replacements; substitutions pass |
| V2 | Medium | O4/O8 | Cover: the winning pass keeps every line and `books.identify` takes the tallest box; upright desk text at 270° is a tall box → chosen as title (`MEMBERSHIP` for `THE BIG STORM`). | Title candidates are the winning pass's wide lines, ranked by quad thickness |
| V3 | Medium | O1/O4 | `OCR_ROTATIONS=0` with a blank frame: no runner-up; "the two highest" raises. | `second = 0` with one pass, stated; tests for evident and empty |
| V4 | Medium | O7 | "say 'page N'" returns the stored page 12 from the database (`world.py:146`) without OCR. | Message names typed `/page` (camera path) and `/page N --text <file>` |
| V5 | Low | O4 | A moved book: the remembered pass is evident but outside the region; the probe nominates the same angle and is discarded → full scan. | When the probe nominates the remembered angle, reuse that pass and publish the new region |

Findings per round: 11, 6, 11, 11, 5. Next: a confirming round on rev 6.
