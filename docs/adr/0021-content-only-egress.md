---
status: proposed
date: 2026-10-24
supersedes: 0018 (§2's data-class table and the source half of its text-to-speech routing; §3's provenance columns and filter; §5's rows `cloud.text`, `cloud.parent_text`, `privacy.tts_learner_lines`)
amends: 0018 (§1 guests and forget, §4.2 consent purposes), 0017 (eligibility of `answer` and `judge`)
---

# Text leaving Leafi is redacted by its content, never gated by its source

Owner decision 2026-10-24 (plan Decision log): "egress redacts by content only and ignores where a text came from", for all of `leafi/`'s cloud traffic; `cloud.text` removed; guests treated like learners; the provenance columns dropped; the name detector scans everything but book fields. Research: [`../research/2026-10-24-content-only-egress.md`](../research/2026-10-24-content-only-egress.md). Design, with one provenance line per mechanism: [`../plans/active/2026-10-24-content-only-egress-design.md`](../plans/active/2026-10-24-content-only-egress-design.md) (cited as E*n*).

**Problem.** ADR-0018 decided per text who may send it: every stored and sent text carried a provenance class and its source learners, and egress refused a learner's own words when that learner's `cloud.text` was off, for every guest, and for parent text when `cloud.parent_text` was off. Running that rule over multi-turn Brain conversations (M7f) needed per-message stamps, a fail-closed guard and a re-render of the whole history at every request. The owner judged the cost too high for this household and chose the rule mature tools use: redact what a text says, at one seam, before it leaves (LangChain `PIIMiddleware`, LLM Guard Anonymize, NeMo Guardrails' PII rails).

**Decision.**
1. Every text bound for a cloud destination is redacted by content and never refused for its source (E1). Pseudonymisation lists apply to every text; the Presidio name detector applies to every text except fields a request declares as book text (`Text.book`: page text, sentences, expected words, titles), so book characters keep their names (E2). Replies are mapped back locally, as before.
2. With the detector off or its model missing, the lists alone apply; while it is still loading inside a session, non-book text for a cloud destination is refused and the call falls back (E3).
3. `cloud.text`, `CLOUD_PARENT_TEXT` and `PRIVACY_TTS_LEARNER_LINES` are removed (E4). A guest's or an unconfirmed session's text is sent redacted like a learner's (E5). `answer` and `judge` may use any configured backend (E6).
4. A line is spoken by Kokoro when it contains a listed name or a detected entity, otherwise by the configured TTS backend through egress (E7).
5. Migration 7 drops `provenance_class` and `source_learners` from every table with `ALTER TABLE … DROP COLUMN`, followed by one `VACUUM` (E8). `forget --learner` deletes by owning learner and session; the write fence checks the owning learner (E9).

Unchanged: egress as the only exit (tokens, the mediating transport, the socket guard, `egress_log`), locality for `LOCAL_MODELS`, media consent and the remote teacher, the Anki notice, `ops` payloads, the habit track (ADR-0011).

**Consequences.** Less code and no per-request source checks: the provenance type, its propagation, the substitutes and the stamps go. Protection of names now rests on the lists and the detector alone, and Presidio states "there is no guarantee that Presidio will find all sensitive information"; the round-1 probe already saw it miss lower-case names. So a friend's name, an unanswered school or a typed lower-case name can reach the cloud verbatim, most of all with the detector off; the owner accepted this. A child's own words, a guest's words and parent-written text now reach the cloud by default, redacted. `forget --learner` no longer finds a copy of a learner's text stored in another learner's rows; the forgotten learner's names stay replaced in later requests because they move into `household_terms`. Changing the policy keys requires restarting every Leafi process once.

**Confirmation.** The full suite passes with E11's rewritten cases: a guest's heard word reaches a cloud body redacted; listed and detected names become surrogates and are mapped back; a character name in a book field is kept while the same name in a heard word is replaced; plain strings are scanned; with the detector off a lower-case school leaves verbatim; the detector loading refuses non-book text inside a session; Kokoro speaks every line with a listed or detected name; `test_migration_7` (columns gone, rows and indexes kept, integrity clean, a canary absent after `VACUUM`); `test_forget` (by owner; a sibling's note naming the learner survives; the fence refuses a write owned by a forgetting learner). Reviews of E8–E9: three reviewers, in parallel (`AGENTS.md`).
