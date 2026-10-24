# M7 design rev 8 — increment round, fresh Claude, fallback for codex (round 8)

Reviewer: a fresh Claude agent on `reviews/prompts/m7-design-rev8.md`, 2026-10-24 (codex's quota out until 02:00). Read D12, D21 with "Rev 8 details", the rev-7 review, `inputs.py`, `console.py`, `services/asr/__init__.py`, `asr/vad.py`, `negotiate.py`, `activities.py`, `world.py`, `identify.py`, `loop.py`, `test_controls.py`, `test_harness_sessions.py`; one probe of `controls.parse`. No file edited.

## Round 7 verdicts

1 partly (`activity_started_at` undefined, `Switched` outside an activity crashes, the console not made main); 2 closed; 3 closed in design (`pause()` cannot reach the segmenter's local buffer); 4 partly (`boundary_inbox` never drained; in-activity waits not routed); 5 closed (a late skip can still cut the next line); 6 closed; 7 closed here; 8 closed; 9 partly (the non-main rule over-applied; pages ignored at some sites).

## Findings

1. **High · reader `src is not main: drop`:** drops every non-control console utterance in voice mode (typed `/fix`, `back`, `explain`, yes/no, eases, typed reading, all delivered by M6 at `inputs.py:118`); after an Ear switch the console is still `control`, so the session cannot be driven (`test_controls.py:171`, `test_harness_sessions.py:234` fail). Fix: only `u is None` from a non-main source is dropped; `ear_lost` makes the console `main` (M6's `_console_is_main`).
2. **Medium-High · `Switched`:** `activity_started_at` is not in `Inputs`; `World.activity_started` is set by four kinds and never cleared; the Ear lost during `decide`, at the first boundary or during `identify_book` raises `StaleInput` from negotiate or loop → `internal_error`. Fix: `run_activity` sets and clears `Inputs.activity_started_at`; a `Switched` taken while no activity runs is consumed (the epoch check returns `Reobserve`); still raise for setup prompts (`identify` restarts on `StaleInput`); rewrite consequence 8.
3. **Medium · late wait-owned items:** `boundary_inbox` is never drained; in-activity waits not covered; "next page" recognised after `decide`, an offer or `judge` is lost. Fix: drain by kind at every boundary iteration (each inbox Page → pending page + `Reobserve`, Skips dropped); a late Page of an ended `("act", aid, *)` prompt of the running activity → its page handling, else `w.pending`; say what a Page means in kinds without page handling.
4. **Low-Medium · a late skip cuts the next line:** the reader's `speaking` cut ignores the owner. Fix: cut only when `owner_at(u.ended_at)` is the current owner, else route it as a late Skip.
5. **Low · `_offer_hint`:** "no thank you", "yes please", "please", "not now" parse to `None` and are aligned as reading (M6 discarded them). Fix: yes/no-like replies are answers (`parse_choice` or extra phrases); test.
6. **Low · `accepts_page = False` changes:** at `confirm_title`, `continue_offer`, identify's four listens and `review_anki` a typed `/page` used to end the listen (or say `noop`). Fix: list each site's M6 page behaviour in M7b's table, or `accepts_page = True` where M6 ended the listen.
7. **Low · notes:** "14 call sites" left in one place; M7b says "seven consequences" (13); the `pause()` buffer clear needs a pause-generation counter the segmenter checks; the VAD `end_t` mapping must survive `vad.reset()`; whether the filler line speaks the `mic_lost` notice.

## Sound

The ownership rule and prompt ids (15 sites verified); the synchronous `Switched` with the notice deferred to the main flow; the last-voiced `ended_at` and the buffer clear on pause; `controls_only` returning skips and pages; `_offer_hint`'s hand-back; prompt ids for `_pause`, `confirm_page`, rationale lines and in-activity waits; the M7c/M7e fixes; the test-port list.

**Readiness:** blocked by 1–3, wording fixes with no new mechanism; once in a rev 9, M7b can start without another full round; 4–7 during implementation.
