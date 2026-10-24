# M7 design rev 7 — confirming round, fresh Claude, fallback for codex (round 7)

Reviewer: a fresh Claude agent on `reviews/prompts/m7-design-rev7.md`, run 2026-10-24 while codex's quota was out. It read D12/D15/D19/D21/D22, the rev-6 review, `inputs.py`, `console.py`, `services/asr/__init__.py`, `asr/vad.py`, `text.typed_utterance`, `ports.Utterance`/`AudioChunk`, `negotiate.py`, `activities.py`, `world.py`, `identify.py`, `loop.py`, `latch.py`, `controls.py`, `learner_store.py`, `knowledge.py`, `cards.py` and the M6 tests driving `Inputs`; one anyio stream-ordering probe. No file edited.

## Round 6 verdicts

1 closed; 2 partly (late wait-owned items, `None`-owned items past a wait); 3 closed; 4 partly (`_offer_hint` reroute wrong; ids missing for `_pause`, rationale lines, in-activity waits); 5 partly (a wait-owned skip posted at exit reaches the wrong consumer); 6 closed (15 sites, not 14); 8 partly (the `code`-built card copies a Brain explanation without its sources); 9 partly ("mic_lost" in the handler: ordering bug and a second speaker); 10 partly (the closing chunk is 0.6–1.2 s after the last speech); 16 partly (no live-session fence; the practice design still builds the command).

## Findings

1. **Medium-High · D21 `ear_lost`:** "bump; say(mic_lost); send(Switched)" yields in `say`, so a console line already in flight is delivered before `Switched` (probe: `['console line', 'Switched']`), owned by `None`, accepted by the stale `read_listen`, whose next listen re-presents after `at` and absorbs `Switched` — never `aborted_stale` (M6 sends `_SWITCHED` before any await, `inputs.py:132-133`); the handler's say also races the filler or an activity line, and its `present(None)` replaces a wait's owner. Fix: set `switched_at` and send `Switched` synchronously first; `listen` raises when the current *activity* began before `switched_at`; "mic_lost" queued as the main flow's next line under the current owner.
2. **Medium · `_offer_hint`:** passing a non-yes reply to `_reading_utterance` aligns controls ("no", "/fix", "back", "explain") as reading; a "skip" is posted and aligned, then the next reading utterance is discarded. Fix: return it to `read_listen`'s loop, which dispatches through `take_skip`, `controls.parse`, `_reading_utterance`; only yes/no consumed; the hint listen accepts pages.
3. **Medium · `u.ended_at`:** the closing chunk is 1.2 s (energy `pause_s`) / 0.6 s (Silero `min_silence_s`) after the last speech, so speech ending up to 1.2 s before B's present is owned by B; `_segment_energy`'s `speech` buffer survives `pause()`. Fix: the end of the last voiced sample (energy: the last above-threshold chunk's `t`; VAD: segment end mapped to chunk times); clear the buffer on pause.
4. **Medium · `controls_only` exit:** a "next page" / "skip" whose segment closed during the wait but whose recognition finishes after the exit arrives owned by the wait and is dropped as stale; also a console line between `readline` and delivery. Fix: route wait-owned `Page` / `Skip` arriving later to the boundary's handler rather than dropping them.
5. **Medium · a wait-owned skip posted at exit:** drained by `negotiate` before its offer (no effect); on `b.wanted` / `b.reask` not drained (overrides a "yes" at `:161`); in an activity's wait it would discard the next answer (`review_anki :457`). Fix: `controls_only` returns its skips; each wait site states what a skip means.
6. **Medium · D15 `code`-built card:** `knowledge.card_fields` copies the latest encounter's explanation (`knowledge.py:146-162`, `cards.stored_text`) and `add_cards` labels it `[s.learner_id]` (`activities.py:541`). Fix: `card_fields` returns the join of the chosen encounter's explanation and context provenance; test.
7. **Low · D19 `forget --brain-records`:** no fence against N's live session (refuse with `LearnerBusy`); transcripts selected by owner, not provenance; the practice design still lists the command.
8. **Low · prompt ids missing:** `_pause`, `_from_request`'s uncertain confirm (`world.py:128-129`), negotiate's rationale and "I can't" lines, in-activity Brain waits (consequence 1 vs D12); the offer listen's page handling needs a page-request hook on `Session` (`pending` lives on `World`; `parse_choice` returns "unparsed" for `/page`).
9. **Low · contract details:** 15 listen sites; the reader turns `None` from any source into `Timeout` while M6 counts only the main source's (`inputs.py:104-107`); an ignored page no longer ends `wait` (`_pause(any_input_ends=True)`) or re-asks in `identify_book`.

Tests that break as specified: every direct `Inputs.listen(t)` in `test_controls.py` (signature), `test_an_eye_page_turn_is_delivered_while_the_page_is_open` (default `accepts_page=False`), every `test_negotiate*.py` through `ScriptedTalk` (no `ask`), `test_the_session_continues_on_the_console_when_the_microphone_dies` (finding 1).

Question 3: "a plain `say` presents `None`" is mostly safe; unsafe only inside a wait or after its prompt was presented ("mic_lost", a Brain line while a call continues): a `say` inside `controls_only` or `listen` keeps the current owner.

## Sound

The ownership rule and owner = prompt id; `Page` / `Skip` returned as M6 utterances; a stale skip never posted; `acquire_page` with `--text`; pruning; a request every iteration; consequences 2, 3, 5, 11–13; the asker-owned timeout; D15's rule for Brain-written content; D19's single definition (both source columns and the learner's sessions).

## Readiness

M7b not ready; blocked by findings 1–5 (wording-level, no new mechanism) plus the port list; one increment reviewer on a rev 8, then M7b can start. 6 (M7c), 7 (M7e), 8–9 during implementation.
