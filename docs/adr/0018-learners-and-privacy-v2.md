---
status: proposed
date: 2026-10-21
revised: 2026-10-22 (v3: the owner's decision to defer every parent feature for a simple household setup; the second code-plan-review pass; the domain prior-art map §3; the harness-libraries research §1 and §6). Earlier: code-plan-review pass 1 with the owner's eight decisions, codex design reviews 1–6 (see Reviews).
supersedes: 0011 (egress policy section only; its v1 scope list stays except the Ollama deferral, lifted here under §2's condition)
amends: 0010 (§9 deletion covers the new tables), 0003 (red line on cloud payloads), 0016 (alert and egress rows)
---

# Several learners, recognised locally; learner text may go to the cloud by the learner's setting, pseudonymised; audio and images only with per-item consent

Owner decisions of 2026-10-21 (research [`../research/2026-10-21-ai-led-study.md`](../research/2026-10-21-ai-led-study.md) §1, decisions 2, 4–7) and 2026-10-22 (guest kept one week; guests never consent to media; a household time zone; `forget` reaches every local store; a voice disagreement is not a failure; face only after measurement; locality by model allow-list; **every parent-related feature deferred: in-home use, simplicity first**, §5). The previous rule — text only, never the learner's name or own words — was judged too strict by the owner. Provenance of each mechanism: [`../research/2026-10-22-domain-prior-art.md`](../research/2026-10-22-domain-prior-art.md) §3 (this ADR applies its recommended column except the parent-consent rows, which are deferred). The habit track (`agent/`) is outside this ADR. **`security.md` owns the egress table** once this ADR is accepted; §2 states the table the rewrite starts from.

## 1. Learners and identity

`learners` (id `INTEGER PRIMARY KEY AUTOINCREMENT` — ids are never reused —, kind ∈ `learner` | `guest` | `anonymous`, display_name, birth_year?, school_year?, alias, alias_age_band, settings json, settings_version, recognition json, guest_reason?, guest_expires_at?, forgetting (bool), created_at). `anonymous` is one permanent row that owns the counts of deleted guest sessions. Ownership:

- Direct `learner_id` (NOT NULL): `reading_sessions`, `knowledge_items`, `difficulties`, `retrieval_events`, `learner_notes`, `book_notes`, `review_answers`, `anki_outbox`, `consents`, `encounters` (with `session_id` nullable, for encounters made outside a session).
- `egress_log.learner_id` is nullable, with a CHECK that it is NULL exactly for `ops` purposes (§2).
- Through `session_id` (NOT NULL; queries join): `activities`, `cycles`, `brain_calls`, `page_reads`, `utterances`; `observations`, `miscues`, `practices` reach a session through `utterances` / `page_reads`.
- Shared by the household: `books`, `pages`, `page_revisions`, `page_images`, `corrections`, `lexicon`.

Keys: `knowledge_items` unique on `(learner_id, kind, language, key, sense_hint)`; `difficulties` per learner; each learner's own Anki deck; card dedupe by `(learner_id, lemma)`; "continue from page N?" by `(learner_id, book_id)`. The direct-owner tables are written through one learner-scoped store API in `leafi/core/learner_store.py` (a core module, so both `leafi.study` and `leafi.privacy` may import it under ADR-0002's layer rule); `egress` writes `egress_log` and `consents` through it too.

**Forget.** `forget --learner <id>`: one conditional update sets `forgetting = true` and is refused while that learner owns a session with `ended_at IS NULL`; `identify` never offers a learner who is being forgotten; then small transactions delete the direct rows, every row reached through the learner's sessions (`brain_calls`, `activities`, `cycles`, `egress_log`, `utterances` …), `data/learners/<id>/`, the learner's `data/evals/decisions/` records, the learner as a source in `cache/tts` (a clip is deleted when no source is left, §3), DEBUG text logs naming the learner's sessions, and every note or assessment of another learner that names this learner as a source (§3); the last transaction deletes the `learners` row. It offers deleting the learner's Anki deck as a separate confirmation; magpie's own logs are outside Leafi and the command says so. `forget --session` / `--book` (ADR-0010 §9) also delete the `activities`, `cycles`, `brain_calls`, `retrieval_events` and `egress_log` rows of the sessions they reach.

**Who is studying.** `identify(s)` runs inside the session (ADR-0017 §2). The session starts owned by a fresh guest row; confirming a learner re-keys that session to the learner, deletes the empty guest row and bumps the epoch, in one transaction. Identification utterances are used in memory and never stored. Until confirmed: `cloud.text` is treated as off, media consent is impossible, recognition results are not stored, prompts use the local TTS only. Every `ask` and `confirm` waits `ASK_S` (8 s), capped by the session deadline. In text mode, or after a `ListenerLost` with a console, identification is the console list (no voice match); a `ListenerLost` without a console is terminal (ADR-0017 §1).

```
identify(s) -> Learner:
  u = ask("Hello! Who's reading today?")                   # the utterance recognition uses; typed → no voice match
  cands_v = [l for l in learners(kind=learner, forgetting=false) if l.recognition.voice]
  cands_f = [l for l in learners(kind=learner, forgetting=false) if l.recognition.face and l.recognition.face_measured]
  v = speaker_match(u, cands_v); f = face_match(eye_frame, cands_f) if face_in_frame(eye_frame) else absent
  per modality: accept(L) if best ≥ RECOG_ACCEPT[ear] and best − second ≥ RECOG_MARGIN[ear]; else ambiguous / none
  guess = L if one modality accepts L and the other does not accept a different learner, else None
  name = parse_name(u)
  if guess and (name is None or name ≈ guess.name) and confirm("Is that you, <guess>?"): return guess
  for attempt in (1, 2):
    if name is None: name = parse_name(ask("What's your name?"))
    if name matches an enrolled learner (fuzzy ≥ 0.85 or a console pick) and confirm("<name>?"): return that learner
    if name is new and confirm("Shall I remember you as <name>?"): return enrol(name)    # asks age or school year
    if name == "don't remember me": set_guest(s, reason = "declined"); return s.learner
    name = None
  say("Today will be kept for a week, then forgotten, unless you tell me your name next time.")
  set_guest(s, reason = "unconfirmed", expires = now + 7 days); return s.learner
```

**Guest end states** (the one owner; ADR-0017's `finalize` applies it). `set_guest` writes `guest_reason` and `guest_expires_at` on the guest row when `identify` returns, not at wrap.

| How the session ended | Outcome |
|---|---|
| identified as a learner | session re-keyed to the learner; guest row deleted |
| `declined` ("don't remember me") | at `finalize`: the guest's rows are deleted; the session row (counts only) is re-keyed to `anonymous` |
| `unconfirmed` (no name confirmed twice) | the record is kept until `guest_expires_at` (7 days); then deleted as for `declined` |
| a terminal (`stop`, deadline, lease lost) before `identify` returned, or a crash | startup recovery treats a guest with neither reason nor expiry as `unconfirmed`, expiring 7 days after its session started |

The guest sweep deletes guests with `kind = 'guest' AND (guest_reason = 'declined' OR guest_expires_at < now) AND EXISTS(session) AND NOT EXISTS(session with ended_at IS NULL)`; it runs at session start after the lease and recovery (ADR-0017 §2) and daily under the supervisor; each deletion starts with a conditional mark so two sweepers never act on one guest. A guest has `cloud.text` off, no media consent, recognition off and no export.

**Recognition** is on by default for every enrolled learner (owner decision 2); enrolment is the child's own "yes" (parent consent is deferred, §5 — the guidance sources that ask for it are recorded in prior-art §3.3). Turning a modality off deletes that learner's embedding for it. **Voice is primary**: a sherpa-onnx speaker-embedding model (its speaker-identification example, *adapted*). **Face counts only after its hit rate is measured on the real study camera position** and recorded (`recognition.face_measured`); the study camera frames the book, so a frame without a face of sufficient size makes the modality `absent`. Face models: **YuNet** (detection, MIT) and **SFace** (recognition, Apache-2.0), run locally through OpenCV; InsightFace pretrained weights (non-commercial) and `face_recognition` (weak on children, by its own README) are ruled out (prior-art §3, *adopted*). Thresholds are per Ear (`RECOG_ACCEPT[ear]`, `RECOG_MARGIN[ear]`), each from a probe that brackets the same child across sessions against sibling pairs; enrolment records its Ear. Embeddings live in `data/learners/<id>/` and never leave the machine.

**Days.** `HOUSEHOLD_TZ` (an IANA name, default the machine's zone stored at setup; `tzdata` is a named requirement because `zoneinfo` on Windows needs it) defines a day for retrieval events, mastery and per-day goals. **Household settings** (`HOUSEHOLD_TZ`, `LOCAL_MODELS`, `household_terms`, routing tables) carry a `household_settings_version` that ADR-0017's `checkpoint` reads.

## 2. Egress: mediated per request, backstopped at the socket

**Request mediation is the rule.** `leafi.privacy.egress` owns every client that talks to a non-loopback destination or to magpie: the model SDK clients (built with `max_retries=0`), the HTTP clients for magpie, notifiers, Open Library, Healthchecks, Gatus and Telegram alerts, the `edge_tts` calls and `doctor --download`. Adapters call `egress.send(destination, purpose, payload, learner=None, consent_id=None)` and get `(response, transmitted_attempts)`. Transport retry is `egress`'s (at most one for text with `tenacity` waits inside the call's deadline, none for media). Implementation choices (libraries §6): a mediating transport on the HTTP client plus the socket guard below; both written for `httpx2` after TD-1 (ADR-0017 §10).

Purposes: study purposes (`decide`, `generate`, `answer`, `judge`, `word`, `tts`, `media`, `catalog`) carry learner context and run the full pipeline; **`ops`** (heartbeat, Gatus push, operational alerts, model downloads) carries no learner data — a fixed payload schema per destination, checked — and skips the provenance and media stages but is logged with `learner_id` NULL and its own retention (§4.3).

**The socket guard is the backstop.** `leafi.core.netguard` is always installed in `leafi` processes. A connect to a non-loopback address — or to the `MAGPIE_URL` port — raises unless the current context holds a matching **grant**. `egress.send` resolves the destination itself (through `asyncio.to_thread`, which copies the context) and creates a grant for `(host, resolved addresses, port)` with an expiry equal to the send's deadline; inside that grant the guard's `getaddrinfo` **answers the granted host from the grant's recorded addresses** without a second lookup, so the clients' own resolution (which runs in `run_in_executor` without the context) needs no context, and the connect to a recorded address and port is allowed. A copied grant past its expiry is refused. **LAN devices** that never receive learner text (camera, Frigate, AnkiConnect, MQTT) are a `lan` class allowed by configured address. **A host that receives study payloads is never `lan`**: an Ollama server on another machine is reached only through `egress` under a grant; the supervisor's probe of it uses an `ops` grant. The guard sees only this process's sockets; other processes (Ollama, magpie, Anki) are governed by what Leafi sends them. `LEAFI_NO_NETWORK=1` (tests) refuses every non-loopback connect, grants included.

Pipeline for study purposes, in order: destination allow-list by purpose → provenance filter (§3) → pseudonymisation (§3) → media check (§4) → **write the attempt** (`egress_log`: destination, purpose, learner, session, payload size and an **HMAC-SHA256** of the body keyed by a per-install secret in `data/` — an unsalted hash of a short answer could be confirmed by guessing (prior-art §3) —, consent id, `status = sending`) → send under the grant → update the attempt (`sent` / `failed` / `unknown`). Text payloads sent to the Brain are kept in `brain_calls`; media bodies are never persisted by egress.

Per learner: `cloud.text` (default **on**) and media consent per item (§4; never for a guest). The table `security.md` will own:

| Data class | `cloud.text` on | `cloud.text` off | Guest / unconfirmed |
|---|---|---|---|
| page text (incl. corrections, which are book text), items, counts, policy text | sent | sent | sent |
| `learner` / `derived_from_learner` text (§3) | sent, pseudonymised, if every source learner allows it | removed; observations carry expected words + category | removed |
| real names of household members, exact ages, school, `household_terms` | never (replaced, §3) | never | never |
| audio, images | only with a consent consumed for that item, destination and purpose (§4) | same | never |
| `ops` payloads | fixed schema, no learner data | same | same |

**Eligible backends.** A backend is **local** only when its configured `backend:model` is on `LOCAL_MODELS` (an Ollama model served on this machine; Ollama's cloud-hosted model names are refused), not because its endpoint is loopback (owner decision 8); magpie is never local. `decide`, `generate` and `word` may use any backend; `answer` and `judge` carry learner text, so with `cloud.text` off only local backends are eligible. Ollama is enabled when configured **and** its memory and latency next to Parakeet, Kokoro and the recognition models are measured on this machine (research D10): the existing gate mechanism records it — `envprotect.GATE_FLOOR`'s `BRAIN_BACKEND=ollama` entry is lifted when the measurement is recorded in the plan. Until then the `fast` tier uses the cheapest cloud model.

**magpie** (owner decision 5): any provider; telemetry off (`DO_NOT_TRACK=1` when the supervisor starts magpie, or Settings → Privacy); magpie may keep its own local logs. Requests that carry learner text or media name an explicit single-provider `provider/model`. That magpie honours the named route is a trust assumption; a response reporting a different provider logs an incident, marks the consent `failed` and disables magpie for media until it is re-enabled in the settings.

**Text-to-speech.** edge-tts is a cloud destination with purpose `tts`; a spoken line carries its provenance from composition to `egress`, which applies the same filter as for Brain payloads, and a line containing a household member's real name is synthesised only locally (Kokoro). The caller-side `local_only` flag is removed.

## 3. Provenance and pseudonymisation

**Columns.** Every stored text that can reach a payload has `provenance_class` ∈ `page` | `system` | `learner` | `derived_from_learner` | `parent` and `source_learners` (json ids), both NOT NULL with no default: `utterances.text`; `activities.outcome`, `activities.assessment`; `brain_calls.payload`, `brain_calls.response`; `learner_notes.text`; `book_notes.text`; `encounters.context_sentence`, `encounters.explanation_*`; `anki_outbox.front` / `back` / `sentence`. The TTS cache keeps a sidecar per clip (`cache/tts/<key>.sources.json`) that unions the sources on every hit, because one content-addressed clip can serve several learners. Combining texts unions the sources and takes the most restrictive class. **Migration:** existing rows become `learner` text of the first learner, except page-derived fields (`encounters.context_sentence` from a page) which become `page`. An unknown or deleted source counts as `cloud.text` off (fail closed).

**Corrections are book text at once.** A learner's correction ("the book says dog") is a claim about the page, so the revision it creates is `page` text immediately (parent approval is deferred, §5). `corrections.source_learner_id` records who made it (NOT NULL for `voice` / `text` sources; the existing `source = 'parent'` marks the parent) so `forget` can unlink it: `forget --learner A` clears the correction's `utterance_id` and `source_learner_id` and sets the boolean `corrections.forgotten` (a column, not a new `source` value); the revision text stays (the household's record of the book, ADR-0010). The two existing writers, `corrections.apply_correction` and `record_unlocated`, gain the learner argument (§6.1).

**The filter** decides at send time from the current settings of every source learner, so switching `cloud.text` off also covers old notes and a sibling's text in shared material. `parent` text follows the household setting `cloud.parent_text` (default on).

**Deletion across sources.** `forget --learner A` also deletes every `learner_note`, `book_note` and assessment whose `source_learners` include A, every `brain_calls` row whose provenance includes A, and removes A from TTS-cache sidecars.

**Pseudonymisation** (`privacy/pseudonym.py`, inside the pipeline). First, list-based replacement: the real names of all household learners and the household's `household_terms` (names, school, street; on the settings page; replaces `REDACT_TERMS`, whose value migrates into it) become stable per-person **surrogate names** (realistic names, not tokens — prior-art §3, one study) and exact age becomes `alias_age_band` (e.g. "7–8"), including in the Brain's system prompt, which today says "a 10-year-old". Second, on `learner` and `derived_from_learner` text, a **name detector**: Microsoft Presidio with spaCy `en` PERSON (prior-art §3, *adopted*); a detected person name not on the lists is replaced by a surrogate too. Its recall on this household's transcripts is measured before any completeness is claimed — detectors degrade on informal and children's text, and Presidio promises none. Replies are mapped back locally before they are shown or spoken.

## 4. Local first for audio and images; consent; retention

### 4.1 The remote teacher

```
on local_failure(kind, item):   # ASR empty/low confidence on a needed answer; OCR below threshold; page unknown
  if s.learner.kind != learner: return                     # guests and unconfirmed sessions never consent to media
  ask the learner first ("Is this word 'through'?", "Can you read me the first line?", "Hold the page flatter")
  if unresolved:
    prepared, check = prepare(item)   # check ∈ clean | masked | unknown | unmaskable, against PROTECTED =
                                      # every household learner's names + household_terms (the same list as §3)
    # image: crop to the page region; YuNet face detector on the crop → any face: unmaskable;
    #        local OCR on the crop; found PROTECTED terms are masked → masked; too little text to check → unknown
    # audio: only a reading or practice attempt, never free speech; the clip is the attempt's own VAD segment.
    #        In order, first match wins:
    #          a PROTECTED term among the expected page words, or any recognised word near one (sim ≥ 0.80)
    #            anywhere in the clip                                   → unmaskable (audio is never masked)
    #          any gap, empty stretch, or word with conf < CLEAN_CONF   → unknown
    #          otherwise                                                → clean
    if check == unmaskable: say "I'll manage without help on this one"; return
    dest = route(...) → backend and explicit provider/model
    warn = " I couldn't check it for names." if check == unknown else ""
    if confirm("May I ask a remote teacher (<dest>) for help with this <recording|picture>?" + warn):
      c = consents.insert(learner, purpose = "remote_teacher", recipient = dest, item = hmac(prepared),
                          status = granted, valid_until = now + 5 min, indicated_by = "learner_voice")
      egress.send(dest, "media", prepared, learner, consent_id = c)
```

In the pipeline the media check **consumes** the consent before any byte leaves: one conditional update `granted → used` where learner, item HMAC, recipient and purpose match and it has not expired; zero rows changed → refuse. The attempt row is written in the same transaction. A delivery that fails or is uncertain leaves the consent `used`.

### 4.2 One consent table

`consents` uses the column names of ISO/IEC TS 27560 / DPV (prior-art §3, *adapted*): id, learner_id, purpose (`remote_teacher` | `cloud_text` | `biometric_voice` | `biometric_face`), recipient, item (HMAC, for per-item consent), status (`granted` | `used` | `withdrawn` | `expired` | `failed`), valid_from, valid_until, indicated_by (`learner_voice` | `learner_console` | `owner_setting`), created_at. Switching `cloud.text` on or off and enrolling or removing a biometric template each write a row, so one table answers "what was allowed, by whom, when".

### 4.3 Retention

| Data class | Kept |
|---|---|
| utterances, observations, miscues, practices, activities, brain_calls | the learning history: until `forget` |
| guest records | per the guest end-state table (§1) |
| embeddings | until recognition is turned off or `forget` |
| `egress_log` study rows | with the learner's history |
| `egress_log` `ops` rows | 30 days |
| consents | until `forget` (the audit of what was allowed) |
| page images, learner audio, TTS cache, eval transcripts, logs | as `security.md` already says (7 days; not stored; 90 days; opt-in 30 days; no raw text at INFO) |

## 5. Deferred: parent features (owner decision 2026-10-22)

For in-home use, simplicity comes first. Deferred, each with what happens instead now:

| Deferred | Now |
|---|---|
| a parent PIN on settings that widen egress | none; the settings page keeps today's typed confirmation for `PRIVACY_FLOOR` keys, extended with `LOCAL_MODELS`, `cloud.parent_text`, `BRAIN_TIERS`, `BRAIN_ROUTES`, `MAGPIE_URL`, `household_terms` |
| parent consent to biometric enrolment | the child's own "yes"; a `consents` row with `indicated_by = learner_voice` |
| parent approval of corrections as book text | corrections are book text at once (§3) |
| parent preview of Anki cards | `ANKI_PREVIEW=auto` (ADR-0017 §7.2) |
| a Learners tab to assign or discard a guest session | the guest end-state table (§1) |
| parent notifications and export extras for study sessions | the existing summary export only |

No columns are reserved for them; they arrive with their own migration when built.

## 6. What changes where

### 6.1 Writers and lookups that become learner-scoped

Through `leafi/core/learner_store.py`: `session.py`'s `reading_sessions` insert; `knowledge.upsert_item` (no Anki queueing) and `_queue_update_if_pushed`; `knowledge.recompute_difficulties` (per learner, never a global `DELETE`); `knowledge.add_encounter` (`learner_id` required, `session_id` nullable); `anki.answer`, `anki.due_cards` (the learner's deck); `word_weights` / `practice_order`; `corrections.apply_correction` and `record_unlocated` (learner argument); `records.export_session`, `forget_session`, `forget_book`; `egress` (`egress_log`, `consents`). Tests: the list is built from a grep of every insert and every call of a changed writer under `tests/` (today at least `seed.py`, `test_storage.py`, `test_anki.py`, `test_knowledge.py`, `test_corrections.py`, `test_lexicon.py`, `test_page_tracker.py`), and a test inserts through every writer under two learners.

### 6.2 Migration 5

Migrations stay Leafi's own `user_version` runner with a generic `rebuild()` helper for SQLite table rebuilds (libraries §1, Combination 1; Alembic's `batch_alter_table` is the alternative the prototype measures). **Migration 5 runs only from an explicit command**, `python -m leafi migrate --learner "<name>"`, which refuses while another process holds the database (it checks by taking an exclusive lock and by the lease) and takes a backup first; every other process that opens the database refuses to start below version 5 and names that command. The command rebuilds outside `transaction()` with `PRAGMA foreign_keys = OFF`, one transaction per table, then `PRAGMA foreign_key_check` (any row → stop, keep the backup, report), sets `user_version` in the last transaction, then `foreign_keys = ON`. Restoring the backup is done by the command only, with no other connection open. New CHECK values: `encounters.trigger` + `teach_ok`, `teach_incorrect`; `knowledge_items.kind` + `pattern`; `knowledge_items.status` + `ignored`; `corrections.forgotten` is a boolean column. The first learner is the one named on the command line.

### 6.3 Network callers in `leafi` processes

| Caller | After |
|---|---|
| Brain backends (Claude, magpie, Ollama on another host) | `egress`, study purposes |
| `tts/edge.py` | `egress`, `tts` |
| `devices/notifiers.py` (study) | `egress`, study purpose |
| `ops/alerts.deliver`, `ops/checks.heartbeat`, `checks.push` | `egress`, `ops` |
| supervisor `http_probe` / `tcp_probe` | loopback, `lan`, or an `ops` grant |
| `doctor --download` | `egress`, `ops`, a grant per download host (note: `hf-xet`'s Rust sockets are invisible to the Python guard — libraries §8; downloads run with `HF_HUB_DISABLE_XET=1`) |
| `go2rtc_camera`, AnkiConnect, Frigate, MQTT | loopback or `lan` |
| `study/books.py` Open Library | `egress`, `catalog` |

### 6.4 Code that enforced the old rule

| Site | Becomes |
|---|---|
| `BrainRequest` constructor (rejects free text) | kept for `cloud.text` off; the provenance filter decides |
| `coach.py`, `controls.py` (target = page text) | kept; free text allowed by provenance |
| `session.say(local_only=…)`, `tts.LocalOnlyUnavailable` | line provenance in `egress` |
| `records.export_session` ("never learner free text") | local export may include learner text; never sent |
| `REDACT_TERMS`, `setup --redact`, the `redact-terms` alert, the `.env` manifest | `household_terms` (migrated), the settings page, alert renamed |
| `envprotect.GATE_FLOOR` (`BRAIN_BACKEND=ollama`, `BRAIN_LOCAL_MODEL`) | lifted when D10 is recorded (§2) |
| `envprotect.PRIVACY_FLOOR` | extended with the new egress keys (§5) |
| `LEAFI_NO_NETWORK` | test switch: refuses every non-loopback connect, grants included (§2) |
| the Brain system prompt "a 10-year-old" | age band |
| `tests/test_privacy.py` | rewritten (Confirmation) |

### 6.5 Documents that state the old rule (changed in the change that accepts this ADR)

`AGENTS.md` (first MUST NOT → §7's text); `security.md` (red lines 1–3, the destination table → §2's table, retention → §4.3); `product.md` (principles 1–2, Users, the Non-Goal "no cloud vision, no cloud ASR … ever" → the remote-teacher rule); `GLOSSARY.md` (Brain, Eye, Learner; new terms: learner kind, guest, provenance, remote teacher, grant, surrogate name); `data-model.md`; `flows/reading-session.md`; `architecture/overview.md` (items 3–4), `c4-context.md`, `c4-container.md` (magpie added), `deployment.md` (trust boundary); `architecture/config.md` (`setup --redact`); `engineering/code-locator.md` (privacy entry), `engineering/testing.md` and `engineering/repo-map.md` (the guard); ADR-0003 (red line → `superseded-in-part-by: 0018`), ADR-0011 (`superseded-in-part-by: 0018`), ADR-0016 (the `redact-terms` alert, its egress rows → `ops`, magpie as a supervised child).

### 6.6 The owner's console

Buttons: `leafi migrate --learner` (once, then removed), enrol a learner and run the recognition probe (voice per Ear; face on the study camera), `forget --learner`, start magpie with `DO_NOT_TRACK=1` under the supervisor; help lines for `forget`, the export and the settings page; the console's own check.

## 7. AGENTS.md boundary (replaces the first MUST NOT when this ADR is accepted)

"MUST NOT send audio or images from `leafi/` to any cloud service without a consent consumed for that item, recipient and purpose (never for a guest); never media whose identity check is `unmaskable`, and `unknown` only when the consent question said so; MUST NOT send any household member's real name, exact age or school in text; learner text leaves only when every source learner's `cloud.text` is on, pseudonymised; every non-loopback request goes through `leafi.privacy.egress` and is logged; the socket guard refuses any other connection. The table is in `security.md` (ADR-0018). Enforced by: `tests/test_privacy.py`, `tests/test_netguard.py`."

## Consequences

- The Brain can see what the children said and asked; each learner's `cloud.text` switches it off, also for stored notes, spoken lines and shared material.
- Siblings share one Leafi with separate records; voice recognition adds a model, a probe per Ear and enrolment; face waits for a measurement.
- Parent controls are absent by choice; the deferral list (§5) says what each would add.
- Enforcement is per request through `egress`, with grants matched by address at the socket; operational traffic is mediated too.

## Confirmation

`tests/test_netguard.py`: refusals (outside a grant through `httpx`/`httpx2`, `asyncio` streams, a thread executor and `edge_tts`; a grant for A refuses B; the `MAGPIE_URL` port without a grant; an expired copied grant; `LEAFI_NO_NETWORK` refuses inside a grant) **beside positive controls** (inside a grant, the real SDK clients and `edge_tts` resolve through the guard's recorded addresses and reach a fake server on a non-loopback test address; a pooled second request through `egress` succeeds; `ops` calls succeed; a `lan` device connects; an Ollama host on the LAN is refused without a grant). `tests/test_architecture.py`: no module outside `leafi.privacy.egress` imports a model SDK or `edge_tts` or builds an HTTP client for a non-loopback base URL; `leafi/core/learner_store.py` imports nothing from `study`. `tests/test_privacy.py` rewritten: two canary learners with `cloud.text` on and off; no real name, exact age or school in any body (Brain incl. the system prompt, edge-tts, notifier); a person name only Presidio knows is replaced; with `cloud.text` off no `learner` / `derived_from_learner` canary appears, including a sibling's text in a shared note and a spoken answer line; media only after a consumed consent; never for a guest; the no-network subprocess run still completes. `tests/test_learners.py` (the identify paths; text-mode identification after a lost Ear with a console; each guest end state of §1 including a crash before `identify` returned; the sweep spares `anonymous`, guests without sessions and guests in an open session; ids never reused). `tests/test_learner_store.py` (every writer under two learners). `tests/test_migration_5.py` (refused while another connection is open; other openers refuse below 5; rebuild clean; new CHECK values accepted; existing corrections and provenance migrate to the first learner). `tests/test_forget.py` (refused during a running session; `forgetting` hides the learner from `identify`; removes every listed store; a correction by A stays as page text, unlinked). `tests/test_consent.py`, `tests/test_media_prepare.py` (a recognised household name plus an unclear stretch → `unmaskable`; a crop with a face → `unmaskable`; real-ASR positive control per household name), `tests/test_pseudonym.py` (surrogates stable; age band; round trip). `egress_log` rows hold an HMAC, never a body or a bare hash.

## Reviews

Codex design reviews 1–6 and code-plan-review passes 1–2 under `../plans/active/reviews/` (2026-10-21, 2026-10-22).
