# Data model (meaning; the schema in `leafi/core/storage.py` is the fact)

Store: SQLite `data/leafi.db`, created on first use, migrated by `PRAGMA user_version` steps in `storage.py`. The legacy habit store `data/sessions.db` stays separate (ADR-0011: consolidation is a future plan). Decisions behind the shape: ADR-0009 (observations vs judgements), ADR-0010 (page revisions).

## Entities

| Entity | Key fields | Lifecycle / meaning |
|---|---|---|
| `books` | id, title, isbn?, language (`en`), level?, created_at, archived_at? | Created when identified (B1) or added by the parent. Never deleted. |
| `pages` | id (internal, stable), book_id, printed_number?, observations (json: first_line, last_line, word_count, line_count — last confirmed set), created_at | One row per physical page. Identity is never derived from text (ADR-0010 §1). `current_text()` returns the latest revision's text. |
| `page_revisions` | id, page_id, rev, text, source (`ocr`/`correction`/`manual`), spans_verified (json list of [start,end]), ocr_backend?, ocr_confidence?, created_at | Immutable. Rev 1 from OCR; each correction appends a revision with its span marked verified; a later OCR never overwrites verified spans. |
| `page_images` | id, page_id, path (under `cache/pages/`), width, captured_at | Deleted after `PAGES_RETAIN_DAYS` (7); the row is deleted with the file. |
| `corrections` | id, page_revision_id (the revision corrected), char_start, char_end, old_text, new_text, source (`voice`/`text`/`parent`), utterance_id?, created_at | Append-only provenance. Applying = insert correction + insert new revision + lexicon update in one transaction. |
| `reading_sessions` | id, book_id, started_at, ended_at?, mode (`voice`/`text`), devices (json), summary? (json counts, no text of the child's questions), lease_token | One sitting. Null `ended_at` = in progress; next start closes stale ones with `summary.interrupted=true`. |
| `page_reads` | id, session_id, page_id, page_revision_id, attempt, started_at, ended_at?, tokens_expected, tokens_committed, tokens_matched, wpm? | One pass over a page at one revision. Repeated reading increments `attempt`. |
| `utterances` | id, page_read_id, page_revision_id, text, words (json: word, start_s, end_s, conf or null), kind (`reading`/`control`/`question`/`correction`), audio_ref? (in-memory only, never persisted unless `AUDIO_KEEP_CLIPS`), created_at | What was heard or typed. Timestamps are relative to the utterance's own audio. |
| `observations` | id, utterance_id, kind (`matched`/`substituted`/`deleted`/`inserted`), token_start, token_end (expected token indexes in the revision; for `inserted`, anchor index), heard_text?, created_at | Raw alignment output (ADR-0009 §1). Never edited. |
| `miscues` | id, observation_id, page_read_id, expected, expected_token_index, heard?, status (`candidate`/`confirmed`/`unsure`/`withdrawn`/`invalidated`), evidence (`none`/`practice`/`acoustic`), score?, phonemes_expected?, phonemes_heard?, invalidated_reason?, updated_at | The judgement layer. Created `candidate` from `substituted`/`deleted` observations; transitions per ADR-0009 §4. Only `confirmed` feeds Difficulties. |
| `practices` | id, miscue_id, attempt (1–2), outcome (`matched`/`disagreed`/`skipped`/`practiced`), evidence (`none`/`acoustic`), created_at | Model-and-repeat attempts; `practiced` + `none` is the text-mode outcome. |
| `knowledge_items` | id, kind (`word`/`phrase`/`grammar`/`fact`/`pronunciation`), language, key (lemma or surface), sense_hint?, status (`new`/`learning`/`known`/`lapsed`), anki_item_key (uuid, stable), created_at, updated_at | Unique on (kind, language, key, sense_hint). `status` moves `new→learning` on first Anki review, `learning→known` when the card's interval ≥ `REVIEW_KNOWN_INTERVAL_DAYS` (21), `known→lapsed` on an Anki lapse, `lapsed→learning` on the next pass. |
| `encounters` | id, knowledge_item_id, session_id, page_revision_id?, context_sentence, explanation_en?, explanation_zh?, trigger (`explain`/`check`/`miscue`/`parent`), created_at | Each time the item came up, with its own context; the item itself holds no context. |
| `difficulties` | id, knowledge_item_id? / miscue_key?, sessions_seen (json ids), count, weight, updated_at | Recomputed by `study/knowledge.py` (rule v1: weight = confirmed count × recency factor; needs ≥ 2 distinct sessions). Never edited by hand; `unsure`/`withdrawn` miscues never contribute. |
| `anki_outbox` | id, knowledge_item_id, op (`add`/`update`), state (`pending`/`sent`/`acked`/`failed`), attempts, last_error?, anki_note_id?, card_ids (json), updated_at | Local synchronisation outbox (ADR-0004 as revised). Before `add`, `findNotes "tag:leafi-id::<anki_item_key>"` dedupes a lost acknowledgement. |
| `review_answers` | id, knowledge_item_id, card_id, ease (1–4, chosen by the learner: again/good only in v1), answered_at, acked (bool) | Written before `answerCards`; `acked` after; repeated `answerCards` on uncertain response is skipped when `acked`. |
| `lexicon` | word, language, source (`book`/`correction`/`manual`), book_id?, weight, updated_at | Advisory in v1 (ADR-0011): candidates for OCR snap and future ASR bias. Rebuilt from revisions + corrections; manual rows survive. |
| `learner_profile` | key, value (json), updated_at | Small facts the coach may use (the name the child gave Leafi, explanation language order). No identity, no images, no embeddings. `REDACT_TERMS` live in config, not here. |

## Invariants

- Page text is read only through `pages.current_text()`; verified spans survive re-OCR. Test: `tests/test_corrections.py`.
- `observations` and `corrections` are append-only; `miscues` change status only forward along ADR-0009 §4 and never disappear (`invalidated` with reason).
- A Difficulty exists only from `confirmed` miscues or `encounters` across ≥ 2 sessions.
- `anki_outbox.anki_note_id` is set only from an AnkiConnect response or a dedupe hit; `knowledge_items` never store Anki ids directly.
- Nothing here identifies a person from pixels; Frigate labels are not stored.

## Retention (owner: security.md; summarised here)

| Store | Default retention |
|---|---|
| `page_images`, `cache/pages/` | 7 days |
| learner audio | not stored (`AUDIO_KEEP_CLIPS=false`) |
| `cache/tts/` | 90 days, content-addressed |
| `utterances.text`, `observations`, `miscues` | kept (learning history); parent deletion command `python -m leafi forget --session <id>` removes a session's utterances and observations, keeping counts |
| `data/evals/` transcripts | opt-in (`EVAL_TRANSCRIPTS=true`), 30 days |
| logs | no raw utterance text at INFO; DEBUG only when `LEAFI_DEBUG_TEXT=1` |
