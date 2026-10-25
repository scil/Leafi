# OCR stage 1, design rev 6: round 6 (confirming) — 2026-10-25

Prompt `reviews/prompts/ocr-rotation-rev6.md`. **codex** `gpt-6-astra` at `xhigh` hit the ChatGPT usage limit mid-run
(log `.scratch/review/ocr-rotation-rev6-codex.log`; resets 15:04); its partial traces showed the repeated-word shift
(W2). Fallback per `codex-review`: a fresh Claude Opus 5.5 agent on the same prompt file; the first attempt ended with
an API content-filter error and no output, the second completed. `git status` unchanged. The author verified W1
(`insert` + `delete` of 7 words on the swapped line) and that `rapidfuzz==3.14.6` is declared in
`requirements-study.txt` and used by `leafi/study/alignment.py`.

V2, V4, V5 answered; V1 mostly; V3 in prose but not in the pseudocode. No passage kept an old decision.

| # | Sev | Decision | Finding | Rev 7 |
|---|---|---|---|---|
| W1 | High | O7 | A moved line counts as missing (delete + insert): the rehearsal's swapped line 7/17 → refused; pages stored in the old order stay stuck after O6 fixes the order. | Pair leftover old and new words by `fuzz.ratio ≥ 60`; only unpaired old words are missing |
| W2 | Medium | O7 | Repeated words make `SequenceMatcher` shift: "the the …" vs "tha the …" → 0.5 refused. | Same pairing |
| W3 | Medium | O7 | Short pages refused for one merged word ("Tom hada kite" → 0.25). | `missing ≥ 3` floor |
| W4 | Medium | O4 | `a == angle` with both None on a first read → `tried[0]` IndexError. | `angle is not None and …` |
| W5 | Medium | O4 | Covers with short or stylised titles score 0 at every angle; regression against today ("Zog"). | Own cover score: wide lines, conf ≥ 0.5, no length bar; tie and all-zero rules stated |
| W6 | Low | O7 | Division by zero when the stored text has no words. | Guard skipped |
| W7 | Low | O7 | "normalised words" not named. | `[w.lower() for w in words(text)]` |
| W8 | Low | O4 | `h` and the region's coordinate frame unstated. | `h` = median body quad height; region in the remembered angle's coordinates |
| W9 | Low | steps | `reliability.md:13` and the `page_tracker.py` docstring still state the old help path. | Added to step 2 |

Findings per round: 11, 6, 11, 11, 5, 9 (1 High). All of round 6 are local to O4/O7.
