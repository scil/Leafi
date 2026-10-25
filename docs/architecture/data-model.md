# Data model (meaning; the schema in `leafi/core/storage.py` is the fact)

Store: SQLite `data/leafi.db`, schema version 5 (`storage.SCHEMA`). Opening has three states (ADR-0018 §7.2): an empty file is created at schema 5 with no learner rows; a file at 5 opens; a file with data below 5 refuses and names `python -m leafi migrate --learner "<name>"`, the only command that changes a schema. Every opener holds a shared lock on `data/leafi.db.users` (`portalocker`); the migration takes it exclusively. The legacy habit store `data/sessions.db` stays separate (ADR-0011: consolidation is a future plan). Decisions behind the shape: ADR-0009 (observations vs judgements), ADR-0010 (page revisions), ADR-0018 (learners, provenance).

## Entities

The rows below give each entity's meaning as of schema 4; schema 5 is these plus the changes in [Migration 5](#migration-5-in-storagepy-since-2026-10-23).

| Entity | Key fields | Lifecycle / meaning |
|---|---|---|
| `books` | id, title, isbn?, language (`en`), level?, created_at, archived_at? | Created when identified (B1) or added by the parent. Never deleted. |
| `pages` | id (internal, stable), book_id, printed_number?, observations (json: first_line, last_line, word_count, line_count — last confirmed set), created_at | One row per physical page. Identity is never derived from text (ADR-0010 §1). `current_text()` returns the latest revision's text. |
| `page_revisions` | id, page_id, rev, text, source (`ocr`/`correction`/`manual`), spans_verified (json list of half-open `[start,end)` code-point spans), edit_map (json, from the parent revision), tokenizer_version, ocr_backend?, ocr_confidence?, created_at | Immutable. Rev 1 from OCR or manual text (manual = fully verified); each correction appends a revision with its span verified and the edit map that transforms spans and reading state (ADR-0010 §6); a later OCR never overwrites verified spans. |
| `page_images` | id, page_id, path (under `cache/pages/`), width, captured_at | Deleted after `PAGES_RETAIN_DAYS` (7); the row is deleted with the file. |
| `corrections` | id, page_revision_id (the revision corrected), char_start, char_end, old_text, new_text, source (`voice`/`text`/`parent`), utterance_id?, created_at | Append-only provenance. Applying = insert correction + insert new revision + lexicon update in one transaction. |
| `reading_sessions` | id, book_id, started_at, ended_at?, mode (`voice`/`text`), devices (json), summary? (json counts, no text of the child's questions), lease_token | One sitting. Null `ended_at` = in progress; next start closes stale ones with `summary.interrupted=true`. |
| `page_reads` | id, session_id, page_id, page_revision_id, attempt, started_at, ended_at?, reading_state (json: per-token status, pcur, ccur, turn_id — ADR-0013), tokens_expected, tokens_committed, tokens_matched, tokens_unread, wpm? | One pass over a page at one revision. Repeated reading increments `attempt`. The reading state is persisted after every utterance; an interrupted session is closed on the next start and a new session may offer to continue from its committed cursor in a new `page_reads` row (ADR-0013 → Interrupted session). |
| `utterances` | id, page_read_id, page_revision_id, text, words (json: word, start_s, end_s, conf or null), kind (`reading`/`control`/`question`/`correction`), audio_ref? (in-memory only, never persisted unless `AUDIO_KEEP_CLIPS`), created_at | What was heard or typed. Timestamps are relative to the utterance's own audio. |
| `observations` | id, utterance_id, kind (`matched`/`substituted`/`deleted`/`inserted`), token_start, token_end (expected token indexes in the revision; for `inserted`, anchor index), heard_text?, created_at | Raw alignment output (ADR-0009 §1). Never edited. |
| `miscues` | id, observation_id, page_read_id, page_revision_id, expected, expected_token_index, expected_char_span, heard?, status (`candidate`/`confirmed`/`unsure`/`withdrawn`/`invalidated`), withdrawn_reason? (`self_corrected`/`reread`/`practice`), unsure_reason? (`disagreed`/`skipped`/`idle`/`interrupted`/`not_practised`), evidence (`none`/`acoustic`), score?, phonemes_expected?, phonemes_heard?, invalidated_reason?, updated_at | The judgement layer. Created `candidate` from `substituted`/`deleted` observations; transitions per ADR-0013 (Practice, Interrupted session, Correction interaction): `confirmed` only with acoustic evidence; a matching retry withdraws in both voice and text mode. |
| `practices` | id, miscue_id, attempt (1–2), outcome (`matched`/`disagreed`/`skipped`), evidence (`none`/`acoustic`), created_at | Model-and-repeat attempts (ADR-0013 → Practice). Text mode writes the same rows with `evidence=none`. |
| `knowledge_items` | id, kind (`word`/`phrase`/`grammar`/`fact`/`pronunciation`), language, key (lemma or surface), sense_hint?, status (`new`/`learning`/`known`/`lapsed`), anki_item_key (uuid, stable), created_at, updated_at | Unique on (kind, language, key, sense_hint). `status` moves `new→learning` on first Anki review, `learning→known` when the card's interval ≥ `REVIEW_KNOWN_INTERVAL_DAYS` (21), `known→lapsed` on an Anki lapse, `lapsed→learning` on the next pass. |
| `encounters` | id, knowledge_item_id, session_id, page_revision_id?, context_sentence, explanation_en?, explanation_zh?, trigger (`explain`/`check`/`miscue`/`parent`), created_at | Each time the item came up, with its own context; the item itself holds no context. |
| `difficulties` | id, knowledge_item_id? / miscue_key?, sessions_seen (json ids), weight, kind (`confirmed`/`watch`/`knowledge`), updated_at | Recomputed by `study/knowledge.py` inside the transaction that changed its inputs, with the formulas in ADR-0013 → Difficulties (the only owner of the weights and existence rules). Never edited by hand; `withdrawn`/`invalidated` never contribute. |
| `anki_outbox` | id, knowledge_item_id, op (`add`/`update`), state (`pending`/`sent`/`acked`/`failed`), attempts, last_error?, anki_note_id?, card_ids (json), last_acked_fields (json hash per field), attempted_fields (hashes of the first add attempt), updated_at | Local synchronisation outbox (ADR-0004 amendment). Before `add`, `findNotes "tag:leafi-id::<anki_item_key>"` dedupes a lost acknowledgement and takes `attempted_fields`, never the remote values, as the baseline; an `update` touches a field only when its remote value still equals `last_acked_fields`. |
| `review_answers` | id, knowledge_item_id, card_id, ease (1 again / 3 good in v1, chosen by the learner), state (`pending`/`sent`/`acked`/`failed`), sent_at?, acked_at? | Written `pending`, set `sent` immediately before `answerCards`, `acked` on response; a `sent` answer is never replayed; reconciliation via `getReviewsOfCards` after `sent_at` marks `acked`, else it stays `sent` and is listed for the parent. |
| `lexicon` | word, language, source (`book`/`correction`/`manual`), book_id?, weight, updated_at | Advisory in v1 (ADR-0011): candidates for OCR snap and future ASR bias. Rebuilt from revisions + corrections; manual rows survive. |
| `learner_profile` | key, value (json), updated_at | Small facts the coach may use (the name the child gave Leafi, explanation language order). No identity, no images, no embeddings. Protected names live in `household_terms`, not here. |

## Migration 5 (in `storage.py` since 2026-10-23)

ADR-0017, ADR-0018 and ADR-0013 v2 change the shape above in one migration (ADR-0018 §7.2): `storage.migrate_file` takes the exclusive lock, backs the file up to `data/backups/leafi-v4-<time>.db`, and in one transaction rebuilds every table whose definition differs from `SCHEMA` (the `rebuild()` helper: create `new_<table>`, copy, drop, rename), creates the new tables, writes the first learner, runs `foreign_key_check` and sets version 5. Existing rows belong to the first learner; their texts become `learner` text of that learner, page-derived fields `page`. `tests/test_migration_5.py` asserts the migrated schema equals a fresh one.

(Until schema 7; migration 7 dropped these columns, ADR-0021 E8.) As built (plan M3, Decision log 2026-10-23): a table with several texts has one provenance pair per text group, named `<group>_provenance_class` / `<group>_source_learners` (`activities.outcome_*`, `activities.assessment_*`, `brain_calls.payload_*`, `brain_calls.response_*`, `encounters.context_*` for the context sentence, `encounters.explanation_*` for `explanation_en`, `explanation_zh` and `example`, `anki_outbox.card_*` for the card fields); a table with one text has `provenance_class` / `source_learners`. `household_terms` (term, kind `name`/`school`/`other`, former_learner_id) is new, so `forget --learner` can keep a name replaced after its learner row is gone. `page_reads.cycle_id`, `miscues.cycle_id` and `anki_outbox.front` / `back` / `sentence` stay nullable until M6 writes cycles and `add_cards`; the `anonymous` learner row is created by M6 with the first guest.

| Entity | Change | Owner of the meaning |
|---|---|---|
| `learners` | new: id (never reused), kind (`learner`/`guest`/`anonymous`), display_name, birth_year?, school_year?, alias, alias_age_band, settings (json), settings_version, recognition (json), guest_reason?, guest_expires_at?, forgetting, created_at | ADR-0018 §1 |
| direct learner ownership | `learner_id NOT NULL` on `reading_sessions`, `knowledge_items`, `difficulties`, `retrieval_events`, `learner_notes`, `book_notes`, `review_answers`, `anki_outbox`, `consents`, `encounters` (`session_id` nullable); keys become learner-scoped | ADR-0018 §1 |
| `cycles` | new: id, session_id, status (`open`/`closed`), opened_by_activity, closed_reason (`next_reading`/`wrap`/`stop`/`interrupted`/terminal status), opened_at, closed_at | ADR-0017 §7.2, ADR-0013 → Cycles |
| `activities` | new: id, session_id, cycle_id?, kind, continuation, params (json), arm, propensity, policy_version, decided_by, override, autonomy, epoch, status (`ActivityStatus`), started_at, ended_at, outcome (json), assessment? | ADR-0017 §7.2 |
| `brain_calls` | new: purpose, difficulty, tier, backend, endpoint host, model, effective provider/model, prompt_version, payload as sent, response, latency_ms, transmitted attempts, tokens, estimated cost, outcome | ADR-0017 §7.2 |
| `retrieval_events` | new: learner_id, item_id, activity_id, at, day (household date), outcome (`success`/`fail`), evidence (`typed`/`heard_confident`/`acoustic`) | ADR-0017 §3.4, §6.2 |
| `learner_notes`, `learner_note_citations`, `book_notes` | new; notes cite the activities they rest on | ADR-0017 §7.1 |
| `consents`, `egress_log` | new (ISO/IEC TS 27560 column names; HMAC, never a body) | ADR-0018 §2, §4.2 |
| provenance | dropped by migration 7 (schema 7, ADR-0021 E8): no stored text carries a source any more; `forget` and the write fence go by the owning learner (`learner_id`, or the session's learner) | ADR-0021 |
| `page_reads` | + `cycle_id`; at most one per `(cycle, page)` (a correction moves it to the new revision in place); + `alignment_versions` (json: word list, `FUNCTION_WORDS`, phonemizer, lemma source); + counts `self_corrections`, `repetitions`, `unaligned_words`, `function_word_misses`, `not_reached`; `reading_state` json: tokens with `miscue_id` and `created_by`, + `unaligned_run`, `unaligned_words`, `prompted` | ADR-0013 → Definitions, Opening a page read, Running-record conventions |
| `observations` | kind + `unaligned` (with `token_start`/`token_end` NULL, so those columns become nullable for that kind only); + `pair_class` (`exact`/`phones`/`fuzzy`/`join`/`inflection`/`substitute`, NULL for deletions and insertions), `function_word`, `repeat`, `self_correction`, `sim` (matches and substitutions), `word_count` (`unaligned`) | ADR-0013 → align rules 4–5 |
| `miscues` | + `cycle_id` (the owning cycle); + `origin` (`substitution`/`deletion`/`supplied`); `unsure_reason` + `unclear`; `expected_token_index` stays the index at `page_revision_id`, the revision of creation (tokens are found by `miscue_id`); `observation_id` stays nullable (a supplied miscue has none); partial unique index on `(page_read_id, page_revision_id, expected_token_index) WHERE status = 'candidate'` | ADR-0013 → align rule 7, Supplying a word, Cycles, Practice |
| `practices` | `outcome` + `unclear`, `idle`; `attempt` 1–2 per miscue across activities | ADR-0013 → Practice |
| `page_revisions` | `tokenizer_version` 2 for new revisions (token boundaries unchanged) | ADR-0013 → `norm()` v2 |
| `knowledge_items` | kind + `pattern`; status + `ignored`; status changed only by `item_status.apply`, a cache of the fold over `retrieval_events` and `item_status_events` | ADR-0017 §6.2 |
| `item_status_events` | migration 8: learner_id, item_id, at, day (household date), event (`ignore`/`unignore`/`card_ack`/`card_state`/`card_gone`), source (`brain`/`learner`/`owner`/`anki`), session_id? (set only for `ignore`/`unignore`), activity_id?, card_id?, ivl_days?, lapses?, revlog_id?, revlog_type?; append-only but for `activity_id`; backfilled with one `card_ack` per acknowledged card | M7 design D17 |
| `decision_records` | migration 8: learner_id, session_id, at, turn, record (json: the observation's leaves with their `book` flag, the menu, the decision, the executed activity and its outcome); written from M7e | M7 design D19 |
| `encounters` | trigger + `teach_ok`, `teach_incorrect` | ADR-0013 → Difficulties |
| `anki_outbox` | + `front`, `back`, `sentence` with provenance; written only by `add_cards` | ADR-0017 §7.2 |
| `review_answers` | `ease IN (1,2,3,4)` | ADR-0017 §3.1 |
| `corrections` | + `source_learner_id`, `forgotten` | ADR-0018 §3 |

## Migration 6 (in `storage.py` since M5a)

Egress under M5 (`docs/plans/active/2026-10-23-m5-egress-design.md` D5, D8, D10, D12, D19). `SCHEMA_V5` is frozen: a version-4 file runs step 5 to it and then step 6, each step in its own transaction (`storage._step`); a version-5 file runs step 6 alone and needs no `--learner`. `SEEDS` are the rows a fresh file and step 6 both insert. `tests/test_migration_6.py` asserts schema and seed rows equal a fresh file.

| Entity | Change | Owner of the meaning |
|---|---|---|
| `egress_log` | purpose + `notify` (the parent notification: a learner's surrogate and counts); + `owner` (`pid:start` of the writing process, for recovery of stuck `sending` rows) | design D5, D8 |
| `reading_sessions` | + `owner`, `post_done_at` (written after delivery and extraction; the sweeper and `forget` treat a session as disposable only once it is set) | design D5 |
| `pseudonyms` | new: entity (`learner:<id>`, `former:<id>`, `term:<id>`), surrogate, both unique (surrogate case-insensitively) | design D10 |
| `privacy_state` | new: `protected_version`, bumped by triggers on every insert, delete or name/alias/kind/forgetting update of `learners` and every change to `household_terms`, in the writer's transaction | design D12 |
| `learners.settings` | the privacy keys `privacy.media`, `privacy.school` (`none` or a `household_terms` id of kind `school`) and `privacy.version`, written only by `leafi.privacy.settings` (the harness's `settings.save` refuses them) | design D10, D12 |
| `household_terms` | the household's old `REDACT_TERMS` imported as kind `name` (a learner's own name skipped); since M5d the key is retired: egress imports a leftover value at start, `leafi privacy terms import --yes` also removes it from `.env`, and `leafi privacy terms add|remove` edits the list | design D12 |

## Invariants

- Page text is read only through `pages.current_text()`; verified spans survive re-OCR. Test: `tests/test_corrections.py`.
- `observations` and `corrections` are append-only; `miscues` change status only forward along ADR-0013 and never disappear (`invalidated` with reason). The exceptions are the parent's `forget --session` / `forget --book` commands (ADR-0010 §9).
- A Difficulty exists only per the ADR-0013 formulas (`kind = confirmed | watch` for words, `kind = knowledge` for items with encounters in ≥ 2 sessions).
- `anki_outbox.anki_note_id` is set only from an AnkiConnect response or a dedupe hit; `knowledge_items` never store Anki ids directly.
- Nothing here identifies a person from pixels; Frigate labels are not stored.

## Retention (owner: security.md; summarised here)

| Store | Default retention |
|---|---|
| `page_images`, `cache/pages/` | 7 days |
| learner audio | not stored (`AUDIO_KEEP_CLIPS=false`) |
| `cache/tts/` | 90 days, content-addressed |
| `utterances.text`, `observations`, `miscues`, `practices` | kept (learning history); the only deletions are `python -m leafi forget --session <id>`, `--book <id>` (ADR-0010 §9) and `--learner <id> --yes` (ADR-0018 §1) |
| `data/evals/` transcripts | opt-in (`EVAL_TRANSCRIPTS=true`), 30 days |
| logs | no raw utterance text at INFO; DEBUG only when `LEAFI_DEBUG_TEXT=1` |
| `data/backups/leafi-*.db` | until the owner prunes: `python -m leafi backup --prune` (console 清除旧备份) keeps the newest 3 by time, migration backups included (owner decision 2026-10-23); `forget` never edits a backup and says so |
