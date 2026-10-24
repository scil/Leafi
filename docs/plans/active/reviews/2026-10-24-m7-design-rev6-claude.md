# M7 design rev 6 — confirming round, fresh Claude, fallback for codex (round 6)

Reviewer: a fresh Claude agent on `reviews/prompts/m7-design-rev6.md`, run 2026-10-24 while codex's quota was out (until 02:00). It read `inputs.py`, `console.py`, `services/asr/__init__.py`, `latch.py`, `activities.py`, `negotiate.py`, `world.py`, `identify.py`, `guests.py`, `records.py`, `learner_store.py`, `egress.py`, `versions.py`, `notifiers.py`, `anki.py`, `knowledge.py`; grepped every INSERT form and every UPDATE under `leafi/`; one in-memory probe (`Epoch.key()` ordering, the empty-`IN ()` fence). No file edited. The author verified findings 1 (`world.acquire_page` parses `/page N --text`) and 8 (`knowledge.add_encounter` and `add_cards` hard-code `[learner_id]`) against the code.

## Round 5 verdicts

| # | Verdict | Remaining |
|---|---|---|
| 1 | partly | `present(o)` not applied at every prompt (4); an epoch change inside one prompt drops input (3) |
| 2 | partly | a stale `Skip` leaves its `post_skip` queued (5); no caller handles `SKIP`/`PAGE` yet (6) |
| 3 | partly | the VAD path cannot stamp: `Vad.feed` returns PCM bytes without times (10) |
| 4 | open | a page typed during a wait is dropped, not consumed; `PAGE` loses the control's details (1, 2) |
| 5 | partly | `Epoch` keys raise `TypeError` when compared; "mic lost" no longer spoken (9) |
| 6 | closed | — |
| 7 | partly | residuals (11) |
| 8 | closed | — |
| 9 | partly | "retry without A's leaves" mislabels Brain outputs (7); two writers hard-code provenance (8) |
| 10 | closed | `_remember_notes` after forget finished (13) |
| 11 | partly | no failed state (12) |
| 12, 13, 14 | closed | (14: naming, 13 → 14 below) |

## Findings

