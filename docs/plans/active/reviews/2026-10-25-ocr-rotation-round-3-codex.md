# OCR rotation and text block, design rev 3: round 3 (increment, codex) — 2026-10-25

Reviewer: codex `gpt-6-astra`, effort high, read-only sandbox, prompt `reviews/prompts/ocr-rotation-rev3.md`
(log `.scratch/review/ocr-rotation-rev3-codex.log`). `git log`/`git status` unchanged after the run. Codex reproduced
#1 on Python 3.12.10, #3 and #6 with the current revision and matching functions, #9 on the proposed synthetic image.
It confirmed that O1's validator wiring answers R6 and that `tests/test_architecture.py` allows `cv2` under
`leafi.services.ocr`.

| # | Sev | Decision | Finding | Source of the finding |
|---|---|---|---|---|
| S1 | High | O5 | `wait_for` cancels `await shield(fut)`, which exits `async with` and releases the lock while the worker runs; two workers ran at once; A never publishes. Fix: an internal task owns lock, worker and publication, shielded as a whole. | O5 |
| S2 | High | O3 | A separate white sheet with more text than the book is tried first and taken as the book; with a remembered angle it can keep a wrong angle `sure`. | O3 paper choice |
| S3 | High | O2–O4, O11 | Partial visibility (clipped facing page, a hand over half a numbered page, uneven light) yields a confident partial page; matched by number, `add_ocr_revision` replaces the full text with three lines. | partly pre-existing (today an occluded page also adds a partial revision); O11 widens it to the clipped facing page |
| S4 | High | O4 | Text-column gap cannot tell two physical pages (30 px apart at h = 10 merge, numbers 12/13 collide again) from a wide two-column page (split). Needs page boundaries from the paper, not from text. | O11 |
| S5 | Medium | O4b | A two-column page merged into one page is read across rows (L1, R1, L2 …). | O4 |
| S6 | High | O11 | Independent matching of the two sides: an unnumbered right side matches the left page just created (same first/last lines and counts) → both sides on one page id. Needs joint resolution. | O11 |
| S7 | High | O11 | Spread continuation has no consumed/exhausted state: unnumbered spreads cycle left/right/left; after 12 → 13 from the database, a request for missing 14 returns 13 again; quiet page turns stay below the frame-diff threshold (2.03 < 6). | O11 |
| S8 | High | O4, O11 | Member lines of any confidence reach `split_number`: a footer misread as "18" at 0.2 takes the numbered-match branch and attaches text to page 18 (ADR-0010 wants a confidently read number). | O4 (also today's `split_number` takes any line) |
| S9 | Medium | O3 | On a uniform white synthetic page the median V is 255, so "pixels brighter than the median" is empty: no seed. | O3 |
| S10 | Medium | O2, O6 | Cover reads skip O3/O4 but O2's score needs pages: cover angle choice undefined. | O2/O6 |
| S11 | Medium | O11 | Confirming an uncertain side does not add its pending OCR text, link its image or complete the spread state. | O11 |

## Shape of the loop

Rounds: 11 findings (rev 1) → 6 (rev 2) → 11 (rev 3). Of round 3's eight Highs, four (S4, S6, S7, S11) come from
O11 and two (S2, S9) from O3's choice of paper; S1 is a mechanism bug with a known fix; S3 and S8 are partly
pre-existing. Per `codex-review`, a loop that keeps producing findings is usually one decision generating them: here
storing a spread as two pages, which needs physical page boundaries, joint identity and a spread lifecycle that the
page flow does not have. Proposed to the owner (2026-10-25): land the single-page design first and design the spread
separately.
