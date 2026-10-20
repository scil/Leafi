---
status: accepted
date: 2026-10-19
---

# Pages have stable identities and immutable text revisions; corrections and assessments reference revisions

## Context

The first data model identified a page by a hash of its first twelve OCR words and stored corrections as free offsets. Codex review round 1 (A3, A4, D2) showed that identity then changes whenever OCR changes, collides across pages with the same opening, and that a correction cannot be located or audited once text length changes; the flow also deleted miscues, contradicting the "history is immutable" invariant.

## Decision outcome

1. **Stable page identity.** `pages.id` is internal and never derived from text. Matching an observed page to a stored one uses, in order: `(book_id, printed_number)` when a number is read with confidence; else a set of observations (`first_line`, `last_line`, `word_count`, `line_count`) scored against stored pages of the same book; a score below `page.match_confident` (0.9) or two close candidates → state `PAGE_UNCERTAIN`, Leafi asks ("Is this page 12?"), and assessment is suspended until confirmed. A confirmed match stores the new observation set for that page.
2. **Immutable revisions.** `page_revisions(id, page_id, rev, text, source: ocr|correction|manual, spans_verified: json, created_at)`. OCR creates rev 1; a correction creates rev n+1 with the corrected span marked verified in `spans_verified`; untouched spans keep their OCR status. `Page.text` is the latest revision's text. A corrected page is OCR-trusted only on its unverified spans; a new OCR of the same page never overwrites verified spans.
3. **Corrections are located.** `corrections(id, page_revision_id, char_start, char_end, old_text, new_text, source: voice|text|parent, utterance_id?, created_at)`; spans are character offsets in the referenced revision. Applying a correction is one SQLite transaction: insert correction, insert the new revision, update lexicon rows.
4. **Assessments reference what they assessed.** `utterances.page_revision_id`, `miscues.utterance_id`, `miscues.expected_token_index` (token index in that revision), `miscues.status (candidate|confirmed|unsure|withdrawn|invalidated)`, `miscues.invalidated_reason`. A correction that covers a miscue's token marks it `invalidated` with reason `page_text_corrected`; nothing is deleted.
5. **Asynchronous results carry their revision.** Any result produced after a delay (Brain explanation, OCR second pass) is applied only if `(session_id, page_revision_id)` still matches the current state; otherwise it is discarded and logged.

## Consequences

- Three tables instead of one for page text; reads go through `pages.current_text()` and never through `page_revisions` directly.
- Crash during a correction leaves no partial state (single transaction).
- The parent can audit every change in Anki-like fashion: who said what was wrong, when.

## Confirmation

`tests/test_pages.py`: identity by number, identity by observations, uncertain → confirm; `tests/test_corrections.py`: revision chain, verified spans survive re-OCR, miscue invalidation with reason, transaction rollback on failure; `tests/test_async_guard.py`: stale Brain result rejected.