1. **High · D21 — `PAGE` returns no information and page acquisition stops working.** `_page_turn` needs the `Control` (`n`, `--text`, `activities.py:62-73`); `world.acquire_page` waits for `/page N --text <file>` in reply to `ask_page_text` (`world.py:153-166`). Under D21 that line becomes `Page(owner)`: a bare `PAGE` loses the path, or "page ignored" for `read_aloud` and World prompts; in text mode the next page can never be typed and the session ends `idle_session`. Fix: `Page(u, ctl, owner)` returned as the item; a prompt-level `accepts_page` for `acquire_page` and `_from_request`.
2. **Medium · D21 — the "boundary pages" rule cannot run as written.** A `/page` typed during `decide` stays in the stream as `Page(("wait", turn))`; at the announce band `negotiate` never listens; `practise_errors`' listen hits `item.owner != o → continue` before the `Page` branch, so the page is lost; during an offer listen the kind is not in `ACCEPTS_PAGE`, so it is ignored. Fix: on exit, `controls_only` (and the offer listen) take every `Page` owned by a wait or offer prompt → `w.pending` via `_page_turn`, `Reobserve`; test at the announce band.
3. **Medium · D21 — the epoch in `Owner` drops input within one prompt.** `read_listen` bumps the epoch on `/fix` (`activities.py:207`) and `back` (`:316`), `checkpoint` on any settings change; a second typed line stamped before the bump has owner `(…, E)` and is dropped (today it is aligned). Fix: match ownership on `prompt_id` only; epoch staleness stays with `Switched` and the existing checks at use.
4. **Medium · D21 — `present()` misses prompts.** No `prompt_id` kind for identification (`identify._confirm`, `ask_school`, `_identify`), `identify_book` and `continue_offer` (`loop.py:97-123`), World's prompts (`world.py:128-129`, `153-154`), `_offer_hint` (`activities.py:216`); lead-in lines before a listen (`_announce`'s "page_ready", `practice_retry`, `review_prompt_eases`, offers through `Talk.say`) need `owner=` too; `say()`, `line()` and `Talk` lack the parameter. Fix: one `ask(o, text)` helper (present, speak, then `listen(o)`); a `setup` / `world` prompt kind; `_offer_hint` reuses the page prompt and passes a non-"yes" reply on to `_reading_utterance`.
5. **Medium · D21 — a stale `Skip` leaves a queued skip behind** (`post_skip()` whoever owns it), later consumed by `negotiate`'s announce path (`negotiate.py:146`) or `read_aloud` (`activities.py:496`); consequence 7 misstates M6 (`negotiate` drains skips before every offer, `negotiate.py:136`). Fix: stamp queue entries with their owner, or `post_skip` only when not stale; correct consequence 7.
6. **Medium · D21 — every `listen` caller must handle `SKIP` and `PAGE`:** `parse_choice`, `controls.parse(u.text)` (`_offer_hint`, `world.py:130`, `:157`, `identify`) and the `if s.take_skip()` checks after `listen` (`read_listen`, `practise_errors`, `review_anki`, `_pause`, `negotiate:161`). Fix: list the 14 `listen` call sites in M7b and test each with `Skip` and `Page`.
7. **Medium · D22 — "retry without A's leaves" mislabels Brain outputs.** It suits stored raw leaves (the `brain_calls` payload, `decision_records`' leaf list); a Brain output (`brain_calls.response`, an assessment, `say_before`/`rationale`) is atomic and by D2 names A; removing A's leaves and recomputing would store A-derived text labelled `[B]`, missed by `_purge_derived`. Fix: drop every Brain output whose provenance names A (response NULL, assessment dropped, decision fields dropped); simplest: drop decision records and assessments outright, keep only the re-rendered payload of audit rows.
8. **Medium · D2/D22 (M7c) — two writers hard-code provenance:** `knowledge.add_encounter` (`[learner_id]`, `knowledge.py:49`) and `add_cards` (`prov("derived_from_learner", [s.learner_id])`, `activities.py:541`); Brain content built from A's note would be stored as B-only, pass the fence and survive `forget --learner A`. Fix: both take the content's `Provenance.of_output`; test.
9. **Low · D21 — `o.epoch < item.epoch` is not usable:** `Epoch.key()` tuples hold `None` (probe: `TypeError`) and lexicographic order misorders `cycle_id`/`page_read_id`; "mic_lost" never spoken when absorbed during a wait. Fix: compare `turn_id`; say "mic lost" when `ear_lost` fires.
10. **Low · D21 — `ended_at` in VAD mode and in scripted sources:** `Vad.feed` returns `list[bytes]` (`asr/__init__.py:32`, `:173`); scripted `lines=` and test fakes would stamp at pop, breaking M6 tests with a Mouth. Fix: `feed` returns `(pcm, end_t)`; define the stamp when a source sets none.
11. **Low · D22's `test_architecture` rule on today's code:** (a) flags `activities.py:51` and `rows.py:27`, both multi-line `store.insert(\n "<t>"` calls (scan the AST, not lines); (b) flags `rows.py:45` (`finish_activity`, missing from the first red run), `identify.py:62`, `identify.py:68` (`adopt`'s `UPDATE egress_log SET learner_id`: stays red unless moved or exempted), `guests.py:50, 57` and `records.py:241, 308` (exempt); dynamic `SET {…}` (`miscues.py:57`, `supervisor.py:62`) is a blind spot to state; `rebuild()` is in `storage.py`, already excluded; learner-naming columns outside the registry (`egress_log.learner_id`, `corrections.source_learner_id`, `household_terms.former_learner_id`) to list with their reason.
12. **Low · D8 — no failed state:** a thread exception leaves `loading` forever (in-session cloud calls refused for good; outside a session `prepare` waits forever). Fix: `failed`, behaving like M5's `detector.load → None` (lists only, warned), and a `doctor` line.
13. **Low · D17/D22 — `_remember_notes` after forget has finished** dereferences a missing learner row (`records.py:229-230`). Fix: alert with the note id, or forget waits while the learner has `sent` outbox rows.
14. **Low · D5/D9 — the same names for input and output:** `study_brain_model`, `brain_model_cheap`, `brain_local_model` are today's pydantic fields (`config.py:53-56`) and the fallback's inputs, so they cannot also be the deprecated computed properties. Fix: aliased internal fields.
15. **Low · D3/C1 against B2:** substituting a refused leaf in an **assistant** `Turn` is B2's rejected option 2. Fix: a refused leaf in an assistant turn refuses the whole request, so M7f's "the conversation ends" follows.
16. **Low · D19 against M7f P4/P7 — two definitions of `forget --brain-records`** (M7e: rows only; P7: also the learner's files under `data/evals/`; M7f's steps build it again); rev 6 misses `brain_calls` rows of N's sessions naming no source. Fix: one owner (M7e), one definition (both source columns, N's `session_id`s, N's eval files).
17. **Low · A1 in M7a also changes `notifiers.body`:** a learner without a school answer is now named (as `derived_from_learner`, `notifiers.py:76`); matches the owner's decision; add to the `test_privacy` list.

## Sound

The ownership rule itself; pruning that keeps the newest entry; a request on every listen iteration; the timeout owned by whoever asked; consequences 1–3 and 5 by hand; D22's fence (empty `IN ()` evaluates true; source `0` excluded in `named()`); the new `guests.discard` and `_delete_session_records` orders with foreign keys on; `effective_tiers` and the fingerprint over effective values (`policy_values` must also read the legacy keys); D7 in `admit`; D8's walk and worked example; practice turns under D8 timing match B4; A2–A5, C3 (two breakpoints within the vendor limit), B1 left to M7f.

## Readiness

**M7a can start**, with finding 7's retry correction written into D22 first (M7a's `test_forget_race` covers `brain_calls` and assessments) and 11, 12, 14 settled during implementation. **M7b is blocked** by 1–6 (with 9, 10). **M7c** needs 8. **M7d**: no blocker beyond earlier steps. **M7e** needs 7 and 16. 15 goes to M7f.
