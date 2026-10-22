# Data model (meaning; the schema in `leafi/core/storage.py` is the fact)

Store: SQLite `data/leafi.db`, created on first use, migrated by `PRAGMA user_version` steps in `storage.py`. The legacy habit store `data/sessions.db` stays separate (ADR-0011: consolidation is a future plan). Decisions behind the shape: ADR-0009 (observations vs judgements), ADR-0010 (page revisions).

## Entities

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
| `learner_profile` | key, value (json), updated_at | Small facts the coach may use (the name the child gave Leafi, explanation language order). No identity, no images, no embeddings. `REDACT_TERMS` live in config, not here. |

## Migration 5 (accepted; not yet in `storage.py`)

ADR-0017, ADR-0018 and ADR-0013 v2 change the shape above in one migration (ADR-0018 §7.2: an empty file is created at the latest schema; a version-4 file with data is migrated by `python -m leafi migrate --learner "<name>"` in one transaction). The entity table above describes schema 4 until the migration lands; then the table is rewritten from `storage.py`.

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
| provenance | `provenance_class` and `source_learners` (NOT NULL, no default) on every stored text that can reach a payload | ADR-0018 §3 |
| `page_reads` | + `cycle_id`; at most one per `(cycle, page, revision)`; + counts `self_corrections`, `repetitions`, `off_task_words`; `reading_state` json + `off_task_run` | ADR-0013 → Definitions, Running-record conventions |
| `observations` | kind + `off_task`; + `category` (`exact`/`phones`/`fuzzy`/`inflection`/`substitute`/`function_word`), `repeat`, `self_correction` | ADR-0013 → align rule 5 |
| `miscues` | + `cycle_id` (the owning cycle); `unsure_reason` + `unclear` | ADR-0013 → Cycles, Practice |
| `practices` | `outcome` + `unclear` | ADR-0013 → Practice |
| `page_revisions` | `tokenizer_version` 2 for new revisions (token boundaries unchanged) | ADR-0013 → `norm()` v2 |
| `knowledge_items` | kind + `pattern`; status + `ignored`; status changed only by `item_status.apply` | ADR-0017 §6.2 |
| `encounters` | trigger + `teach_ok`, `teach_incorrect` | ADR-0013 → Difficulties |
| `anki_outbox` | + `front`, `back`, `sentence` with provenance; written only by `add_cards` | ADR-0017 §7.2 |
| `review_answers` | `ease IN (1,2,3,4)` | ADR-0017 §3.1 |
| `corrections` | + `source_learner_id`, `forgotten` | ADR-0018 §3 |

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
| `utterances.text`, `observations`, `miscues`, `practices` | kept (learning history); the only deletions are `python -m leafi forget --session <id>` and `--book <id>` (ADR-0010 §9) |
| `data/evals/` transcripts | opt-in (`EVAL_TRANSCRIPTS=true`), 30 days |
| logs | no raw utterance text at INFO; DEBUG only when `LEAFI_DEBUG_TEXT=1` |
