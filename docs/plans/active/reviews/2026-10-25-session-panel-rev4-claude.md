# Session panel design rev 4: confirming round (fresh Claude, codex's stand-in)

Reviewer: a fresh Claude agent (Opus 5.5) on `reviews/prompts/session-panel-rev4.md` plus the owner's D5 note and
banner, 2026-10-25. Codex (`gpt-6-astra`, xhigh) ran out of quota mid-round ("try again at 8:06 PM"); its output was
lost. Answered by rev 5.

Confirmed: every listen an activity reaches (including `_offer_hint`, the practice retry, `world._from_request`,
`acquire_page`) is a position where `StaleInput` can fire today; no listen sits inside `controls_only` (the wake is
re-queued by its `finally`, `inputs.py:272-283`); `read_aloud` is the only loop without a listen; no
`except Exception` stands between a listen and `run_activity`. D1, D2, D4, D6, D8, D9 stand; ADR amendments marked;
provenance complete.

1. **Medium · D5/D3: an undelivered press shows nothing.** Readers read only when asked (`inputs.py:145-160`);
   `_speak` asks typed sources only when `_will_play()` (`:314`). Text mode: the panel reader idle after a `/say` →
   a `/do` during feedback waits in the device queue; the POST's dirty mark publishes a version with no `want`, the
   buttons re-enable. Fix: keep the panel reader always asked, or publish undelivered lines as `queued`.
2. **Medium · D3 `waiting_for`, D5 note: setup.** A want at a setup prompt (`identify.py:80, 144`; `loop.py:99,
   106, 124`) shows `step` while Leafi waits for a name or title; the note's "when Leafi is listening" is false
   there. Fix: a `setup` value; "not during setup" in the note.
3. **Medium · D5 "the same note and banner apply to Skip and Next page".** (a) They create no want, so no data; (b)
   Skip cuts a playing line at once (`inputs.py:173-176`); with an old `seen` it parks and is later dropped
   (`activities.py:252-258`, `loop.py:349-354`); at a boundary it is drained (`negotiate.py:149`) or dropped
   (`generate.py:84-87`); (c) `/next` → `next_page` (`controls.py:78-79`) is no page item (`inputs.py:179`); at an
   offer `parse_choice` gives `unparsed` and the argue band runs `Run(a)` (`negotiate.py:197`); ignored in `break`
   (`activities.py:562-567`), `noop` in review (`:521`). Fix: own fates (`cut`, `skipped`, `dropped`, `ignored`);
   `next_page` as a page item; show Next page only where it acts; truthful notes.
4. **Medium · D7 (a): the switch comes after the next question.** Each item loop speaks its prompt before listening
   (`activities.py:639, 840, 782, 421-427, 733, 498`): a want during "Correct!" → question 4 is asked → `Jump`.
   Fix: `activity_over()` true while a want is set (checked at `309, 333, 412, 494, 542, 636, 729, 838, 880`); `Jump`
   at the start of an owned prompt.
5. **Low/Medium · `_body`'s continuation loop skips negotiation** (`loop.py:405-410`): `/next` then `/do` → OCR, a
   new page read, an announcement, then `Jump`. Fix: `and latch.want is None` in the condition.
6. **Low · the wake counted as a silence** (`negotiate.py:198`): with `silence_reasks = 1` and an unconstructible
   kind, one real silence then ends the session (`:85-86`). Fix: check the slot right after the offer listen, before
   `parse_choice` and any counting.
7. **Low · two exits not cited**: the wanted path's `Run` (`negotiate.py:131`) and the `yes` path (`:185`).
8. **Low · fates undefined**: `switched` not in D3's list; no link from `Want` to its log entry; no fate for
   replaced, stopped, refused-after-take, or soft-deadline-lost wants; console `/do` has no entry.
9. **Low · `waiting_for` order and `judge`**: the filler speaks inside `controls_only`, so check `brain` first;
   `scoring.item_used`'s `judge` (`activities.py:808`) is outside `controls_only` (codex round 3, 5).
10. **Low · note wording**: "a page read always finishes first" contradicts D7 (a page read ends mid-page); say
    "a page scan (OCR)".
11. **Low · step 2's 409 test needs step 6**: test `_deliver` dropping lines when `accepting` is false; move 409 to
    `tests/test_panel.py`.
