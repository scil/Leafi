---
status: proposed
date: 2026-10-24
revision: 2
---

# Content-only egress: design (M5e)

Plan `2026-10-22-ai-led-study.md` → owner decision 2026-10-24 (Decision log: "egress redacts by content only and ignores where a text came from"). Research and reference collection: `docs/research/2026-10-24-content-only-egress.md` (cited as R§n, sources S*n*, owner decisions O*n*). This note is the `derive-project-plan` output; ADR-0021 records the decision and cites it. It supersedes ADR-0018 §2's data-class table and §3's provenance columns and filter, removes three settings of ADR-0018 §5, and supersedes M7 D2 and D3 (`2026-10-23-m7-brain-design.md`). Each decision gives its basis (owner, project constraint, reference, assumption) and each mechanism one provenance line.

History: rev 2 answers round 1 on E8–E9 (`reviews/2026-10-24-egress-e8e9-round-1-comparison.md`, themes U1–U12, cited as U*n*; codex, a fresh Claude and `code-plan-review`, none a false positive) and the owner's U6 answer (cards in other learners' decks are not found; `forget` says so). E8 now uses the migration runner as it is, E9 states the fence as a mechanism, E7's cache deletion and E10's commit order change, and the accepted cost of E9 is corrected.

Status: E1–E7 need no review (owner, 2026-10-24). E8–E9 rev 2: an increment round, one reviewer (codex), per `AGENTS.md`.

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

