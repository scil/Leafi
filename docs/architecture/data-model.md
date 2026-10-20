# Data model (meaning; the schema in `leafi/core/storage.py` is the fact)

Store: SQLite `data/leafi.db`, created on first use, migrated by `PRAGMA user_version` steps in `storage.py`. The legacy habit store `data/sessions.db` stays separate until T2.

## Entities

| Entity | Key fields | Lifecycle / meaning |
|---|---|---|
| `books` | id, title, isbn?, language (`en`), level?, created_at | Created when identified (B1) or added by the parent. Never deleted; `archived_at` hides it. |
| `pages` | id, book_id, number?, fingerprint, text_ocr, text_truth?, ocr_backend, ocr_confidence, image_path?, updated_at | One row per physical page seen. `fingerprint` = normalised first 12 words hash, used when `number` is unknown. **Page text = `text_truth` if not null else `text_ocr`.** `image_path` is a local file under `cache/pages/` and is deleted after `pages.retain_days` (default 7). |
| `corrections` | id, page_id, span_start, span_end, ocr_text, truth_text, source (`voice`/`text`/`parent`), created_at | Append-only. Applying a correction rewrites `pages.text_truth`; the row stays as provenance and feeds `lexicon`. |
| `reading_sessions` | id, book_id, started_at, ended_at?, mode (`voice`/`text`), devices (json), summary? | One sitting. `ended_at` null = in progress; the next start closes stale ones (crash recovery). |
| `page_reads` | id, session_id, page_id, attempt, started_at, ended_at, words_expected, words_read, words_correct, wpm? | One pass over a page. Repeated reading = `attempt` 2, 3… (B12). |
| `utterances` | id, page_read_id, text, words (json: word, start, end, conf), started_at | What was heard or typed. Audio itself is not stored unless `audio.keep_clips` is on (default off); then a path under `cache/audio/`. |
| `miscues` | id, page_read_id, expected, heard?, kind (`mispronounced`/`skipped`/`inserted`/`unsure`), phonemes_expected?, phonemes_heard?, score?, resolved (bool), created_at | A Verdict other than `read`. `resolved` flips when a Practice retry scores `read`. |
| `knowledge_items` | id, kind (`word`/`phrase`/`grammar`/`fact`/`pronunciation`), key, book_id?, page_id?, context, explanation_en, explanation_zh?, anki_note_id?, status (`new`/`learning`/`known`), seen_count, last_seen_at, created_at | Unique on (kind, key). `status` follows Lute's idea of a term status and is advanced by Review outcomes reported from Anki. |
| `difficulties` | id, knowledge_item_id?, miscue_key?, count, last_at, weight | A recurring Miscue or Knowledge item. `weight` orders Practice and card creation. Recomputed by `study/knowledge.py`, never edited by hand. |
| `lexicon` | word, source (`book`/`correction`/`manual`), book_id?, weight, updated_at | Words that bias ASR hotwords and OCR post-correction. Rebuilt from pages + corrections; manual rows survive rebuilds. |
| `learner_profile` | key, value (json), updated_at | Small facts the coach may use: name the child chose for Leafi, preferred explanation language order, known-word count. No images, no face embeddings. |

## Invariants

- Page text is derived, never stored twice: readers call `Page.text`, which prefers `text_truth`. Test: `tests/test_pages.py`.
- `miscues.expected` is always a word of the Page text at the time of the read; a later Correction does not rewrite history.
- `knowledge_items.anki_note_id` is set only after AnkiConnect returns an id; a failed push leaves it null and the item is retried next session.
- Nothing in this database identifies a person from pixels. Face labels from Frigate are strings chosen by the parent and are not stored here.

## Enums

- `miscues.kind`: `mispronounced` (word heard, differs), `skipped` (expected word absent), `inserted` (heard word not expected; stored with `expected` = the following expected word), `unsure` (ASR confidence below `alignment.unsure_below`).
- `knowledge_items.status`: `new` → `learning` (first Anki review done) → `known` (Anki interval ≥ `review.known_interval_days`, default 21).
