---
status: proposed
date: 2026-10-21
revised: 2026-10-22 (codex design reviews 1–6 and the code-plan-review of 2026-10-21 with the owner's eight decisions; see Reviews)
supersedes: 0011 (egress policy section only; its v1 scope list stays except the Ollama deferral, lifted here under §2's conditions)
amends: 0010 (§9 deletion covers the new tables)
---

# Several learners, recognised locally; learner text may go to the cloud by the learner's setting, pseudonymised; audio and images only with bound per-item consent

Owner decisions of 2026-10-21 (research [`../research/2026-10-21-ai-led-study.md`](../research/2026-10-21-ai-led-study.md) §1, decisions 2, 4–7; pool D14, D18, D20) and of 2026-10-22 on the code-plan-review (guest kept one week; guests never consent to media; a household time zone; a Learners tab with a parent PIN; `forget` reaches every local store; a voice disagreement is not a failure; face only after measurement; locality by model allow-list). The previous rule — text only, never the learner's name or own words — was judged too strict by the owner. The habit track (`agent/`) is outside this ADR; its `NOTIFY_WITH_SNAPSHOT` opt-in stays governed by AGENTS.md as before. **`security.md` owns the egress table** once this ADR is accepted; this ADR records the decision and §2 states the table the rewrite starts from.

## 1. Learners and identity

`learners` (id, kind ∈ `learner` | `guest` | `anonymous`, display_name, birth_year?, school_year?, alias, alias_age_band, settings json, recognition json, settings_version, created_at, guest_expires_at?). `anonymous` is one permanent row that owns the counts of discarded guest sessions; it is never deleted and has no settings. Ownership:

- Direct `learner_id` (NOT NULL): `reading_sessions`, `knowledge_items`, `difficulties`, `retrieval_events`, `learner_notes`, `book_notes`, `review_answers`, `anki_outbox`, `consents`, `egress_log`.
- Through `session_id` (a NOT NULL column on each; queries join): `activities`, `cycles`, `brain_calls`, `page_reads`, `utterances`, `encounters` (with `session_id` now required; the parent trigger uses the parent's session of record, §6.1). `observations`, `miscues`, `practices` reach a session through `utterances` / `page_reads`.
- Shared by the household: `books`, `pages`, `page_revisions`, `page_images`, `corrections` (with `source_learner_id`, §3), `lexicon`.

Keys: `knowledge_items` unique on `(learner_id, kind, language, key, sense_hint)`; `difficulties` per learner; `anki_item_key` per learner and each learner's own deck; card dedupe by `(learner_id, lemma)`; interrupted-session and "continue from page N?" lookups by `(learner_id, book_id)`. All of these go through one learner-scoped store API (§6.1).

**Forget.** `forget --learner <id>` deletes the direct rows, every row reached through that learner's sessions (including `brain_calls` payloads, `activities`, `cycles`, `egress_log`), `data/learners/<id>/`, the learner's `data/evals/decisions/` records, `cache/tts` clips synthesised from lines with that learner as a source (`cache/tts` keys record provenance, §3), and DEBUG text logs naming the session; it offers deleting the learner's Anki deck as a separate confirmation; magpie's own logs are outside Leafi and the parent is told so. It refuses while that learner owns a session with `ended_at IS NULL` and the speech lease is held, and works in small transactions so a running session of another learner is never blocked past `busy_timeout`. `forget --session` / `--book` (ADR-0010 §9) also delete `activities`, `cycles`, `brain_calls`, `retrieval_events` and `egress_log` rows of the sessions they reach.

**Who is studying.** `identify(s)` runs inside the session (ADR-0017 §2), so the control latch, the deadline and `finalize` cover it. The session starts owned by a fresh guest row; confirming a learner re-keys that session and its rows to the learner, deletes the empty guest row and bumps the epoch, in one transaction. Identification utterances are used in memory and never stored. Until confirmed: the egress filter treats `cloud.text` as off, `cloud.media` is `never`, recognition results are not stored, and prompts use the local TTS only. Every `ask` and `confirm` waits `ASK_S` (8 s), capped by the session deadline. In text mode there is no voice match: the console list is the identification.

```
identify(s) -> Learner:
  u = ask("Hello! Who's reading today?")                   # u is the utterance recognition uses; typed → no voice match
  if no valid samples arrived while asking: raise ListenerLost                          # a dead Ear is terminal, not "no match"
  cands_v = [l for l in learners(kind=learner) if l.recognition.voice]
  cands_f = [l for l in learners(kind=learner) if l.recognition.face and l.recognition.face_measured]   # decision 7
  v = speaker_match(u, cands_v); f = face_match(eye_frame, cands_f) if face_in_frame(eye_frame) else absent
  per modality: accept(L) if best ≥ RECOG_ACCEPT[ear] and best − second ≥ RECOG_MARGIN[ear]; else ambiguous / none
  guess = L if one modality accepts L and the other does not accept a different learner, else None
  name = parse_name(u)
  if guess and (name is None or name ≈ guess.name) and confirm("Is that you, <guess>?"): return guess
  for attempt in (1, 2):
    if name is None: name = parse_name(ask("What's your name?"))
    if name matches an enrolled learner (fuzzy ≥ 0.85 or a console pick) and confirm("<name>?"): return that learner
    if name is new and confirm("Shall I remember you as <name>?"): return enrol(name)    # asks age or school year
    if name == "don't remember me": s.guest_reason = "declined"; return s.learner
    name = None
  say("Today will be saved for a grown-up to check.")       # the child is told
  s.guest_reason = "unconfirmed"; return s.learner
```

**Guests.** A guest (`kind = guest`) has `cloud.text` off, `cloud.media = never`, recognition off, no export and no parent notification. A guest session that ended `unconfirmed` is **kept for one week** (`guest_expires_at`, owner decision) with its learning record: the parent assigns it to a learner in the Learners tab (its rows are re-keyed and the guest row deleted) or discards it. A `declined` guest, or an unassigned one past `guest_expires_at`, is deleted as by `forget --learner`; its session rows keep only the counts, re-keyed to `anonymous`. The sweep's predicate is `kind = 'guest' AND (guest_reason = 'declined' OR guest_expires_at < now) AND EXISTS(session) AND NOT EXISTS(session with ended_at IS NULL)`; it runs at session start after the lease is acquired and before `new_guest()`, and daily under the supervisor.

**Recognition** is on by default for every enrolled learner (owner decision 2), turned off per modality by the learner or parent (which deletes that learner's embedding for it). Voice is primary: a sherpa-onnx speaker-embedding model. **Face counts only after its hit rate is measured on the real study camera position** and recorded in the plan (`recognition.face_measured`); the study camera frames the book, so a frame with no face of sufficient size makes the modality `absent`, not `none` (owner decision 7). Thresholds are per Ear (`RECOG_ACCEPT[ear]`, `RECOG_MARGIN[ear]`), each from a probe that brackets the same child across sessions against sibling pairs; enrolment records the Ear it used. Embeddings live in `data/learners/<id>/` and never leave the machine. Red line 01 of the habit track is unchanged.

**Who may consent and approve.** Media consent (§4) is given by a confirmed learner or the parent, never by a guest. Actions that declassify text or widen egress — approving a correction as book text, switching `cloud.text` on, editing `household_terms`, re-enabling magpie for media — need the **parent PIN** in the Learners tab (owner decision 4).

**Days.** A household time-zone setting (`HOUSEHOLD_TZ`) defines a "day" for `retrieval_events.day`, "different days" (ADR-0017 §6.2) and daily goals; the harness computes the local date at write time (owner decision 3).

## 2. Egress: mediated per request, backstopped at the socket

**Request mediation is the rule.** `leafi.privacy.egress` owns every client that talks to a non-loopback destination or to magpie — the `anthropic` client, the `httpx` clients (magpie, Ollama on another host, notifiers, Open Library, Healthchecks, Gatus, Telegram alerts), the `edge_tts` calls and `doctor --download`. Adapters never hold a client: they call `egress.send(destination, purpose, payload, learner=None, consent_id=None)`. Connection pools live inside `egress`. **Retries have one owner:** transport retry is `egress`'s (at most one for text, none for media, inside the call's `PER_CALL_S`); client and adapter retries are off (the Claude adapter's own loop and `BRAIN_DEADLINE_S` are removed); semantic escalation is `brain_call`'s (ADR-0017 §5); the ledger is charged per transmitted attempt.

Purposes: study purposes (`decide`, `generate`, `answer`, `judge`, `word`, `tts`, `media`, `catalog`, `notify_study`) carry learner context and run the full pipeline; **`ops`** (heartbeat, Gatus push, operational alerts, supervisor probes of non-loopback hosts, model downloads) carries no learner data — its payload schema is fixed per destination and checked — and skips the provenance and media stages but is logged.

**The socket guard is the backstop.** `leafi.core.netguard` is always installed in `leafi` processes. A connect to a non-loopback address — or to the `MAGPIE_URL` port — raises unless the current context holds a **grant** that matches it. `egress.send` resolves the destination host itself (`asyncio.to_thread`, which copies the context), then creates a grant for `(host, resolved addresses, port)` with an expiry equal to the send's deadline; the guard matches the connect's IP and port against it (a hostname-keyed grant could never match a connect, which sees an address). Name resolution is allowed only inside a grant's own resolve step. A copied grant past its expiry is refused, so an orphaned thread cannot connect. **LAN devices** configured in `devices.yml` (camera, Frigate, AnkiConnect, an Ollama host) are a `lan` destination class: allowed by address without a study payload check, listed in the table. The guard sees only this process's sockets; another process (Ollama, magpie, Anki) is governed by what Leafi sends it, not by the guard.

Pipeline for study purposes, in order: destination allow-list by purpose → provenance filter (§3) → pseudonymisation (§3) → media check (§4) → **write the attempt** (`egress_log`: destination, purpose, learner, session, payload size and sha256 — never the body — consent id, `status = sending`) → send under the grant → update the attempt (`sent` / `failed` / `unknown`). Text payloads sent to the Brain are kept in `brain_calls` (learning history, deleted with the session or learner); media bodies are never persisted by egress.

Per learner: `cloud.text` (default **on**) and `cloud.media` (`ask`; `never` for guests). The table `security.md` will own:

| Data class | `cloud.text` on | `cloud.text` off | Guest / tentative |
|---|---|---|---|
| page text (incl. parent-approved corrections), items, counts, policy text | sent | sent | sent |
| `learner` / `derived_from_learner` text (§3) | sent, pseudonymised, if **every** source learner allows it | removed; observations carry expected words + category | removed |
| real names of household members, exact ages, school, `household_terms` | never (replaced, §3) | never | never |
| audio, images | only with a consent consumed for that item, destination and purpose (§4) | same | never |
| `ops` payloads | fixed schema, no learner data | same | same |

**Eligible backends.** A backend is **local** only when its configured `backend:model` is on the `LOCAL_MODELS` allow-list (an Ollama model served on this machine by name; Ollama's cloud-hosted model names are refused), not because its endpoint is loopback (owner decision 8); magpie is never local. `decide`, `generate` and `word` may use any backend (with `cloud.text` off their payloads carry no learner text); `answer` and `judge` carry learner text, so with `cloud.text` off only local backends are eligible, with no cloud fallback. Lifting ADR-0011's deferral, Ollama is enabled when configured **and** its memory and latency next to Parakeet, Kokoro and the recognition models are measured on this machine (research D10); until then the `fast` tier uses the cheapest configured cloud model.

**magpie** (owner decision 5): any provider; telemetry off (Settings → Privacy, or `DO_NOT_TRACK=1` when the supervisor starts magpie); magpie may keep its own local logs. Requests that carry learner text or media name an explicit single-provider `provider/model` (never `auto/` or `group/`). That magpie honours the named route is a **trust assumption**; a response reporting a different provider logs an incident, marks the consent `failed` and disables magpie for media until the parent re-enables it (PIN).

**Text-to-speech.** edge-tts is a cloud destination with purpose `tts`; a spoken line carries its provenance from composition to `egress`, which applies the same filter as for Brain payloads (a Brain answer to a learner's own question is `derived_from_learner`), and a line containing a household member's real name is synthesised only locally (Kokoro). The caller-side `local_only` flag is removed.

## 3. Provenance and pseudonymisation

**Columns.** Every stored text that can reach a payload has `provenance_class` ∈ `page` | `system` | `learner` | `derived_from_learner` | `parent` and `source_learners` (json ids). The columns: `utterances.text`; `activities.outcome`, `activities.assessment`; `brain_calls.payload`, `brain_calls.response` (union of their parts); `learner_notes.text`; `book_notes.text`; `encounters.context_sentence`, `encounters.explanation_*`; `anki_outbox` card fields; `cache/tts` keys. Corrections: `corrections.source_learner_id` (NULL = the parent), written at insert, and `corrections.forgotten` (boolean) — the span a correction changes carries its source in the revision's span map, mapped forward through edit maps like `spans_verified`. Combining texts unions the sources and takes the most restrictive class.

**The filter** decides at send time from the **current** settings of every source learner, so switching `cloud.text` off also covers old notes and a sibling's text inside shared material; a source learner that no longer exists, or a `forgotten` correction, counts as off (fail closed). `parent` text follows the household setting `cloud.parent_text` (default on). A learner's spoken or typed correction is `learner` text; the span it changes keeps that learner as source until the parent approves it as book text (`corrections.parent_approved_at`, PIN; distinct from ADR-0010's `spans_verified`, which protects a span from re-OCR and says nothing about privacy). Until then the page window masks that span for cloud payloads whenever its source learner's `cloud.text` is off.

**Deletion across sources.** `forget --learner A` also deletes every `learner_note`, `book_note` and assessment whose `source_learners` include A, every `brain_calls` row whose provenance includes A, and A-sourced `cache/tts` clips. A's corrections are **unlinked, not unwound**: page revisions stay (the household's record of the book, ADR-0010; later revisions build on them); each correction by A loses its `utterance_id` and gets `forgotten = true`; spans of A's corrections the parent had not approved become **local-only for good** until the parent approves them. Corrections are short claims about the book's words, so what stays local is a word or phrase of supposed book text; this residual is accepted and named here instead of rebuilding revision chains.

**Pseudonymisation** (`privacy/pseudonym.py`, inside the pipeline): replaces the real names of **all** household learners and the parent's `household_terms` (names, school, street; Learners tab, PIN; replaces `REDACT_TERMS`, whose value migrates into it) by stable per-person aliases and neutral tokens; exact age by `alias_age_band` (e.g. "7–8") — including in the Brain's system prompt, which today says "a 10-year-old"; dates of birth by nothing. Replies are mapped back locally before they are shown or spoken. Identities in free text that are on no list ("my friend Tom") are not caught; with `cloud.text` on this is an accepted residual risk the parent reduces by adding terms.

## 4. Local first for audio and images; the remote teacher

```
on local_failure(kind, item):   # ASR empty/low confidence on a needed answer; OCR below threshold; page unknown
  if s.learner.kind != learner: return                     # guests and tentative sessions never consent to media
  ask the learner first ("Is this word 'through'?", "Can you read me the first line?", "Hold the page flatter")
  if unresolved:
    prepared, check = prepare(item)   # check ∈ clean | masked | unknown | unmaskable, against PROTECTED =
                                      # every household learner's names + household_terms (the same list as §3)
    # image: crop to the page region; a local face/person detector on the crop → any hit: unmaskable;
    #        local OCR on the crop; found PROTECTED terms are masked → masked; too little text to check → unknown
    # audio: only a reading or practice attempt, never free speech (answers, questions, chat); the clip is the
    #        attempt's own VAD segment. In order, first match wins:
    #          a PROTECTED term among the expected page words, or any recognised word near one (sim ≥ 0.80)
    #            anywhere in the clip                                   → unmaskable (audio is never masked)
    #          any gap, empty stretch, or word with conf < CLEAN_CONF   → unknown (the usual case: the trigger
    #            (0.6)                                                    was a local failure)
    #          otherwise (whole segment covered by confident words)     → clean
    if check == unmaskable: say "I'll manage without help on this one"; return      # never asked, never sent
    dest = route(...) → backend and explicit provider/model
    warn = " I couldn't check it for names." if check == unknown else ""
    if confirm("May I ask a remote teacher (<dest>) for help with this <recording|picture>?" + warn):
      c = consents.insert(learner, kind, sha256(prepared), dest, purpose, status=granted, expires=now+5 min)
      egress.send(dest, "media", prepared, learner, consent_id=c)
```

In the pipeline the media check **consumes** the consent before any byte leaves: one conditional update `granted → used` where learner, hash, destination and purpose match and it has not expired; zero rows changed → refuse. The attempt row is written in the same transaction. A delivery that fails or is uncertain leaves the consent `used`; trying again or another destination needs a new question. A consent covers one prepared item, one destination, one purpose, one attempt.

## 5. AGENTS.md boundary (replaces the first MUST NOT when this ADR is accepted)

"MUST NOT send audio or images from `leafi/` to any cloud service without a consent consumed for that item, destination and purpose (never for a guest); never media whose identity check is `unmaskable`, and `unknown` only when the consent question said so; MUST NOT send any household member's real name, exact age or school in text; learner text leaves only when every source learner's `cloud.text` is on, pseudonymised; every non-loopback request goes through `leafi.privacy.egress` (which owns every client) and is logged; the socket guard refuses any other connection. The table is in `security.md` (ADR-0018). Enforced by: `tests/test_privacy.py`, `tests/test_netguard.py`."

## 6. What changes where (inventory for the implementation)

### 6.1 Writers and lookups that must become learner-scoped

One learner-scoped store API (`study/learner_store.py`) is the only writer of the direct-owner tables; each site below calls it. `session.py` `reading_sessions` insert; `knowledge.upsert_item` (no longer queues Anki, ADR-0017 §7.2) and `_queue_update_if_pushed`; `knowledge.recompute_difficulties` (per learner, never a global `DELETE`); `knowledge.add_encounter` (`session_id` required; the parent trigger writes against the parent's session of record, a per-learner synthetic `reading_sessions` row with mode `parent`); `anki.answer` (`review_answers`), `anki.due_cards` (the learner's deck); `word_weights` / `practice_order`; `records.export_session`, `forget_session`, `forget_book`; `tests/seed.py`, `tests/test_storage.py`. A test inserts through every writer under two learners and asserts no row crosses. The first learner is created by the migration from `learner_profile` if present, else from the owner's answer to `python -m leafi setup --learner "<name>"`.

### 6.2 Constraints and the migration

New values meet existing CHECKs: `encounters.trigger` gains `teach`; `knowledge_items.kind` gains `pattern`; `knowledge_items.status` gains `ignored`; `forgotten` is a boolean column, not a `corrections.source` value. Changed UNIQUE (`knowledge_items`) and new `NOT NULL … REFERENCES learners` columns need table rebuilds, which SQLite cannot do inside `Store.migrate()`'s `BEGIN IMMEDIATE` with foreign keys on. Migration 5 is a **rebuild step type**: outside `transaction()`, `PRAGMA foreign_keys = OFF`, rebuild each table (copy, drop, rename, recreate indexes) in its own transaction, then `PRAGMA foreign_key_check` (any row → abort and restore the backup taken first) and `foreign_keys = ON`. Per table, the migration notes list each constraint and whether migrated and new rows satisfy it.

### 6.3 Network callers in `leafi` processes

| Caller | After |
|---|---|
| Brain backends (Claude, magpie, Ollama on another host) | `egress`, study purposes |
| `tts/edge.py` | `egress`, `tts` |
| `devices/notifiers.py` (study) | `egress`, `notify_study` |
| `ops/alerts.deliver` via `NotifierDevice`, `ops/checks.heartbeat` (Healthchecks), `checks.push` (Gatus) | `egress`, `ops` |
| supervisor `http_probe` / `tcp_probe`, Ollama probe | loopback, or `lan` by configured address |
| `doctor --download` (`urllib`, `huggingface_hub`, rapidocr) | `egress`, `ops`, grant per download host |
| `go2rtc_camera`, AnkiConnect, Frigate, MQTT | loopback or `lan` |
| `study/books.py` Open Library | `egress`, `catalog` |

### 6.4 Code that enforced the old rule

| Site | Becomes |
|---|---|
| `BrainRequest` constructor (rejects free text) | kept for `cloud.text` off; the provenance filter decides |
| `coach.py`, `controls.py` (target = page text) | kept; free text allowed by provenance |
| `session.say(local_only=…)`, `tts.LocalOnlyUnavailable` | replaced by line provenance in `egress` (§2) |
| `records.export_session` ("never learner free text") | parent export may include learner text locally; never sent |
| `REDACT_TERMS`, `setup --redact`, `redact-terms` alert, `.env` manifest | `household_terms` (migrated value), Learners tab, alert renamed |
| `services/brain/__init__.py` system prompt "a 10-year-old" | age band from `alias_age_band` |
| `tests/test_privacy.py` | rewritten (Confirmation) |

### 6.5 Documents that state the old rule (changed in the same change that accepts this ADR)

`AGENTS.md` (first MUST NOT → §5's text); `security.md` (red lines 1–3, the destination table → §2's table, the prompt-safety action allow-list → ADR-0017's activity kinds); `product.md` (principles 1–2, Users "the child, age 10" → learners, the Non-Goal "no cloud vision, no cloud ASR … ever" → the remote-teacher rule); `GLOSSARY.md` (Brain "text only", Eye "images never leave the LAN", Learner; new terms: learner kind, guest, provenance, remote teacher, grant); `data-model.md` (new tables and columns, the invariant "nothing identifies a person from pixels" → "only local recognition models, §1", retention: `forget --learner`); `flows/reading-session.md` ("the learner's answer stays local"); ADR-0011 front matter (`superseded-in-part-by: 0018`).

### 6.6 The owner's console

Buttons in the Obsidian console (`scil/Leafi/`, calling `scripts/win/*`) for: enrol a learner, the recognition probe (voice per Ear, face on the study camera), `forget --learner`, the Learners tab (approvals, `household_terms`, cloud settings, guest assignment), re-enable magpie for media, start magpie with `DO_NOT_TRACK=1` under the supervisor; help lines updated for `forget`, the export and the `.env` page; the console's own check run.

## Consequences

- The Brain can see what the children said and asked; the parent switches it off per learner, and the switch also covers stored notes, spoken lines and shared material.
- Siblings share one Leafi with separate records; voice recognition adds a model, a probe per Ear and enrolment; face waits for a measurement; a wrong guess cannot change egress before confirmation.
- Enforcement moves from "which module builds a client" to "which request goes through egress", with grants matched by address at the socket; operational traffic is mediated too.

## Confirmation

`tests/test_netguard.py`: refusals — a non-loopback connect outside a grant raises through `httpx`, `asyncio` streams, a thread executor and `edge_tts`; inside a grant for host A a connect to host B raises; a direct connect to the `MAGPIE_URL` port raises; an orphaned thread past its grant's expiry cannot connect. **Positive controls beside each:** inside a grant, real `httpx`, `anthropic` and `edge_tts` clients resolve and reach a fake server on a non-loopback test address; a pooled second request through `egress` succeeds; `ops` calls (heartbeat, alert) succeed; a `lan` device address connects. `tests/test_architecture.py`: no module outside `leafi.privacy.egress` imports `anthropic`, `edge_tts` or constructs an `httpx` client for a non-loopback base URL. `tests/test_privacy.py` rewritten: two canary learners (real names, exact ages, school) with `cloud.text` on and off through recording transports; no real name, exact age or school in any body (Brain incl. the system prompt, edge-tts, notifier); with `cloud.text` off no provenance-tagged learner canary appears, including a sibling's text in a shared note and a spoken answer line; media bytes only after a consumed consent; never for a guest; the no-network subprocess run still completes. `tests/test_pseudonym.py`. `tests/test_learners.py` (siblings within the margin → ask; modality conflict → ask; face without `face_measured` is absent; a dead Ear during identification is terminal; "no" twice → guest kept a week and assignable; "don't remember me" → deleted at finalize; the sweep spares `anonymous` and guests without sessions; recognition off deletes the embedding). `tests/test_learner_store.py` (every writer under two learners; Difficulties never merge). `tests/test_migration_5.py` (rebuild with foreign keys off, `foreign_key_check` clean, CHECKs accept the new values). `tests/test_forget.py` (`forget --learner` refuses during the learner's running session; removes `brain_calls`, `activities`, `cycles`, `egress_log`, evals, A-sourced TTS clips and A-sourced notes held by B; A's unapproved correction spans stay unlinked and never in a cloud payload; B's later revision intact). `tests/test_consent.py`, `tests/test_media_prepare.py` (a clip with a household name recognised plus an unclear stretch is `unmaskable`; recorded clips of each household name through the real ASR are `unmaskable` — positive control; a crop with a face is `unmaskable`). `egress_log` rows contain no payload bodies.

## Reviews

Codex design reviews 1–6 (`../plans/active/reviews/2026-10-21-codex-ai-led-design-review-*.md`) and the code-plan-review (`../plans/active/reviews/2026-10-21-code-plan-review-ai-led.md`) with the owner's answers of 2026-10-22.
