# OCR rotation and text block, design rev 2: round 2 (increment, codex) — 2026-10-25

Reviewer: codex `gpt-6-astra`, effort high, read-only sandbox, prompt `reviews/prompts/ocr-rotation-rev2.md`
(log `.scratch/review/ocr-rotation-rev2-codex.log`). `git log`/`git status` unchanged after the run. Codex ran each
case in memory.

| # | Severity | Finding | Proposed answer |
|---|---|---|---|
| R1 | High | O3 cannot tell a desk label column from a page column when typography matches (two 5-line pages + a 6-line label → all three kept). With a remembered angle, a stationary label keeps O5's fast path `sure` after the book is turned 180° or covered, so `_angle` sticks on the wrong angle. | Structural; see below. Cached acceptance must prove the page reads, not any column. |
| R2 | High | `wait_for` cancels the await but not the executor worker: a timed-out read A finishing after a newer read B overwrites `_angle`; a new read can enter the backend while A still runs. | Worker returns (result, angle) and never writes `_angle`; the async side publishes it for the current request only; an `asyncio.Lock` held until the worker future really finishes (`shield`), a read arriving while busy waits or returns `unavailable`. Test timeout → newer read → late completion. |
| R3 | High | Two lines above a picture are a component below the 3-line minimum, dropped before the column merge and outside the 6·h band → an incomplete page reads `sure`. | Merge components into columns first, apply the 3-line minimum to the merged column; tests two+three and two+two. |
| R4 | High | A spread flattened into one text: `split_number` (`page_tracker.py:47`) returns the last number (13) and leaves "12" in the reading text; both pages' text is stored as page 13. | Owner decision (spread policy, below). |
| R5 | Medium | O5's fast path skips O2's absolute floor (score ≥ 20): the same sparse input is `no text` on a scan and `sure` from the remembered angle. | One evidence predicate for both paths; only the comparison with other angles is skipped on the cached path. |
| R6 | Medium | Step 2 misses `tests/test_env_validators.py` (`CONSUMERS`, `SENTINELS`) for the new validator, and `test_low_confidence_recaptures_once_then_asks_the_learner` asserts two reads on an unchanged frame. | Add both to step 2; keep a changed-frame test that proves the second read. |

## Shape of the round

R1 and R4 come from one source, as T1/T2/T4/T11 did in round 1: from line boxes alone, O3 has to guess where the book
is and how many pages it holds. Two rounds have now patched instances of it. Per `codex-review`, the next move is
structural: decide the page region by a different signal, and decide what a spread *is* to page identity (one page
row or two). Both are the owner's to choose (asked 2026-10-25).
