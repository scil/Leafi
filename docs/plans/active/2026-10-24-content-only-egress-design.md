---
status: proposed
date: 2026-10-24
revision: 1
---

# Content-only egress: design (M5e)

Plan `2026-10-22-ai-led-study.md` → owner decision 2026-10-24 (Decision log: "egress redacts by content only and ignores where a text came from"). Research and reference collection: `docs/research/2026-10-24-content-only-egress.md` (cited as R§n, sources S*n*, owner decisions O*n*). This note is the `derive-project-plan` output; ADR-0021 records the decision and cites it. It supersedes ADR-0018 §2's data-class table and §3's provenance columns and filter, removes three settings of ADR-0018 §5, and supersedes M7 D2 and D3 (`2026-10-23-m7-brain-design.md`). Each decision gives its basis (owner, project constraint, reference, assumption) and each mechanism one provenance line.

Status: not reviewed. Under `AGENTS.md` the privacy choices need no review (owner, 2026-10-24); **the migration, `forget` and the write fence (E8, E9) do**: codex, `code-plan-review` and a fresh Claude on those sections, in parallel, then compared.

## What stays

Basis: project constraint (unchanged by O1–O7).
- `leafi.privacy.egress` stays the only exit: destination allow-lists, attempt tokens bound to the body's HMAC, the mediating transport, the socket guard, `egress_log`, the budget per transmission (ADR-0018 §2, M5).
- **Locality**: a destination on `LOCAL_MODELS` receives text unredacted, as today.
- Pseudonymisation **lists** (household names, schools, `household_terms`, the age band) and the replies mapped back locally (ADR-0018 §3 steps 1 and the last line).
- **Media** (audio, images): per-item consent and the remote-teacher flow (ADR-0018 §4); a guest still never consents to media (§1).
- The Anki notice (card text may sync to AnkiWeb outside Leafi).
- `ops` purposes: fixed schemas, no learner data.
- The habit track (`agent/`, ADR-0011) (O7).

## Decisions

**E1 One rule: cloud-bound text is redacted by content, never refused by its source.** Basis: owner (O1). `prepare`'s pipeline for study purposes becomes: destination allow-list → locality → **redaction** (E2) → media check → write the attempt → transmit. `_gate`, `may_send`, every source refusal ("cloud.text off", "a guest", "parent text", "unknown provenance"), the substitutes and `withheld` counts go. A text is never refused for what it is; it is sent redacted. The only text refusals left: the detector `loading` inside a session (E3) and the version/fingerprint checks of `admit` (E6). Provenance: *adapted* from content-redaction middleware at one seam before the model call (LangChain `PIIMiddleware` S3, LLM Guard Anonymize S4, NeMo PII rails S5); Leafi keeps its own lists and surrogates instead of their detectors (R§5).

