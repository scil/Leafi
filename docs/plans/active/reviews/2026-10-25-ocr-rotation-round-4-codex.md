# OCR rotation and text block, design rev 4: round 4 (increment, codex) — 2026-10-25

Reviewer: codex `gpt-6-astra`, effort high, read-only sandbox, prompt `reviews/prompts/ocr-rotation-rev4.md`
(log `.scratch/review/ocr-rotation-rev4-codex.log`). `git log`/`git status` unchanged. Codex traced on Python 3.12.10
with synthetic inputs and an in-memory database; it confirmed that rapidocr instances with a stage off skip that
stage's model and that detection-only output exposes `.boxes`, and that O6's shielded task survives a caller timeout
and the cancellation of a waiting second read.

| # | Sev | Decision | Finding | Area |
|---|---|---|---|---|
| U1 | High | O4/O6 | Book turned 180° beside a printed sheet: the book offers no readable candidate, so the sheet is "the only sheet"; the hint falls back to it; `sure`, and its region is remembered. | which paper is the book |
| U2 | High | O5 | Two pages with a 30 px gap at h = 10 form one group: numbers 12/13 collide, page 12's text stored inside page 13; no `sides`, so O9 never runs. | spread inside single page |
| U3 | High | O8 | The partial rule counts lines: six half-width lines pass against six full ones; 48 words became 24 in `current_text()` (reproduced). | partial revisions |
| U4 | High | O2/O6 | A pass with sides scores 0 (no `page`): a clear spread at 0° loses to an invalid 270° by ordering → `no text`. | spread inside single page |
| U5 | High | O8/O9 | Sides are routed before `needs_help`: an `unsure` orientation can be stored after a number match or a left/right answer; the weaker side is not validated. | spread inside single page |
| U6 | Medium | O5 | Staggered captions (upper left, lower right) do not overlap enough to merge; the upper two lines are lost. | columns |
| U7 | Medium | O8 | The help message asks for the first line, but `World.acquire_page` only consumes `page` controls: the answer becomes `noop` and the prompt repeats (reproduced; also today). | help path (pre-existing) |
| U8 | Medium | O9 | `choose()` can return `uncertain`; the yes/no confirmation after a side answer is not specified. | spread inside single page |
| U9 | Medium | O7 | Cover: one upright desk line at the remembered angle ends the search; the sideways cover is never compared. | covers |
| U10 | Medium | O7/O8 | Flat mock `OcrResult(lines)` has no `page`; `MockOcr.read(frame)` lacks `purpose`. | compatibility |
| U11 | Medium | O6 | Loop shutdown cancels the backend task directly: lock released with the worker running; no consumer for a task's exception. | serialisation |

## Shape of the loop

Findings per round: 11, 6, 11, 11. Four of round 4's eleven (U2, U4, U5, U8) come from handling a spread inside the
single-page design, U1 again from choosing the book's sheet. `codex-review`: budget five rounds; a loop that keeps
producing findings is one decision generating them. Two decisions generate most of them: seeing the book in a wide
shot of a busy desk (paper identity, desk text, partial views), and recognising a spread. Proposed to the owner
(2026-10-25): stage the work — stage 1 without paper or spread logic, or a fixed reading zone set once in the console.
