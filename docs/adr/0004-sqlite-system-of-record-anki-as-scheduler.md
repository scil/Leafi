---
status: accepted
date: 2026-10-19
---

# Leafi's SQLite is the system of record; Anki schedules review

## Context

The learner's books, pages, miscues and knowledge items must be stored and reviewed on a spacing schedule. The household already uses Anki with the AnkiConnect add-on, FSRS, and the shared `anki-cards` tooling.

## Decision drivers

- One owner per fact; review scheduling is a solved problem in Anki (FSRS).
- Leafi must work when Anki is closed.
- Cards must be curatable by the parent in Anki's own UI.

## Considered options

1. Implement spaced repetition inside Leafi (own FSRS), never touch Anki.
2. Make Anki the only store: write everything as notes, read state back.
3. Leafi's SQLite holds books/pages/sessions/miscues/knowledge; Anki holds cards and their schedule; `knowledge_items.anki_note_id` links them; Leafi reads due cards and review outcomes through AnkiConnect to update `status`.

## Decision outcome

Option 3. Deck `Leafi`, note type `问答题` (fields `正面`/`背面`) in the bilingual English-first layout the `anki-cards` skill already uses; tag `leafi::<book-slug>` plus `lib::` style topic tags. Push happens at session wrap; a review turn at session start reads `findCards "deck:Leafi is:due"`, asks through the Faces/Mouths, and answers with `answerCards`.

## Consequences

- Anki absent → items queue (null `anki_note_id`) and are pushed later; review turn is skipped.
- Card copy must follow the `anki-cards` skill's no-redundancy and short-card rules; `study/knowledge.py` owns the card builder.
- The habit track's `data/sessions.db` stays separate until T2.

## Confirmation

`tests/test_anki.py` with a fake AnkiConnect server: push, idempotent re-push, due-card fetch, answer; queue when unreachable.