**E2 What is redacted where.** Basis: owner (O5); reference (S5's per-field scope).
- **Lists** apply to every text of every request, book text included (as today: a household name in a book is replaced too).
- **The detector** (Presidio PERSON / ORGANIZATION / LOCATION) applies to every text **except book fields**. `leafi.privacy.egress.Text` gains `book: bool = False`; the request builders set it on the page text, the sentences, the expected words and book titles (`observe.page`, `kinds.*_sections`, `generate.learner_context`'s page part, `prompts`' page helpers); everything else, including plain strings, is scanned. `Text(value, provenance, sources)`'s old constructor is kept for one release as a shim that maps `provenance == "page"` to `book=True` and ignores the rest, so edge-tts and every M5 caller keep working until E10's commit converts them.
- A detected entity not on the lists becomes a surrogate like a listed one and is mapped back in the reply (ADR-0018 §3, unchanged).
- Provenance: lists and map-back *adopted* from ADR-0018 §3 (reversible placeholders as S4's Vault, S6's numbered placeholders); the book flag *original* (searched: S3–S6 scope by message role, not by field; Leafi's requests mix book and other text in one message, so the scope is per `Text`).

**E3 Detector states.** Basis: owner (O6, ADR-0018's 2026-10-23 decision); project constraint (M7 D8).
- `privacy.name_detector = off`, or the model missing: lists only; `leafi doctor` keeps reporting it; an unanswered school, a friend's name or a lower-case name then leaves verbatim (O6, stated in ADR-0021).
- `loading` or `unloaded` inside a session: non-book text for a cloud destination is refused with `detector not ready` (M7 D8 today, widened from learner leaves to non-book text), so the call falls back; outside a session `prepare` waits, as today.
- Provenance: *adopted* from M7 D8's detector state machine.

**E4 Settings removed.** Basis: owner (O2); project constraint (the inventory, group E).
- Learner key `cloud.text`: removed from `privacy/settings.KEYS`; a stored value is ignored on read and the writer refuses the key; `LearnerPrivacy.cloud_text` and `cloud_text_allowed` go; `consents` rows with purpose `cloud_text` stay as history, none is written (the CHECK keeps the value).
- Household `.env` keys `CLOUD_PARENT_TEXT` and `PRIVACY_TTS_LEARNER_LINES`: removed from `config/env-schema.json`, `.env.example`, `envprotect.PRIVACY_FLOOR`, `versions.POLICY_KEYS` and `core/config.py`; an existing value in `.env` is ignored and `leafi doctor` names it as obsolete. Removing a key from `POLICY_KEYS` changes the policy fingerprint once, so a running process refuses study text until restarted (M5d behaviour); the rollout restarts every Leafi process (E11).
- Provenance: *original* (a removal).

**E5 Guests and unconfirmed sessions.** Basis: owner (O3). Text from a guest or a session not yet confirmed by `identify` is redacted and sent like an enrolled learner's. Unchanged for guests: no media consent, no export, no post-session notes, the guest end states and sweep (ADR-0018 §1). Identification prompts keep their local TTS by E7 (they contain names). Provenance: *original* (a removal).

**E6 The provenance type and its propagation go.** Basis: owner (O1, O4); project constraint (inventory groups B, C).
- Removed: `leafi/core/provenance.py` (`Provenance`, `PARENT_SOURCE`, `join`, `of_output`, `SYSTEM`, `Leaf.prov`, `Leaf.substitute`), `Turn.provenance`, `Synthesizer.synth(provenance=)`, `Content.provenance`, `Result.provenance`, `content_provenance`, `explanation_provenance`, `render.filter_turns` and `AssistantTurnWithheld`, `call._withheld`.
- `Leaf` becomes `(value, book: bool)`; `Turn` keeps `role` and `sections`.
- `Brain.eligible`: `answer` and `judge` may use any configured backend (`CallContext.may_use_cloud_text` goes).
- `versions.snapshot` keeps a version check for the **request's learner** (school and media settings, household terms) instead of per source learner.
- The parent notification always names the learner by surrogate (the lists replace the real name anyway).
- Provenance: *original* (a removal).

**E7 Text-to-speech by content.** Basis: owner (O1); reference (M5 D13's protected-name rule). A line is synthesised by Kokoro when its text contains a listed protected name **or a detector entity** (the line scanned as non-book text); otherwise by the configured backend (edge-tts by default) through `prepare`. So a child never hears a surrogate name. The cache sidecar drops `provenance_class` / `source_learners`; `forget --learner` deletes the whole `cache/tts/` (a 90-day cache). Provenance: *adapted* from M5 D13 (the class half dropped, the detector added).

**E8 Migration 7: drop the provenance columns.** Basis: owner (O4); reference (S2); project constraint (§2 of the research).
- Steps, one transaction under `migrate()`'s `BEGIN IMMEDIATE` (ADR-0019 §5): `ALTER TABLE … DROP COLUMN` for `activities.{outcome,assessment}_{provenance_class,source_learners}`, `brain_calls.{payload,response}_*`, `utterances.*`, `encounters.{context,explanation}_*`, `learner_notes.*`, `book_notes.*`, `anki_outbox.card_*`; `SCHEMA` edited to match so a new file is created without them; `SCHEMA_VERSION = 7`.
- Before: `python -m leafi backup` (ADR-0019 §8), with every Leafi process stopped, as migrations 5 and 6 (ADR-0018 §7.2). After: one `VACUUM` (with `secure_delete` already on, ADR-0019 §7), so the dropped values leave the file's free pages.
- Numbering: M7's planned `item_status_events` migration becomes 8 and M7f's interests migration 9 (neither is written yet).
- `tests/test_migration_7.py`: a version-6 file with rows in every table migrates; `PRAGMA table_info` has none of the columns; every row and index survives; `PRAGMA integrity_check` and `foreign_key_check` clean; a canary value from a dropped column is absent from the file after the `VACUUM`; a version-7 file opens without migrating.
- Provenance: *adopted* from SQLite's DROP COLUMN (S2, 3.35.0+; this PC runs 3.54.1) and Leafi's migration runner.

**E9 `forget` and the write fence by owner, not by source.** Basis: owner (O4); project constraint (inventory group D).
- `forget --learner N` deletes N's direct rows (`learner_id`) and every row reached through N's sessions (`session_id → reading_sessions.learner_id`), as ADR-0018 §1 already lists; `records._purge_derived` and its rescan by `json_each(source_learners)` go. `forget --session` / `--book` unchanged.
- **Accepted cost**: a derived text about N stored in another learner's rows (a sibling's note mentioning N, a card) is no longer found by `forget`. N's names still move into `household_terms` before the row is deleted, so they stay replaced in every later cloud request (ADR-0018 §1); the stored copy itself stays local.
- The fence (`learner_store.insert_named`, `update_named`): a write is refused when the row's **owning learner** (its `learner_id`, or its session's learner) is being forgotten or gone, in the same transaction (a conditional insert), instead of checking every source learner. `brain_calls` rows of a session whose learner is being forgotten are refused (the audit write logs and drops them, M7 D8). `test_architecture`'s fence regex follows.
- Provenance: *adapted* from ADR-0018 §1's fence (the subject changes from source learners to the owning learner).

**E10 Code sites (from the inventory, ≈ 130 sites).**
- `leafi/privacy/`: `egress.py` (pipeline, `Text`, `_gate`, `may_send`, `_plain_strings` now scanned), `settings.py`, `versions.py`; `destinations.py` unchanged.
- `leafi/core/`: `provenance.py` deleted; `ports.py`, `learner_store.py`, `storage.py` (E8), `config.py`, `hub.py` (no `provenance=`).
- `leafi/services/`: `brain/render.py`, `brain/claude.py`, `brain/ollama.py`, `tts/__init__.py`, `tts/edge.py`.
- `leafi/study/`: `brain/{observe,generate,call,kinds,scoring,prompts,sequence}.py`, `cards.py`, `knowledge.py`, `records.py`, `harness/{state,construct,negotiate,activities,inputs,identify,rows}.py`.
- `leafi/devices/notifiers.py`, `leafi/envprotect.py`, `leafi/doctor.py`, `leafi/cli.py` (the stale "keeps their own words off the cloud" lines), `config/env-schema.json`, `.env.example`.
- Order: one commit per layer, each green: (1) redaction rule and `Text.book` with the shim (E1–E3); (2) settings (E4, E5); (3) provenance type and TTS (E6, E7); (4) migration, `forget`, fence (E8, E9), after its review.

**E11 Tests.** Basis: `AGENTS.md` (full suite green; storage changes add a regression test).
- Rewritten to the new rule (the inventory's group F, ≈ 45 functions): every "withheld because of the source / `cloud.text` / guest / parent text / TTS learner lines" case becomes "sent redacted". New cases in `tests/test_privacy.py`: a guest's heard word reaches a cloud body, redacted; a listed name and a detector-found name in a heard word become surrogates and are mapped back; a character name in the page text is **not** replaced (book field) while the same name in a heard word is; plain strings are scanned; with the detector off a lower-case school leaves verbatim (the stated limit, O6); the detector `loading` refuses non-book text inside a session; no audio reference in any body.
- `test_services_mock`: a line with a listed or detected name is spoken by Kokoro; a line without goes to edge-tts.
- `test_forget`: deletion by owner; a sibling's note naming N survives (the stated cost); the fence refuses a write owned by a forgetting learner. `test_migration_7` (E8). `test_provenance.py` deleted. `test_env_protections`, `test_env_schema`: the two keys gone.
- Provenance: *adopted* from the existing suites.

**E12 Documents.** ADR-0021 (new, short). ADR-0018: §2's table and edge-tts paragraph, §3's columns and filter, §5's three rows, §1's guest lines ("`cloud.text` off"), §4.2's consent purpose, §7–§9 pointers, marked "superseded by ADR-0021" where they change. `security.md` (red line 3, the egress table, the settings rows, the TTS cache retention); `GLOSSARY.md` (Provenance retired; Guest, Egress, Brain reworded; a new "book field" entry); `docs/product.md` principle 2; `docs/architecture/data-model.md`; `docs/engineering/code-locator.md`; `AGENTS.md`'s boundary line keeps egress as the only exit and names ADR-0021.

**E13 Effect on other plans.** M7 D2 and D3 superseded (D3's per-leaf filter becomes E1's redaction at `prepare`); D10's `answer` / `judge` eligibility and D22's fence follow E6 and E9; D4's relaxed line needs no provenance. M7f rev 4: P4's stamps, guard and per-request re-render, B2's "conversation ends on `cloud.text` off", P5 rule 4's substitute, P6's `[N, 0]` encoding and P7's `cloud.text` cases go; its rev 5 follows this design.

## Rollout

1. Land E1–E7 (commits 1–3): no schema change; the full suite green after each.
2. Review E8–E9 (three reviewers), then land commit 4.
3. On the owner's PC, with every Leafi process stopped: `python -m leafi backup`, then the first open migrates to 7, then `VACUUM`; restart; `leafi doctor` shows no obsolete keys or names them.
4. M10 measures the detector's recall on this household's transcripts and typed lines (R§6), the only protection left for names the lists do not hold.

## Provenance table (code-plan-review H7)

| Mechanism | Provenance |
|---|---|
| Redaction at one seam before every cloud call (E1) | adapted: LangChain `PIIMiddleware`, LLM Guard Anonymize, NeMo PII rails (S3–S5) |
| Lists, surrogates, map-back (E2) | adopted: ADR-0018 §3 (cf. S4 Vault, S6 placeholders) |
| `Text.book` field scope (E2) | original: S3–S6 scope by message role; Leafi needs per-text scope |
| Detector states (E3) | adopted: M7 D8 |
| Settings removal (E4), guests (E5), type removal (E6) | original: removals |
| TTS by content (E7) | adapted: M5 D13 |
| DROP COLUMN migration, `VACUUM` (E8) | adopted: SQLite S2; ADR-0019 §7–§8 |
| Fence by owning learner (E9) | adapted: ADR-0018 §1 |
| Rejected: label-based flow control (S7, S8), a hosted gateway (S6), a second NER stack now (S4, deferred) | R§5 |
