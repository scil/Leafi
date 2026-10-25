# OCR rotation and text block, design rev 1: round 1 comparison (2026-10-25)

Design: `docs/plans/active/2026-10-25-ocr-rotation-and-text-block-design.md` rev 1. Prompt:
`reviews/prompts/ocr-rotation-rev1.md`. Reviewers, run in parallel, none reading another:
- **codex**: `gpt-6-astra`, effort high, read-only sandbox (log `.scratch/review/ocr-rotation-rev1-codex.log`);
  11 findings (7 High, 4 Medium); ran synthetic O2/O3 inputs in memory. `git log`/`git status` unchanged after the run.
- **Claude**: a fresh Claude Opus 5.5 agent on the same prompt file; 13 findings (3 High, 7 Medium, 3 Low); ran O3/O4
  on synthetic boxes and O2 with the real engine on in-memory PIL pages.
- **code-plan-review**: a fresh Claude Opus 5.5 agent walking the catalog; 4 owner decisions, 5 "most severe"
  (G4.4, G5.1, F1.1, K3.1, I1.1).

Verified by the author: `envedit.empty_rule(str)` returns `"empty"` (`envedit.py:64–70`) and `agreement` compares it
(`envedit.py:205`), so T6 holds.

## Themes

| # | Theme | codex | Claude | cpr | Severity | Answer in rev 2 |
|---|---|---|---|---|---|---|
| T1 | Spread: runs split against "the previous line" in top-edge order, so interleaved pages become singleton runs; "main" is the longest single line or a compact desk label (Claude ran: label kept, both pages dropped) | 5 | 1 | Dec 2 | High | O3 restated: runs are connected components (overlap ≥ 30 % of the narrower line, gap < 2.5·h, against any member); spread policy is the owner's (Q1) |
| T2 | Page number and chapter heading fall outside the 1.5·h margin or the height band → `split_number` loses the printed number, `match_page` its first key | 4 | 2 | G4.4 | High | Membership band: inside the column's x-range, lines within k·h above/below the block are page lines (k measured in O6); a `NUMBER_RE` line in the column is always kept; only lines outside the column count as desk |
| T3 | `rotation_sure` does not reach `find()`; its default is unstated (mock results would all be unsure) | 6 | 6 | F1.1 | High | One predicate `OcrResult.needs_help(min_conf)` used by `read` and `find`; `rotation_sure` defaults to True; test through `find` (no page written) |
| T4 | Whole-frame score lets upright desk text win the angle, sure | 2 | 4 | — | High | Score each angle on its own text block (O3 runs per pass), not the whole frame |
| T5 | Short-text pages (one line, one-word lines) are never sure; recapturing a still scene repeats the same unsure result (~12 s) | 7 | 3 | F1.2, Dec 4 | High | States `no text` / `unsure` / `sure`; sure = second ≤ 0.5·best (floor only when second > 0); unsure recaptures only if `frame_diff` ≥ threshold (Q3) |
| T6 | `empty → error` breaks `agreement` (suite red, editor read-only); `ROTATION_ANGLES` must be strings; hand-edited `.env` bypasses `normalise_list` | 1 | 7 | H1.1 | High | `"empty": "empty"` + an error-severity validator; `ROTATION_ANGLES = ("0","90","180","270")`; `RapidOcr` parses defensively (unknown ignored, empty → all four, logged) |
| T7 | O4 row tolerance (and O3's height band) use the axis-aligned box height, inflated by skew (Claude ran: lines 2/3 and 4/5 swapped) | 8 | 5 | K1.1 | Medium | Line height from the quad (`|q0 − q3|`), box height without a quad; skew median over body lines only |
| T8 | `upright_score` after O3 differs from the choosing score; the console keeps its own rotation loop (8 passes, removed constants) | 11 | 8 | H3.2, I1.1 | Medium | `_read` records per-pass diagnostics on the result; the console prints them and no longer runs the engine or re-sorts |
| T9 | `__call__(use_cls=…)` persists via `update_params`; `p3_ocr_compare` changes meaning | 9 | 10 | — | Medium | Build-time `Global.use_cls=False` only; never pass per-call overrides to the backend's engine; probes build their own engine |
| T10 | Retiring `OCR_AUTO_ROTATE`: a legacy `false` silently becomes four angles | 10 (Medium) | 11 (safe) | unlikely | Low | Split: the owner's `.env` does not set it (checked); the settings page lists a stale key as Unknown. Rev 2 adds a one-line warning at start when the key is present; retarget `test_envedit.py:73` to another bool |
| T11 | Sparse or hand-covered frame keeps every line (one label can be "sure"); a distant same-column label joins; the height filter can empty the body | 3, 4c | — | — | High | `no text` state below the floor; block requires ≥ 3 body lines else `needs_help`; membership bounded by the band of T2; empty body → `no text` |
| T12 | Stored pages: first/last-line observations change → old pages re-match as uncertain or duplicate | — | — | G5.1, Dec 3 | Medium | Owner decision (Q4); named in rev 2 |
| T13 | `performance.md` budgets OCR ≤ 3 s; the 15 s timeout is not enforced | — | — | K3.1, Dec 1 | Medium | Owner decision on the budget (Q2); enforce `asyncio.wait_for` 15 s around `ocr.read` |
| T14 | `to_result` already orders lines; O3 must run before the order step → split `to_result`; quads as float tuples (dataclass equality in `drop_overlay`) | — | 9 | — | Medium | Stated in rev 2 |
| T15 | `block=` is a mechanism flag the caller must understand; O3 is RapidOCR-only | — | — | H3.3 | Low | `read(frame, purpose="page" \| "cover")`; `text_block` lives beside `drop_overlay` in `leafi.services.ocr` |
| T16 | The `rapidocr==3.10.0` pin now carries O2's dependence on the 1.5 crop rule; hardware test of rotated fixtures | — | 12 | H6.3 | Low | Reason beside the pin; `test_hardware.py:74` named; rotated-fixture hardware case |
| T17 | Non-0° passes re-encode JPEG q92, 0° reads the original: a small bias | — | — | outside | Low | Rotate losslessly and pass the same encoding to every pass |
| T18 | No run-time signal that text is too small (the residual errors) | — | — | K4.2 | Low | Console prints the body's median line height in px |
| T19 | O6 vs step 3 ordering; O6 criteria miss "desk dropped", page number, heading | — | 13 | K4.1 | Low | Code lands with named constants and default `0,90,180,270`? → owner (Q2); O6 criteria extended |
| T20 | Missing tests: `purpose` forwarded through the executor, blank frame, two runs in different columns | — | 12 | — | Low | Added to the list |

Overlap: T1, T2, T3, T6 found by all three; T4, T5, T7, T8, T9 by two. Only codex: T11. Only Claude: T14. Only
code-plan-review: T12, T13, T15, T17, T18. No false positives found; T10 is a severity split.

## Shape of the round

T1, T2, T4 and T11 rhyme: each is O3's block selection being underspecified or applied at the wrong point. Per
`codex-review`, rev 2 restates O3 as one executable statement (connected components → block per pass → score per
block → membership band) and the next round hand-executes it on the named inputs, rather than patching each instance.

## Questions for the owner (asked 2026-10-25)

- Q1 Two-page spread: keep both pages (left then right), ask the learner, or the left page.
- Q2 Cost: four angles ≈ 5–6 s per page against the 3 s budget.
- Q3 Unsure on a still frame: recapture or ask at once.
- Q4 Pages already stored may re-match as uncertain or new.
