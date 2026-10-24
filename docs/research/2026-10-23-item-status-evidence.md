# Item-status evidence (M7 design round 1, theme T10)

Question: which stored evidence lets `item_status` be **derived** (ADR-0017 §6.2: "status is derived, not stored apart from its evidence") in both mastery modes, including `ignored`, Anki-following items and `forget --session`? Decision it serves: M7 design rev 2, D13 (a new data shape, so AGENTS.md → Verification requires this note first).

## What Leafi stores today (code, 2026-10-23)

| Evidence | Where | Missing for derivation |
|---|---|---|
| Spoken/typed retrieval outcomes | `retrieval_events(learner_id, item_id, activity_id, at, day, outcome, evidence)` | session link only through `activity_id`; `day` written with `date.today()`, not `HOUSEHOLD_TZ` |
| Leafi's Anki answers | `review_answers(learner_id, knowledge_item_id, card_id, ease 1–4, state, sent_at, acked_at)` | the interval **after** the answer, the review type, lapses, the session or activity |
| Card acknowledgement | `anki_outbox(state='acked', anki_note_id, card_ids)` | when it was acknowledged (only `updated_at`) |
| Ignore requests | nowhere | everything |
| Status | `knowledge_items.status`, written by `anki._update_status` and (M7) `item_status.apply` | it is the only copy |

Found while reading: `anki._update_status` promotes `learning → known` from `DueCard.interval`, which `due_cards` read from `cardsInfo` **before** the answer, so the comparison with `REVIEW_KNOWN_INTERVAL_DAYS` uses the previous interval (one review late at best). Reviews done in Anki itself (desktop, AnkiDroid, AnkiWeb) are never seen.

## Sources

| # | Tier | Source | source-date | checked | What is taken / not taken |
|---|---|---|---|---|---|
| S1 | 1 | AnkiConnect source, `plugin/__init__.py` (FooSoft/anki-connect; the repository states it moved to `git.sr.ht/~foosoft/anki-connect`, which answered 502) — https://raw.githubusercontent.com/FooSoft/anki-connect/master/plugin/__init__.py | copyright 2016–2021; GitHub mirror, undated | 2026-10-23 | `getReviewsOfCards(cards)` returns, per card id, revlog rows as dicts with keys `id, usn, ease, ivl, lastIvl, factor, time, type`; `cardsInfo` returns `interval` (= `card.ivl`), `lapses`, `due`, `queue`, `type`. Not taken: `cardReviews` (raw rows, per deck). |
| S2 | 1 (Anki's schema, documented by AnkiDroid, a co-maintained client) | AnkiDroid wiki, Database Structure — https://github.com/ankidroid/Anki-Android/wiki/Database-Structure | edited 2025-08-06 | 2026-10-23 | `revlog.id` = review time in epoch ms; `ivl` = interval after the review, negative = seconds (intraday (re)learning), positive = days; `lastIvl` = the previous `ivl`; `type` 0 learn, 1 review, 2 relearn, 3 filtered, 4 manual, 5 rescheduled. Not taken: `ease` semantics for learning cards (the page gives 1–3 for learn/relearn; Leafi does not rely on ease for Anki-following status), `factor` (FSRS difficulty when FSRS is on). |

## Findings

1. The interval after an answer is the revlog row's `ivl` whose `id` ≥ the answer's `sent_at` (S1, S2). Leafi's reconcile already finds that row to acknowledge a lost response; reading its `ivl` and `type` there and after a normal acknowledgement costs one `getReviewsOfCards` call per answer, which `reconcile` already makes.
2. A lapse is visible as a revlog row of `type` 2 (relearn) after a `type` 1 review, or as `cardsInfo.lapses` increasing (S1, S2). The card's `interval` and `lapses` at any observation are enough to say known (interval ≥ threshold) and lapsed (lapses grew since it was known), whoever reviewed it.
3. Anki keeps its own history: Leafi needs only the observations it made (snapshots), not a copy of `revlog`. A snapshot belongs to the session in which Leafi observed it, so `forget --session` removes Leafi's evidence of that session without touching the card (the card is the learner's, and its deletion is `forget --learner --delete-anki-deck`).
4. Prior art for "status as a fold over an append-only log": Anki itself (card state is the result of `revlog`; S2). *Adapted*: Leafi's log holds observations and requests, not scheduling.

## Consequence for the design

One append-only table, `item_status_events` (migration 7): `ignore` / `unignore` requests (source `brain` | `learner` | `owner`), `card_ack` (first Anki acknowledgement of the item's card), `card_state` (an observation: `ivl_days`, `lapses`, `revlog_id`, `revlog_type`); each with learner, item, `at`, household `day`, and `session_id` / `activity_id` when observed inside a session. Status and the next recall date are a pure fold over this table and `retrieval_events`; `knowledge_items.status` becomes a cache the fold rewrites. Designed in M7 rev 2, D13.
