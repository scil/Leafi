---
status: accepted
date: 2026-10-25
revision: 7
---

# Page OCR stage 1: ordered rotations, an angle probe, a remembered angle, skew order, guarded revisions (design)

Owner request (2026-10-25): OCR of the desk camera reads poorly; reads should try several rotations and keep the best,
and the rotations to try are a setting. Research: `docs/research/2026-10-25-ocr-orientation-and-text-block.md` (R§n).
Measurements: the rehearsal snapshot of 2026-10-25 09:43 (`cache/checks/snapshot.jpg`, not committed: it shows the
owner's hand and a medicine label with a name). Today's behaviour: `leafi/services/ocr/rapidocr.py::RapidOcr._read`
(0° first; 90/270/180 only when 0° gives fewer than `MIN_GOOD_LINES` = 8 confident lines; the first orientation at or
above 8 wins) under `OCR_AUTO_ROTATE`.

History: four review rounds (`reviews/2026-10-25-ocr-rotation-round-1-comparison.md`, `…-round-2-codex.md`,
`…-round-3-codex.md`, `…-round-4-codex.md`; findings 11, 6, 11, 11). Most findings came from two parts: finding the
book in a wide shot of a busy desk (paper, desk text, which sheet) and recognising a spread. **Rev 5 is stage 1**
(owner, 2026-10-25): only the parts that fix the measured failures — wrong rotation kept, line order, slow scans,
unreliable page numbers, partial revisions. **Stage 2**, a design of its own after the O8 captures: the book's paper,
desk text, a spread (rev 3–4's O3/O4/O9 and rounds 2–4's open findings are its starting material).

Rev 5 → codex (`reviews/2026-10-25-ocr-rotation-round-5-codex.md`, V1–V5); **rev 6** answers them in O4, O7, O8.

Rev 6 → the confirming round (`reviews/2026-10-25-ocr-rotation-round-6.md`, W1–W9; codex hit its quota mid-run,
a fresh Claude completed it); **rev 7** answers W1–W9 in O4, O7 and the steps.

Status: rev 7, **implemented** (step 2, 2026-10-25). The owner skipped the scoped confirming round
(`reviews/prompts/ocr-rotation-rev7.md` stays ready for a code review). Full suite green (1122 passed); the OCR model
tests pass with `LEAFI_HW_TESTS=1`; on the rehearsal frame the probe chose 270° (194 vs 0), one full pass, `sure`.
Step 3 (O8 captures) and step 4 (stage 2, U7) are open.

## What the measurement showed

Rehearsal frame (book lying sideways, page ~20 % of a 1920×1080 frame, text lines ~15 px tall):

| Pass | all confident chars | wide boxes only | time |
|---|---|---|---|
| 0° / 90° / 270° / 180°, line classifier on | 324 / 191 / 427 / 413 | 7 / 191 / 427 / 0 | 1.8–2.0 s |
| 0° / 90° / 270° / 180°, line classifier off | 11 / 0 / 427 / 413 | 7 / 0 / 427 / 0 | 1.1–1.6 s |

- Detection alone 0.27 s, a full pass 1.0–1.4 s: recognition is the cost.
- Angle probe (detect once at 0°, recognise a few line crops at two angles): 2 longest boxes → the camera clock won,
  0° (wrong); 6 longest → 5 tall → 90°/270° → 270° 194 vs 32, 0.82 s including detection.
- At 270° the slight skew put "compass in the middle of the room." before "Suddenly, my sister pointed to a big".

Engine facts (rapidocr 3.10.0, tier 1; confirmed by codex in rounds 1–4): crops with height/width ≥ 1.5 are turned 90°
and the line classifier flips crops, so lines read at almost any frame rotation; the classifier off does not stop the
90° turn, hence wide boxes only. A 1920×1080 frame is not downscaled. Quads come top-left, top-right, bottom-right,
bottom-left in the coordinates of the image passed in. `__call__` overrides persist (`update_params`), so each
configuration is its own engine instance; an instance with a stage off does not load that stage's model;
detection-only output exposes `.boxes`. `LoadImage` accepts a PIL image.

Known limits of stage 1 (stage 2's work): desk text that reads well at the page's angle stays in the page text, as
today; a spread is read as one page, as today; `noodle`/`necdle` are a resolution matter (O8 prints the line height).

## Decisions

**O1 `OCR_ROTATIONS`, an ordered list [setting].** Replaces `OCR_AUTO_ROTATE`. Manifest `type: text` (the `list` type
re-sorts), default `270,90,0`, `"empty": "empty"`, reader `leafi`, `Settings.ocr_rotations: str`, validator `{fn:
leafi.services.ocr.rapidocr:parse_rotations, severity: error, consumer: leafi.services.ocr.rapidocr:RapidOcr}`,
registered in `tests/test_env_validators.py` (`CONSUMERS`, `SENTINELS`). `parse_rotations(text) -> tuple[int, ...]`:
comma-separated, stripped, each in `ROTATION_ANGLES = ("0", "90", "180", "270")`, no repeats, at least one;
`ValueError` names the rule, never the value. A bad hand-edited value: `RapidOcr.__init__` logs one warning and uses
the default. `OCR_AUTO_ROTATE` retired (manifest, `Settings`, `.env.example`; `test_envedit.py:73` moves to another
leafi bool with `empty: error`); a `.env` still holding it gets one `leafi doctor` line. `MIN_GOOD_LINES` and
`ROTATIONS` go. Provenance: *original*.

**O2 Engines, one pass and its score [rule].** Three engine instances, built once, never given per-call overrides:
`full` (`Global.use_cls = False`), `det` (also `use_rec = False`), `rec` (also `use_det = False`). The frame is decoded
once; a pass at angle *a* gets it turned losslessly (`Image.transpose`, 0° included) as a PIL image.

```
lines = drop_overlay(lines_of(full(image_a)))           # OcrLine with quad (tuples of float)
body  = lines with conf ≥ 0.85, len(text) > 3, box width > box height
score = Σ len(l.text) · l.conf over body
evident(p) = len(p.body) ≥ 3 and p.score ≥ 20 and confidence(p.lines) ≥ OCR_MIN_CONFIDENCE    # one predicate
```

The score counts wide boxes only, because at a frame rotation 90° off the page lines are tall boxes the engine still
reads; with the classifier off, a frame 180° off reads as garbage. Provenance: *original*, from the rapidocr crop rule.

**O3 The angle probe [mechanism; owner].**

```
boxes = det(image_0).boxes, line-like only (long side ≥ 4 × short side)
take  = the PROBE_K = 6 longest
pair  = (90, 270) if most of `take` are tall else (0, 180);  cand = [a in pair if a in OCR_ROTATIONS]
for a in cand: crops = warp(box) turned by a, keeping those that end up wide
               s[a] = Σ len · conf over rec(crop) texts with conf ≥ 0.85, len > 3, not the camera clock
probe = the best a in cand when s[a] ≥ 20 and (len(cand) == 1 or the other ≤ 0.5 · s[a]); else none
```

The probe only nominates: its full pass must be `evident`. Provenance: *original* (owner's suggestion); the crop warp
*adopted* from rapidocr's `get_rotate_crop_image` without its automatic 90° turn.

**O4 Choosing, and the remembered angle [state; owner].** `RapidOcr` holds `_angle: int | None` and `_region` (the
bounding box of the last sure read's body lines, in the coordinates of the image turned by that angle — the only
angle it is ever checked at), in memory only. In the region check, `h` is the median quad height of the pass's body
lines. The worker `_read(frame,
purpose, angle, region)` is pure and returns the result with the angle and region it chose.

```
page read:
  tried = []
  if angle is set:
      p = pass(angle); tried += [p]
      if evident(p) and ≥ half of p.body's centres lie in region grown by 2·h: return sure(p)   # the book is still there
  a = probe(image)
  if angle is not None and a == angle and evident(tried[0]): return sure(tried[0])   # the book moved (V5, W4)
  if a is set and a != angle: p = pass(a); tried += [p]; if evident(p): return sure(p)
  tried += [pass(x) for x in OCR_ROTATIONS if x not in angles of tried]
  best = the highest score among tried; tie → the earlier angle in OCR_ROTATIONS
  second = the next highest score, or 0 when only one pass was made (V3)
  state = "no text" if not evident(best) else "sure" if second ≤ 0.5 · best else "unsure"
  sure(p) publishes p's angle and p's own region (the region of the new read, not the old one)
cover read (`books.identify`): every angle in OCR_ROTATIONS; cover score = Σ len · conf over wide lines with
  conf ≥ 0.5, no length bar (short or stylised titles: "Zog", W5); the highest score wins, tie → the earlier angle in
  OCR_ROTATIONS, all zero → no title (`BookGuess("none")`, as today for an unreadable cover); no probe, no remembered
  state, never publishes (U9). The result's lines are that pass's wide lines only, in reading order, so the title is chosen
  among lines upright at the winning angle; `books.identify` ranks them by quad thickness (`OcrLine.height` from the
  quad), not by box height (V2: upright desk text at 270° is a tall box)
```

The region check keeps a stationary desk label from holding the remembered angle after the book is turned or moved
(U1 in stage-1 form): the label lies outside the book's last region, so the read falls through to the probe or the
scan; a moved book costs a probe, not a wrong angle. Cost: remembered angle good → one pass (≈ 1.1–1.6 s); first
read → probe + one pass (≈ 2 s); otherwise plus the scan (≤ ≈ 6 s). The margin rule is *adapted* from Tesseract OSD's
best − second and OCRmyPDF's `--rotate-pages-threshold` (R§1).

**O5 Serialised reads with an owned task [concurrency; S1, U11].**

```
async def read(frame, *, purpose="page"):
    if self._closed: raise RuntimeError("ocr closed")
    t = asyncio.create_task(self._run(frame, purpose))
    self._tasks.add(t); t.add_done_callback(self._done)          # _done: discard, and log a task's exception
    return await asyncio.shield(t)                                # a caller's cancel stops its wait only

async def _run(frame, purpose):
    async with self._busy:                                        # one worker at a time, held until it returns
        res = await asyncio.get_running_loop().run_in_executor(None, self._read, frame, purpose,
                                                                 self._angle, self._region)
        if purpose == "page" and res.state == "sure": self._angle, self._region = res.rotation, res.region
        return res

async def aclose():                                               # runner teardown, before the loop ends
    self._closed = True
    await asyncio.gather(*self._tasks, return_exceptions=True)    # drains queued and running reads
```

`leafi/runner.py::_run` calls `await ocr.aclose()` in a `finally` after `run_session` when the backend has it. A
caller's `wait_for` timeout cancels its shield only; the task keeps the lock until the worker returns and publishes;
the next read waits. `_done` retrieves every task's exception, so none is lost. `MockOcr` gets `aclose()` as a no-op.

**O6 Skew order [data shape].** `OcrLine` gains `quad: tuple[tuple[float, float], ...] | None = None`. `reading_order(
lines)` takes skew = median of the confident wide lines' `q0 → q1` angles, clamped to ±15° (0 without quads), rotates
centres by −skew about the frame centre, sorts by deskewed centre y, forms a row when deskewed centres are within half
the quad height (`|q0 − q3|`, box height without a quad), then left to right. Without quads it is today's function.
`to_result(raw)` keeps its signature for the probes. Provenance: *adapted* from docTR `_sort_boxes` (R§4); rejected:
the fixed 10 px row threshold of PaddleOCR/RapidOCR.

**O7 Confident page numbers and guarded revisions [rules; S8, U3].**
- `split_number(lines: list[OcrLine], min_conf) -> (int | None, list[str])`: as today on the first and last two lines,
  but a number-only line gives the printed number only when its confidence ≥ `min_conf`; a number-only line below it
  is removed from the text and gives no number. Callers: `PageTracker.find`, `scripts/probes/p3_ocr_compare.py:65`,
  `tests/test_page_tracker.py:113`.
- **Missing-words guard** in `PageTracker.find`, for a page `matched` with a current revision. Words are
  `[w.lower() for w in leafi.core.text.words(text)]` (W7); `old` from `current_text`, `new` from the read. With no
  `old` words the guard is skipped (W6).

  ```
  uo, un = [], []                                       # old / new words left unmatched
  for tag, i1, i2, j1, j2 in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
      if tag == "equal": continue
      k = min(i2 - i1, j2 - j1) if tag == "replace" else 0      # paired in place: substitutions
      uo += old[i1 + k:i2]; un += new[j1 + k:j2]
  missing = 0
  for w in uo:                                          # a word that moved or shifted shows up among un
      b = max(un, key=lambda x: fuzz.ratio(w, x), default=None)
      if b is not None and fuzz.ratio(w, b) >= 60: un.remove(b)
      else: missing += 1
  refuse = missing >= 3 and missing / len(old) > MISSING        # MISSING = 0.2
  ```

  `refuse` → `PageFound("low_confidence", message="I can only see part of the page. Move your hand away and type
  /page to look again, or /page N --text <file> to type it.")`, nothing written. Substitutions, a moved line, and the
  shifts `SequenceMatcher` makes on repeated words are not missing words (W1, W2: the rehearsal's swapped line was 7
  of 17 under rev 6, 0 now; "the the the …" read as "tha the …" 0.5 → 0). Measured by the round-6 reviewer: a moved
  line 0, a repeated-word shift 0, a refrain with misreads 0, 12 words with 4 OCR errors 0, a corrected word read with
  its old misread 0, half the page gone 24/48 → refused, half gone plus desk words 23/48 → refused. The floor of 3
  keeps a short picture-book page from being refused for one merged or dropped word ("Tom hada kite", W3). Words,
  not lines, so a reformatted revision compares fairly. A new page has nothing to compare with and is stored as read;
  a later full read adds a revision (ADR-0010). Provenance: `difflib.SequenceMatcher` (stdlib) and
  `rapidfuzz.fuzz.ratio` (3.14.6, already used by `leafi/study/alignment.py`) *adopted*; the pairing *original*.
- The message names typed `/page` because it takes the camera path (`World._from_request` with no number and no text
  → `page_tracker.find`); a spoken "page N" returns the stored page N from the database without OCR (V4). The spoken
  first-line answer of today's help message is dropped as `noop` (U7, pre-existing): a follow-up issue.

**O8 Result, help path, console, evidence.** `OcrResult` gains `state` (default `"sure"`), `rotation`, `region`,
`passes` (angle, kind = remembered/probe/scan, score, wide, all, seconds); flat mock results stay valid (U10).
`needs_help(min_conf) = state != "sure" or confidence < min_conf`. `PageTracker.read()` wraps each `ocr.read` in
`wait_for(…, 15 s)` (timeout → `find` returns `unavailable`); on `needs_help` it recaptures only when `frame_diff ≥
diff_threshold`, so an unchanged frame reaches the help path at once (owner); `find()` returns `low_confidence` on
`needs_help`, writing nothing. `Ocr.read(frame, *, purpose="page"|"cover")`; `MockOcr.read` accepts and ignores it;
`books.identify` passes `cover`. `checks.py ocr` / `ocr-last` call `read` once and print `passes`, state, angle, line
count and the body's median line height in px; no engine calls of their own; verdict `ok` when `sure` with ≥ 3 lines.
Before relying on the constants (`PROBE_K`, the 0.5 margin, `MISSING`), the owner captures: book at 0°, 90°, 270°;
a spread; a hand over half a stored page; desk text near the book. Captures stay in `cache/`; a values-only commit
follows. `rapidocr==3.10.0` gains its reason (the crop rule, `update_params`). `performance.md`: "OCR one page ≤ 2 s
with a remembered angle or a sure probe, ≤ 6 s otherwise"; the 15 s timeout is enforced.

## Tests (`tests/test_ocr_pipeline.py` unless named; fake engines, no models)

1. `parse_rotations` and the settings page (`test_envedit.py`, `test_env_validators.py`): order kept; empty, `" , "`,
   `45`, `90,90` refused; a bad hand-edited value logs and uses the default.
2. Probe: five of six boxes tall → only 90/270 recognised; the clock excluded; a candidate not in `OCR_ROTATIONS`
   skipped; unsure → scan.
3. Choice: probe pass evident → two engine calls in all (det, one full) plus the probe's crops; tie → earlier listed
   angle; two body lines → `no text`; 180°-off garbage and 90°-off tall boxes score 0.
4. Remembered angle: second read one full pass; body outside the region (a label at the old angle) → probe; the book
   moved and the probe confirms the angle → no scan, new region published (V5); unsure keeps state; covers neither use
   nor set it; a sideways cover beside upright desk text picks the cover's angle and `books.identify` returns the
   cover title, not the desk text (V2); `OCR_ROTATIONS=0` with an evident page → `sure`, with a blank frame →
   `no text` and no exception (V3, W4); a first read whose probe nominates nothing reaches the scan (W4); a cover
   titled "Zog" read at confidence 0.7 → "Zog" (W5).
5. Serialisation: A exceeds the caller's timeout; B waits; A publishes, then B runs with A's state; never two workers
   (counted); a waiting B cancelled leaves A running; `aclose` drains and later `read` raises; a worker exception is
   logged, not lost.
6. `reading_order` with 5°-skewed quads and boxes derived from them (six lines, pitch 20, height 15) → correct order;
   no quads → today's test.
7. `split_number`: number at conf 0.97 → found; at 0.2 → no number and removed from the text; `OcrLine` input.
8. `PageTracker.find`: stored 48-word page read with 24 words → `low_confidence`, no revision; the same page reformatted
   (other newlines) with all words → revision added; a 12-word page stored with 4 OCR errors read correctly →
   revision added (V1); a page with 4 verified corrections read with the old misreads → revision added and the
   corrections kept by `add_ocr_revision` (V1); a page stored in the old line order read with one line moved → added
   (W1); "the the the the the the" read as "tha the tha the tha the" → added (W2); half missing plus desk words →
   refused; a 4-word page with one merged word → added (W3); a stored revision with no words → guard skipped (W6); unchanged-frame unsure → one read, nothing written; changed frame
   → two reads; timeout → `unavailable`; mock results unchanged
   (`test_low_confidence_recaptures_once_then_asks_the_learner` → one read on an unchanged frame; a new changed-frame
   test proves two).
9. Engines: `full`, `det`, `rec` built with `use_cls = False` and still so after reads.
10. `checks.ocr` against a fake backend prints the passes and calls no engine itself.
11. Rewrite the two existing rotation tests for O2/O4.

Hardware (`LEAFI_HW_TESTS=1`): fixture pages ≥ 98 % words with the classifier off; `test_hardware.py:74`'s turned
fixture read `sure` upright; fixtures turned 90°/180°/270° read upright with `OCR_ROTATIONS=0,90,180,270`.

## Steps

1. Rev 7 confirming round (codex, scoped to O4 and O7); answers folded into rev 8 if needed.
2. One commit: O1–O8, tests, `.env.example`, `performance.md`, `docs/engineering/code-locator.md`,
   `docs/plans/tech-debt.md` (TD-18's wording), `GLOSSARY.md` ("angle probe", "remembered angle"), the
   `2026-10-19-leafi-book-study.md` Decision log row, `scripts/probes/p3_ocr_compare.py` (its own engine,
   `split_number` on lines), `leafi/runner.py` (`aclose`), `docs/architecture/quality-attributes/reliability.md:13`
   and the `leafi/study/page_tracker.py` docstring (recapture only on a changed frame; the guard's message) (W9);
   full suite green.
3. O8 captures with the owner at the desk (no audio); a values-only commit for the constants.
4. Issues under `.scratch/` (`docs/agents/issue-tracker.md`): stage 2 (the book's paper, desk text, a spread — two
   pages or a left/right question); U7 (the help path drops a spoken first line).