**E7 Text-to-speech by content.** Basis: owner (O1); reference (M5 D13's protected-name rule). A line is synthesised by Kokoro when its text contains a listed protected name **or a detector entity** (the line scanned as non-book text); otherwise by the configured backend (edge-tts by default) through `prepare`. So a child never hears a surrogate name. The cache sidecar drops `provenance_class` / `source_learners`; `forget --learner` clears the clip cache as E9 says (U9). Provenance: *adapted* from M5 D13 (the class half dropped, the detector added).

**E8 Migration 7: drop the provenance columns, with the runner as it is (U1–U3).** Basis: owner (O4); project constraint (`storage.migrate_file`, `_step`); reference (S2).
- **Freeze before editing (U1).** `SCHEMA_V6 = <today's SCHEMA>` is frozen beside `SCHEMA_V5`; step 6 targets `SCHEMA_V6` (today it targets the live `SCHEMA`, `storage.py:822`, so editing `SCHEMA` would rebuild a v5 file straight into the v7 shape, stamp it 6 and strand it). Then `SCHEMA` loses the 20 columns (`activities.{outcome,assessment}_*`, `brain_calls.{payload,response}_*`, `utterances.*`, `encounters.{context,explanation}_*`, `learner_notes.*`, `book_notes.*`, `anki_outbox.card_*`) and `_PROV`; `SCHEMA_VERSION = 7`.
- **One mechanism (U2).** `migrate_file` gains `if version == 6: _step(conn, 7, SCHEMA, {}, result, _hook)`: `_step` already rebuilds every table whose DDL differs from the target, copying the shared columns, in one transaction, under the exclusive `.users` lock that excludes every `Store` (ADR-0019 §5's protection is this lock; there is no separate `migrate()` `BEGIN IMMEDIATE`). The research's DROP COLUMN finding (S2: legal on all 20 columns, confirmed by all three reviewers) stays a recorded fact, not a second mechanism. A file at 4 or 5 runs its earlier steps first, as today.
- **Cleanup after the commit (U3).** `migrate_file`'s connection sets `PRAGMA secure_delete = ON` (it is a raw connection; `Store` sets it per connection). After the last step commits, still holding the lock: `VACUUM`, then `PRAGMA wal_checkpoint(TRUNCATE)`; a failure there is reported and leaves a valid version-7 file. `leafi migrate` on a file already at the latest version runs the same cleanup again (idempotent), so a crash between the commit and the cleanup is completed by rerunning the command; its output says whether the cleanup completed.
- **Rollout (U2).** `Store` refuses a version-6 file (`NeedsMigration`); the owner runs `python -m leafi migrate` with every Leafi process stopped. It takes its own `leafi-v6-<stamp>.db` backup (no extra manual backup). Restoring that backup gives a version-6 file that needs `leafi migrate` again, and any backup older than a `forget` brings the forgotten learner back (ADR-0019 §8); the rollout and `leafi forget`'s backup notice say both (U10).
- **Numbering (U12).** M7's planned `item_status_events` migration becomes 8 and M7f's interests migration 9 (neither is written); both designs carry the note.
- `tests/test_migration_7.py`: files at 4, 5 and 6 with rows in every table migrate to 7; `schema_of(migrated) == schema_of(fresh)` (as tests 5 and 6 do); none of the 20 columns remains; every row and index survives; `integrity_check` and `foreign_key_check` clean; the failure-injection hook mid-step 7 leaves the file at 6 and a rerun completes; a canary `'[987654321]'` in a `*_source_learners` column (a value no other column holds) is absent from `leafi.db` and `-wal` after the cleanup; a cleanup cut off after the commit is completed by a second `leafi migrate`. `test_migration_6` now migrates to `SCHEMA_V6` and asserts version 6 at that step, not `SCHEMA_VERSION`.
- Provenance: *adopted* from Leafi's migration runner (`_step`, the `.users` lock, the auto-backup; migrations 5 and 6) and SQLite's `VACUUM` / `wal_checkpoint` (ADR-0019 §6–§7); the frozen-schema pattern *adopted* from `SCHEMA_V5`.

**E9 `forget` and the write fence by owning learner (U5–U9, U11).** Basis: owner (O4, U6); project constraint (`learner_store`, `records`, `call`).
- **Owner sets.** `learner_store.DIRECT_OWNED` (today's `DIRECT`, owner in `learner_id`) and `SESSION_OWNED = {activities, utterances, brain_calls}` (owner = `reading_sessions.learner_id` of the row's `session_id`). The other session tables (`cycles`, `page_reads`, `observations`, `miscues`, `practices`) hold no free text that can reach a payload and are written only inside a live session's transactions; `egress_log` is keyed on `learner_id` and stays a plain insert. Both sets are explicit constants, not derived from columns (U5).
- **The fence, in the statement (U5).** `insert` (direct): `INSERT … SELECT … WHERE EXISTS(SELECT 1 FROM learners WHERE id = :learner_id AND forgetting = 0)`. `insert_named` (session-owned): `… WHERE EXISTS(SELECT 1 FROM reading_sessions rs JOIN learners l ON l.id = rs.learner_id WHERE rs.id = :session_id AND l.forgetting = 0)`, so a missing session or learner refuses (`LearnerUnavailable`) instead of raising a foreign-key error. `update_named` puts the same `EXISTS`, joined through the row's own `session_id` or `learner_id`, in the UPDATE's `WHERE` (no separate owner read). The `sources=` argument and `stated_sources` go. `test_architecture` checks that every INSERT or UPDATE of a table in `DIRECT_OWNED | SESSION_OWNED` goes through these functions, using the explicit sets.
- **The audit write (U8).** `call._insert` catches `LearnerUnavailable`, logs the refusal (call id, outcome, no text) and drops the row, which `flush_audit` then pops from `pending_audit`; `_withheld` goes with E6. So a late audit row for a forgetting learner never raises into a Brain call or `finalize`.
- **Names (U7).** Before the rows are deleted, `forget_learner` moves **every** name the lists protect for N — `display_name`, `alias`, and any `household_terms` linked to N — into `household_terms` as `former_learner_id = N`, in the marking transaction.
- **What `forget --learner N` deletes.** N's direct rows; every row reached through N's sessions, including other learners' notes cited only by those sessions' activities (today's citation rule in `_delete_session_records`, kept); `data/learners/<N>/`. `records._purge_derived` and its `json_each(source_learners)` rescan go; **the last transaction repeats the by-owner deletes** (direct tables, `egress_log`) before deleting the `learners` row, so a row written between batches does not make the final delete fail (U11).
- **Stores outside the database (U9).** The TTS clip cache: `forget` receives the configured cache path and deletes the clip entries (`<key>.wav` + `<key>.json`) but never `cache/tts/camera/` (the camera's push folder); an entry whose sidecar is being written is skipped and the pass retried once after the synthesizer's publish lock; a delete that still fails leaves N marked `forgetting` and is reported, so a rerun completes. `data/evals/decisions/` and DEBUG text logs: no writer exists yet (M7e / logging), so `forget` has nothing to delete there today; their writers must register a deletion step when they land. `test_forget` covers the cache deletion and the camera folder kept.
- **Accepted cost, corrected (U6, owner).** Copies of N's words or names stored in **other learners'** rows — M's utterances, Brain calls, notes cited outside N's sessions, encounter explanations, assessments and Anki cards — are not found. They stay in Leafi's database, they keep reaching the cloud redacted when M's later requests include them (E1), and M's Anki cards quoting N stay in Anki and, if the profile syncs, in AnkiWeb. N's names stay replaced in those requests because they moved into `household_terms` (U7), as long as the lists or the detector catch the spelling used. `leafi forget`'s preview, help and report drop "every text derived from them" and say: "Text in other learners' records that mentions them is kept; their names stay replaced when it is sent. Cards in other learners' decks may still mention them; check Anki." (owner, U6).
- Provenance: *adapted* from ADR-0018 §1's fence and forget (the subject changes from source learners to the owning learner; the in-statement `EXISTS` and conditional insert kept).

**E10 Code sites (from the inventory, ≈ 130 sites).**
- `leafi/privacy/`: `egress.py` (pipeline, `Text`, `_gate`, `may_send`, `_plain_strings` now scanned), `settings.py`, `versions.py`; `destinations.py` unchanged.
- `leafi/core/`: `provenance.py` deleted; `ports.py`, `learner_store.py`, `storage.py` (E8), `config.py`, `hub.py` (no `provenance=`).
- `leafi/services/`: `brain/render.py`, `brain/claude.py`, `brain/ollama.py`, `tts/__init__.py`, `tts/edge.py`.
- `leafi/study/`: `brain/{observe,generate,call,kinds,scoring,prompts,sequence}.py`, `cards.py`, `knowledge.py`, `records.py`, `harness/{state,construct,negotiate,activities,inputs,identify,rows}.py`.
- `leafi/devices/notifiers.py`, `leafi/envprotect.py`, `leafi/doctor.py`, `leafi/cli.py` (the stale "keeps their own words off the cloud" lines), `config/env-schema.json`, `.env.example`.
- Order: one commit per layer, each green (U4): (1) redaction rule and `Text.book` with the shim (E1–E3); (2) settings (E4, E5); (3) **in-memory** provenance only — egress, TTS routing, Brain eligibility, `Turn` / `Leaf` / `synth` (E6, E7) — while every storage writer keeps filling the 20 columns through one helper, `learner_store.legacy_prov() -> ("system", "[]")`, and `core/provenance.py` keeps only what `learner_store` imports; (4) after E8–E9's review, in one commit: migration 7, every storage writer (`rows.py`, `activities.py`, `knowledge.py`, `cards.py`, `call._row`), the fence and `forget` (E9), `legacy_prov` and the rest of `core/provenance.py` deleted, and every test file that writes or reads the columns or `SCHEMA_VERSION` (`tests/seed.py`, `test_forget`, `test_learner_store`, `test_migration_5`, `test_migration_6`, `test_open_db`, `test_brain_call`, `test_activity_status`, `test_anki_single_path`, `test_card_checks`, `test_harness_sessions`, `test_architecture`, and the rest that `rg "provenance_class|source_learners|SCHEMA_VERSION" tests` lists at that commit). Between (3) and (4) the fence still checks the owner (`learner_id`) and the constant sources name nobody, so it behaves as an owner fence for direct tables; session-owned inserts are unfenced in that window, which is why (4) follows (3) without a release between them.

**E11 Tests.** Basis: `AGENTS.md` (full suite green; storage changes add a regression test).
- Rewritten to the new rule (the inventory's group F, ≈ 45 functions): every "withheld because of the source / `cloud.text` / guest / parent text / TTS learner lines" case becomes "sent redacted". New cases in `tests/test_privacy.py`: a guest's heard word reaches a cloud body, redacted; a listed name and a detector-found name in a heard word become surrogates and are mapped back; a character name in the page text is **not** replaced (book field) while the same name in a heard word is; plain strings are scanned; with the detector off a lower-case school leaves verbatim (the stated limit, O6); the detector `loading` refuses non-book text inside a session; no audio reference in any body.
- `test_services_mock`: a line with a listed or detected name is spoken by Kokoro; a line without goes to edge-tts.
- `test_forget`: deletion by owner; M's note cited outside N's sessions survives and M's note cited only by N's session activities is deleted (the citation rule); M's card quoting N survives and the report carries the Anki sentence; N's alias moved into `household_terms` and still replaced in M's surviving text afterwards; the TTS clip cache cleared and `camera/` kept; a row inserted between batches does not break the final delete. `test_learner_store`: the fence refuses a direct and a session-owned insert and an update owned by a forgetting learner, and refuses a session that no longer exists; M's writes pass while N is being forgotten; a session adopted from a guest fences on its new owner. `test_brain_call`: `finalize` completes and pops the row when the audit insert is refused. `test_migration_7` (E8). `test_provenance.py` deleted. `test_env_protections`, `test_env_schema`: the two keys gone.
- Provenance: *adopted* from the existing suites.

**E12 Documents.** ADR-0021 (new, short). ADR-0018: §2's table and edge-tts paragraph, §3's columns and filter, §5's three rows, §1's guest lines ("`cloud.text` off"), §4.2's consent purpose, §7–§9 pointers, marked "superseded by ADR-0021" where they change. `security.md` (red line 3, the egress table, the settings rows, the TTS cache retention); `GLOSSARY.md` (Provenance retired; Guest, Egress, Brain reworded; a new "book field" entry); `docs/product.md` principle 2; `docs/architecture/data-model.md`; `docs/engineering/code-locator.md`; `AGENTS.md`'s boundary line keeps egress as the only exit and names ADR-0021; `leafi/cli.py`'s `forget` preview and help (E9's sentence).

**E13 Effect on other plans.** M7 D2 and D3 superseded (D3's per-leaf filter becomes E1's redaction at `prepare`); D10's `answer` / `judge` eligibility and D22's fence follow E6 and E9; D4's relaxed line needs no provenance. M7f rev 4: P4's stamps, guard and per-request re-render, B2's "conversation ends on `cloud.text` off", P5 rule 4's substitute, P6's `[N, 0]` encoding and P7's `cloud.text` cases go; its rev 5 follows this design.

## Rollout

1. Land E1–E7 (commits 1–3): no schema change; the full suite green after each.
2. E8–E9 reviewed (round 1 done; rev 2's increment round next), then land commit 4 right after commit 3.
3. On the owner's PC, with every Leafi process stopped: `python -m leafi migrate` (its own v6 backup, step 7, the cleanup; rerun it if it reports the cleanup incomplete); restart; `leafi doctor` shows no obsolete keys or names them. A restored v6 backup needs `leafi migrate` again, and a backup older than a `forget` brings that learner back (E8).
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
| Migration 7 by `_step` with a frozen `SCHEMA_V6`; cleanup after the commit (E8) | adopted: Leafi's runner and `SCHEMA_V5` pattern; SQLite `VACUUM` / `wal_checkpoint`, ADR-0019 §6–§8 (DROP COLUMN, S2, recorded as legal but not used) |
| `legacy_prov` bridge between commits 3 and 4 (E10) | original: a one-commit shim, searched none needed beyond it |
| Fence by owning learner, in-statement `EXISTS`, explicit owner sets (E9) | adapted: ADR-0018 §1 |
| Audit refusal logged and dropped (E9) | adapted: M7 D8's audit write (the `_withheld` fallback removed) |
| All protected names moved on forget (E9) | adopted: ADR-0018 §1 ("display name and other identifying names") |
| Rejected: label-based flow control (S7, S8), a hosted gateway (S6), a second NER stack now (S4, deferred) | R§5 |
