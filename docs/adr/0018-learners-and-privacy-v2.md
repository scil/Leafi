---
status: proposed
date: 2026-10-21
revised: 2026-10-22 (v4: the independent codex and code-plan-review rounds on v3 and the owner's answers — Anki sync is a notice, privacy behaviour is configurable, guests and unknown ages get their own session settings; earlier v3, v2 and their reviews, see Reviews)
supersedes: 0011 (egress policy section only; its v1 scope list stays except the Ollama deferral, lifted under §2's condition)
amends: 0010 (§9 deletion covers the new tables), 0003 (red line on cloud payloads), 0016 (alert and egress rows)
---

# Several learners, recognised locally; learner text may go to the cloud by the learner's setting, pseudonymised; audio and images only with per-item consent

Owner decisions: 2026-10-21 (research [`../research/2026-10-21-ai-led-study.md`](../research/2026-10-21-ai-led-study.md) §1, decisions 2, 4–7) and 2026-10-22 (guest kept one week; guests never consent to media; a household time zone; `forget` reaches every local store; a voice disagreement is not a failure; face only after measurement; locality by model allow-list; every parent feature deferred, §6; **when Anki is enabled Leafi shows that AnkiWeb sync can send card text out, and the household checks its own setup**; **every privacy behaviour is a setting**, §5; a new empty database is created at the latest schema; routing tables are household settings). The habit track (`agent/`) is outside this ADR. **`security.md` owns the egress table and the privacy settings** once this ADR is accepted; §2 and §5 state what its rewrite starts from.

## 1. Learners and identity

`learners` (id `INTEGER PRIMARY KEY AUTOINCREMENT` — never reused —, kind ∈ `learner` | `guest` | `anonymous`, display_name, birth_year?, school_year?, alias, alias_age_band, settings json, settings_version, recognition json, guest_reason?, guest_expires_at?, forgetting (bool), created_at). `anonymous` is one permanent row that owns the counts of deleted guest sessions. Ownership:

- Direct `learner_id` (NOT NULL): `reading_sessions`, `knowledge_items`, `difficulties`, `retrieval_events`, `learner_notes`, `book_notes`, `review_answers`, `anki_outbox`, `consents`, `encounters` (`session_id` nullable).
- `egress_log.learner_id` nullable, with a CHECK that it is NULL exactly for `ops` purposes (§2).
- Through `session_id` (NOT NULL; queries join): `activities`, `cycles`, `brain_calls`, `page_reads`, `utterances`; `observations`, `miscues`, `practices` through `utterances` / `page_reads`.
- Shared by the household: `books`, `pages`, `page_revisions`, `page_images`, `corrections`, `lexicon`.

Keys: `knowledge_items` unique on `(learner_id, kind, language, key, sense_hint)`; `difficulties` per learner; each learner's own Anki deck; card dedupe by `(learner_id, lemma)`; "continue from page N?" by `(learner_id, book_id)`. The direct-owner tables are written through one learner-scoped store API, `leafi/core/learner_store.py` (a core module, so `leafi.study` and `leafi.privacy` may both import it under ADR-0002).

**Forget.** `forget --learner <id>`: one conditional update sets `forgetting = true`, refused while that learner owns a session with `ended_at IS NULL`; `identify` never offers, and the confirmation transaction never adopts, a learner being forgotten. Then small transactions delete: the direct rows; every row reached through the learner's sessions (`brain_calls`, `activities`, `cycles`, `egress_log`, `utterances` …); `data/learners/<id>/`; the learner's `data/evals/decisions/` records; the learner as a source in TTS-cache sidecars (a clip is deleted when no source is left); DEBUG text logs naming the learner's sessions; **every derived copy whose `source_learners` include the learner, in any learner's rows** — notes, assessments, encounter explanations, `anki_outbox` card fields (the card row is deleted, and a card already in Anki is listed for the household to remove), `brain_calls`. The learner's display name and other identifying names move into `household_terms` before the row is deleted, so pseudonymisation keeps replacing them in shared text such as corrections (§3). **Fence against new derived writes:** every write of a derived text (a note, an assessment, an encounter explanation, card fields, a `brain_calls` row) checks, in its own transaction, that none of its `source_learners` has `forgetting = true`, and is refused otherwise; a final rescan just before the last transaction deletes any row naming the learner as a source that slipped in between batches. The last transaction deletes the `learners` row. The command offers deleting the learner's Anki deck as a separate confirmation; magpie's own logs are outside Leafi and it says so. `forget --session` / `--book` (ADR-0010 §9) also delete the `activities`, `cycles`, `brain_calls`, `retrieval_events` and `egress_log` rows of the sessions they reach.

**Who is studying.** `identify(s)` runs inside the session (ADR-0017 §2). The session starts owned by a fresh guest row. **Confirmation is durable before it is adopted:** confirming learner L runs one transaction that re-keys the session to L only if `L.forgetting = false` (a conditional update), deletes the empty guest row and bumps the epoch; only after it commits does `identify` return L. A failed or refused transaction (busy twice, or L being forgotten) says "Let's try that again" and continues the identification loop; the session stays the guest's meanwhile. Identification utterances are used in memory and never stored. Until confirmed: `cloud.text` is treated as off, media consent is impossible, recognition results are not stored, prompts use the local TTS only. Every `ask` and `confirm` waits `ASK_S` (8 s), capped by the session's deadlines. In text mode there is no voice match (console list). **A `ListenerLost` during `identify`** restarts identification on the console list when a console exists, and is terminal without one; a `ListenerLost` after `identify` returned never re-identifies (ADR-0017 §1).

```
identify(s) -> Learner:
  u = ask("Hello! Who's reading today?")                   # the utterance recognition uses; typed → no voice match
  cands_v = [l for l in learners(kind=learner, forgetting=false) if l.recognition.voice]
  cands_f = [l for l in learners(kind=learner, forgetting=false) if l.recognition.face and l.recognition.face_measured]
  v = speaker_match(u, cands_v); f = face_match(eye_frame, cands_f) if face_in_frame(eye_frame) else absent
  per modality: accept(L) if best ≥ RECOG_ACCEPT[ear] and best − second ≥ RECOG_MARGIN[ear]; else ambiguous / none
  guess = L if one modality accepts L and the other does not accept a different learner, else None
  name = parse_name(u)
  if guess and (name is None or name ≈ guess.name) and confirm("Is that you, <guess>?") and adopt(s, guess): return guess
  for attempt in (1, 2):
    if name is None: name = parse_name(ask("What's your name?"))
    if name matches an enrolled learner (fuzzy ≥ 0.85 or a console pick) and confirm("<name>?") and adopt(s, that): return that
    if name is new and confirm("Shall I remember you as <name>?"): L = enrol(name); if adopt(s, L): return L
    if name == "don't remember me": set_guest(s, reason = "declined"); return s.learner
    name = None
  say("Today will be kept for a week, then forgotten, unless you tell me your name next time.")
  set_guest(s, reason = "unconfirmed", expires = now + guest.keep_days); return s.learner
adopt(s, L) = the durable confirmation transaction above; true only when it committed
```

**Guest end states** (the one owner; ADR-0017's `finalize` and startup recovery both apply it). `set_guest` writes `guest_reason` and `guest_expires_at` when `identify` returns.

| How the session ended | Who writes the outcome | Outcome |
|---|---|---|
| a learner adopted | `adopt` | session re-keyed; guest row deleted |
| `declined` | `finalize` | the guest's rows deleted; the session row (counts only) re-keyed to `anonymous` |
| `unconfirmed` with `guest.keep_days = 0` | `finalize` | deleted at wrap, as for `declined` |
| `unconfirmed` | `identify` | kept until `guest_expires_at`; then deleted as for `declined` |
| a terminal (`stop`, deadline, lease lost) before `identify` returned | `finalize` | `unconfirmed`, expiring `guest.keep_days` after the session started |
| a crash, or a `finalize` that could not write | startup recovery, for every guest (open or ended session) with neither reason nor expiry | as the row above |

The guest sweep deletes guests with `kind = 'guest' AND (guest_reason = 'declined' OR guest_expires_at < now) AND EXISTS(session) AND NOT EXISTS(session with ended_at IS NULL)`; it runs at session start after the lease and recovery (ADR-0017 §2) and daily under the supervisor; each deletion starts with a conditional mark so two sweepers never act on one guest. A guest has `cloud.text` off, no media consent, recognition off, no export and no post-session notes (ADR-0017 `extract_notes` skips guests, so nothing derived from a guest is written after `finalize`).

**Recognition** is on by default for every enrolled learner (owner decision 2); enrolment is the child's own "yes" (parent consent deferred, §6; the guidance sources that ask for it are in prior-art §3.3). Turning a modality off deletes that learner's embedding for it. **Voice is primary**: a sherpa-onnx speaker-embedding model, enrolled by averaging several clips; the model, its licence and version are recorded in the plan, and published error rates are adult-only, so thresholds come from this household's own probe, repeated after an Ear change and every 6 months. **Face counts only after its hit rate is measured on the real study camera position** (`recognition.face_measured`); a frame without a face of sufficient size makes the modality `absent`. Face models: YuNet (detection, MIT) and SFace (recognition, Apache-2.0) through OpenCV; InsightFace pretrained weights (non-commercial) and `face_recognition` (weak on children, by its own README) are ruled out. Mixed Chinese/English names in `parse_name` are untested and get their own probe cases. Thresholds are per Ear (`RECOG_ACCEPT[ear]`, `RECOG_MARGIN[ear]`); enrolment records its Ear. Embeddings live in `data/learners/<id>/` and never leave the machine.

**Days and household settings.** `HOUSEHOLD_TZ` is an IANA name obtained at setup from the machine's zone through `tzlocal` (it maps Windows zone names through CLDR's `windowsZones`; *adopted*), with `tzdata` a named requirement because `zoneinfo` on Windows needs it. Household settings (`HOUSEHOLD_TZ`, `LOCAL_MODELS`, `household_terms`, `BRAIN_TIERS`, `BRAIN_ROUTES`, `cloud.parent_text`, the privacy settings of §5 marked household) carry a `household_settings_version` that ADR-0017's `checkpoint` reads.

## 2. Egress: mediated per request, backstopped at the socket

**Two seams, two jobs.** At the **call level**, `leafi.privacy.egress.prepare(destination, purpose, payload, learner, consent_id=None)` runs the study pipeline and returns the filtered payload plus an **attempt token** bound to `(learner, purpose, recipient, HMAC of the prepared body, expiry)`; adapters keep their own SDK and send the prepared payload through a client they obtain from **`egress.client(destination)`**. At the **transport level**, that client carries a mediating transport which, per request: recomputes the HMAC of the body actually being sent and refuses it unless it matches a live token for that recipient; **consumes the token atomically on first use** (a token is single-use; a text retry by the mediator itself reuses the same request and body and is the only second transmission a token allows; media has none); checks the host; reserves the per-transmission budget (ADR-0017 §5); and records each transmitted attempt. A second adapter submission with a spent token, or any other body, is refused.

**WebSocket clients.** edge-tts speaks over an aiohttp WebSocket, not `httpx2`. Its adapter passes `egress.aiohttp_connector(destination, token)` as edge-tts's `connector` argument: the connector's resolver answers from the grant, and it checks and consumes the token when it opens the connection (the TTS text is the whole payload, so the token's HMAC is of that text). A probe confirms edge-tts honours the connector before this is relied on; if it does not, edge-tts is replaced by a Leafi WebSocket adapter built on the same connector. Client and SDK retries are off (`max_retries=0`); transport retry is the mediator's (at most one, text only, `tenacity` waits inside the call's deadline). **One client family:** every Leafi-built client moves to `httpx2` with `httpx2.alias_httpx()` called first in `leafi.cli`, after TD-1 (ADR-0017 §10); magpie is called through the `anthropic` SDK's Messages API at `MAGPIE_URL`; Ollama through its OpenAI-compatible HTTP endpoint on `httpx2` (the `ollama` package, still on `httpx`, is not used). A request refused by the pipeline or the guard returns a synthetic `403` with a reason, so callers handle one refusal shape.

Purposes: study purposes (`decide`, `generate`, `answer`, `judge`, `word`, `tts`, `media`, `catalog`) run the full pipeline; **`ops`** (heartbeat, Gatus push, operational alerts, model downloads) carries no learner data — a fixed payload schema per destination, checked — skips the provenance and media stages and is logged with `learner_id` NULL. Redirects are followed by the mediator, not the client: each destination lists its allowed redirect hosts (a GitHub release asset → `release-assets.githubusercontent.com`; Hugging Face → its CDN), and each allowed hop gets its own grant. Environment set before any import (`leafi.cli`): `HF_HUB_DISABLE_TELEMETRY=1`, `DO_NOT_TRACK=1`, `HF_HUB_DISABLE_XET=1` (its Rust sockets are invisible to the Python guard), `HF_HUB_OFFLINE=1` except under `doctor --download`, Ultralytics `sync` off. A monitor-only `sys.addaudithook` logs `subprocess.Popen` calls so a child process that could open sockets is visible.

**The socket guard is the backstop.** `leafi.core.netguard` is always installed in `leafi` processes. Protected targets: every non-loopback address, and a list of **loopback gateway ports** — `MAGPIE_URL`'s and the local Ollama port — because both can forward to cloud models. A connect to a protected target raises unless the current context holds a matching **grant**. Grants are created by the mediator per transmission for `(host, resolved addresses, port)` with an expiry equal to that transmission's deadline; the connect check reads the grant from the task's context. **Resolution:** the guard patches the event loop's async `getaddrinfo` (which runs in the calling task's context, unlike the executor it hands off to) to answer a granted host from the grant's recorded addresses; the mediator itself resolves once per grant through `asyncio.to_thread`. Blocking `socket.getaddrinfo` stays refused for protected names outside a grant. **LAN devices** that never receive learner text (camera, Frigate, MQTT) are a `lan` class allowed by configured address; a host that receives study payloads (Ollama on another machine) is never `lan`. AnkiConnect is loopback (see the Anki row below). The guard sees only this process's sockets. `LEAFI_NO_NETWORK=1` (tests) refuses every protected connect, grants included.

Pipeline for study purposes, in order: destination allow-list by purpose → **locality** (a destination on `LOCAL_MODELS` skips the provenance filter and pseudonymisation: learner text may reach a local model whatever `cloud.text` says, which is what makes local `answer` and `judge` usable) → provenance filter (§3) → pseudonymisation (§3) → media check (§4) → **write the attempt** (`egress_log`: destination, purpose, learner, session, payload size and an HMAC-SHA256 of the body keyed by a per-install secret in `data/`, consent id, `status = sending`) → transmit through the mediated client → update the attempt (`sent` / `failed` / `unknown`, transmitted attempts). Text payloads sent to the Brain are kept in `brain_calls`; media bodies are never persisted by egress.

The table `security.md` will own:

| Data class | `cloud.text` on | `cloud.text` off | Guest / unconfirmed |
|---|---|---|---|
| page text (incl. corrections), items, counts, policy text | sent, pseudonymised by the lists | same | same |
| `learner` / `derived_from_learner` text (§3) | sent, pseudonymised, if every source learner allows it | removed; observations carry expected words + category | removed |
| real names of household members, exact ages, school, `household_terms` | never (replaced, §3) | never | never |
| audio, images | only with a consent consumed for that item (§4) | same | never |
| `ops` payloads | fixed schema, no learner data | same | same |
| **Anki** (AnkiConnect on loopback; card text) | card text may contain `derived_from_learner` text. If the Anki profile syncs to AnkiWeb, it leaves the machine through Anki, outside Leafi's control | same | guests have no deck |

**Anki notice** (owner decision 2026-10-22): when Anki is enabled (setup, `doctor`, and the settings page), Leafi shows: "Anki can sync your cards to AnkiWeb. Card text can include what Leafi learned from your child's answers. Check your Anki sync setting." The household decides; Leafi does not filter card text by `cloud.text` and does not check Anki's sync state.

**Eligible backends.** A backend is **local** only when its configured `backend:model` is on `LOCAL_MODELS` (an Ollama model served on this machine; Ollama's cloud-hosted model names are refused), never because its endpoint is loopback; magpie is never local. `decide`, `generate` and `word` may use any backend; `answer` and `judge` carry learner text, so with `cloud.text` off only local backends are eligible. Ollama is enabled when configured **and** its memory and latency next to Parakeet, Kokoro and the recognition models are measured on this machine (research D10): `envprotect.GATE_FLOOR`'s `BRAIN_BACKEND=ollama` entry is lifted when the measurement is recorded in the plan. Until then the `fast` tier uses the cheapest cloud model. `qwen3-vl` as a local second opinion before the remote teacher is deferred with the Ollama gate.

**magpie** (owner decision 5): any provider; telemetry off (`DO_NOT_TRACK=1` when the supervisor starts magpie, or its Settings → Privacy); magpie may keep its own local logs. Requests that carry learner text or media name an explicit single-provider `provider/model`; that magpie honours the route is a trust assumption; a response reporting another provider logs an incident, marks the consent `failed` and disables magpie for media until re-enabled in the settings. Whether magpie passes structured outputs through is probed before it may be a `decide` backend.

**Text-to-speech.** Lines are routed **before** egress by `privacy.tts_learner_lines` (§5): with `local` (default), any line containing `learner` / `derived_from_learner` text or a detected name is synthesised by Kokoro; edge-tts receives only `page` / `system` lines, so it never speaks a surrogate name. With `cloud`, such lines go through the full pipeline to edge-tts and a surrogate name may be spoken. The caller-side `local_only` flag is removed.

## 3. Provenance and pseudonymisation

**Columns.** Every stored text that can reach a payload has `provenance_class` ∈ `page` | `system` | `learner` | `derived_from_learner` | `parent` and `source_learners` (json ids), both NOT NULL with no default: `utterances.text`; `activities.outcome`, `activities.assessment`; `brain_calls.payload`, `brain_calls.response`; `learner_notes.text`; `book_notes.text`; `encounters.context_sentence`, `encounters.explanation_*`; `anki_outbox.front` / `back` / `sentence`. The TTS cache keeps a sidecar per clip (`cache/tts/<key>.sources.json`) that unions sources on every hit. Combining texts unions the sources and takes the most restrictive class. Migration: existing rows become `learner` text of the first learner, except page-derived fields, which become `page`. An unknown or deleted source counts as `cloud.text` off.

**Corrections are book text at once.** A learner's correction creates a revision that is `page` text immediately (parent approval deferred, §6). `corrections.source_learner_id` records who made it, with `CHECK (source = 'parent' OR forgotten OR source_learner_id IS NOT NULL)`; `forget --learner A` clears `utterance_id` and `source_learner_id` and sets `corrections.forgotten = true`; the revision text stays (the household's record of the book, ADR-0010), and A's names stay replaced in it because they moved into `household_terms` (§1). The two writers, `corrections.apply_correction` and `record_unlocated`, take the learner.

**The filter** decides at send time from the current settings of every source learner. `parent` text follows `cloud.parent_text` (household, default on).

**Pseudonymisation** (`privacy/pseudonym.py`, inside the pipeline, applied to **every text class**, page text included):
1. **Lists** (all classes): the names of all household learners (including forgotten ones, kept in `household_terms`), each learner's school (asked at enrolment and stored in `household_terms`; enrolment is not complete without it or an explicit "no school"), and the rest of `household_terms` become stable per-person **surrogate names** or neutral tokens (realistic surrogates, prior-art §3, one study). The exact age becomes `alias_age_band`, including in the Brain's system prompt, which today says "a 10-year-old".
2. **Detector** (`learner` and `derived_from_learner` text, when `privacy.name_detector` is on — §5): Microsoft Presidio with spaCy `en` for PERSON, ORGANIZATION and LOCATION; a detected entity not on the lists is replaced too, so an unlisted school ("Cedar Grove Primary") or a friend's name is caught. Recall on this household's transcripts is measured before completeness is claimed; Presidio promises none.

Replies are mapped back locally before they are shown or spoken.

## 4. Local first for audio and images; consent; retention

### 4.1 The remote teacher

```
on local_failure(kind, item):   # ASR empty/low confidence on a needed answer; OCR below threshold; page unknown
  if s.learner.kind != learner or privacy.media == "never": return
  ask the learner first ("Is this word 'through'?", "Can you read me the first line?", "Hold the page flatter")
  if unresolved:
    prepared, check = prepare(item)   # check ∈ clean | masked | unknown | unmaskable, against PROTECTED = §3's lists
    # image: crop to the page region; YuNet on the crop → any face: unmaskable; local OCR on the crop; PROTECTED
    #        terms found are masked → masked; too little text to check → unknown. A person/body without a face
    #        is not detected (stated gap).
    # audio: only a reading or practice attempt's own VAD segment, never free speech. First match wins:
    #        a PROTECTED term among the expected page words, or any recognised word near one (sim ≥ 0.80) → unmaskable
    #        any gap, empty stretch, or word with conf < CLEAN_CONF (0.6, untuned)                     → unknown
    #        otherwise                                                                                    → clean
    if check == unmaskable: say "I'll manage without help on this one"; return
    dest = route(...) → backend and explicit provider/model
    warn = " I couldn't check it for names." if check == unknown else ""
    if confirm("May I ask a remote teacher (<dest>) for help with this <recording|picture>?" + warn):
      c = consents.insert(learner, purpose = "remote_teacher", recipient = dest, item = hmac(prepared),
                          status = granted, valid_until = now + 5 min, indicated_by = "learner_voice")
      egress.prepare(dest, "media", prepared, learner, consent_id = c) → transmit
```

**Consent matching.** An egress purpose `media` requires a consent with purpose `remote_teacher` (the one consent purpose that authorises sending media); `prepare` consumes it with one conditional update `granted → used` where learner, item HMAC and recipient match, the consent purpose is `remote_teacher`, the egress purpose is `media`, and it has not expired; zero rows → refuse. The attempt row is written in the same transaction, before any transmission. A delivery that fails or is uncertain leaves the consent `used`.

### 4.2 One consent table

`consents` uses the column names of ISO/IEC TS 27560 / DPV (*adapted*): id, learner_id, purpose (`remote_teacher` | `cloud_text` | `biometric_voice` | `biometric_face`), recipient, item (HMAC, per-item consent only), status (`granted` | `used` | `withdrawn` | `expired` | `failed`), valid_from, valid_until, indicated_by (`learner_voice` | `learner_console` | `household_setting`), created_at. Switching `cloud.text` and enrolling or removing a biometric template each write a row.

### 4.3 Retention

| Data class | Kept |
|---|---|
| utterances, observations, miscues, practices, activities, brain_calls | until `forget` |
| guest records | per the guest end-state table (§1) |
| embeddings | until recognition is turned off or `forget` |
| `egress_log` study rows | with the learner's history |
| `egress_log` `ops` rows | `privacy.ops_log_days` (30) |
| consents | until `forget` |
| page images, learner audio, TTS cache, eval transcripts, logs | as `security.md` says (7 days; not stored; 90 days; opt-in 30 days; no raw text at INFO) |

## 5. Privacy settings (owner decision 2026-10-22: every privacy behaviour is configurable)

One table, owned by `security.md` after acceptance; changes to keys marked † need the settings page's typed confirmation (today's `PRIVACY_FLOOR` mechanism, extended to these keys).

| Setting | Scope | Default | Values |
|---|---|---|---|
| `cloud.text` † | learner | on | on / off |
| `cloud.parent_text` † | household | on | on / off |
| `privacy.media` † | learner | ask | ask / never |
| `privacy.tts_learner_lines` † | household | local | local / cloud (§2) |
| `privacy.name_detector` † | household | on | on / off (§3 step 2) |
| `household_terms` † | household | names and schools from enrolment | a list |
| `recognition.voice`, `recognition.face` | learner | on (face counts only when measured) | on / off |
| `guest.keep_days` | household | 7 | 0–30 (0 = delete at wrap) |
| `privacy.ops_log_days` | household | 30 | 1–365 |
| `LOCAL_MODELS` †, `BRAIN_TIERS` †, `BRAIN_ROUTES` †, `MAGPIE_URL` † | household | — | §2, ADR-0017 §5.1 |
| `HOUSEHOLD_TZ` | household | from `tzlocal` | an IANA name |

Session length and end timing for learners, guests and unknown ages are ADR-0017 §6.3 settings.

## 6. Deferred: parent features (owner decision 2026-10-22)

| Deferred | Now |
|---|---|
| a parent PIN on settings that widen egress | the typed confirmation of §5's † keys |
| parent consent to biometric enrolment | the child's own "yes"; a `consents` row with `indicated_by = learner_voice` |
| parent approval of corrections as book text | corrections are book text at once (§3) |
| parent preview of Anki cards | `ANKI_PREVIEW=auto` (ADR-0017 §7.2) |
| a Learners tab to assign or discard a guest session | the guest end-state table (§1) |
| parent notifications and export extras for study sessions | the existing summary export only |

No columns are reserved for them.

## 7. What changes where

### 7.1 Writers and lookups that become learner-scoped

Through `leafi/core/learner_store.py`: `session.py`'s `reading_sessions` insert; `knowledge.upsert_item` (no Anki queueing); `knowledge.recompute_difficulties` (per learner, never a global `DELETE`); `knowledge.add_encounter` (`learner_id` required, `session_id` nullable); `anki.answer` (eases 1–4), `anki.due_cards` (the learner's deck); `word_weights` / `practice_order`; `corrections.apply_correction` and `record_unlocated` (learner argument); `records.export_session`, `forget_session`, `forget_book`; `egress` (`egress_log`, `consents`). `_queue_update_if_pushed` is removed (ADR-0017 §7.2). Tests: the list is built from a grep of every insert and every call of a changed writer under `tests/` (today at least `seed.py`, `test_storage.py`, `test_anki.py`, `test_knowledge.py`, `test_corrections.py`, `test_lexicon.py`, `test_page_tracker.py`); a test inserts through every writer under two learners.

### 7.2 Opening the database and migration 5

**Three states on open:** an empty new file is created at the latest schema in one step, with no learner rows (decision 5; every test fixture and a first install work unchanged); a database at the latest version opens; a database that holds data below version 5 refuses and names the command below. **Exclusion between processes:** every Leafi process that opens the database holds a shared OS file lock on `data/leafi.db.users` for as long as it is open (`portalocker`, *adopted*); the migration takes it exclusively and non-blocking, so it refuses while any other process — a supervisor, a web UI, a CLI, an idle connection — has the database open, and no process can open it while the migration runs.

`python -m leafi migrate --learner "<name>"`: takes the exclusive lock; copies the file to a backup with SQLite's backup API; sets `PRAGMA foreign_keys = OFF` (outside any transaction); runs **one** transaction that rebuilds every changed table (Leafi's own `rebuild()` helper: create new, copy, drop, rename, recreate indexes), creates the new tables, writes the first learner, migrates provenance and correction sources, runs `PRAGMA foreign_key_check` (any row → ROLLBACK) and sets `user_version`; COMMIT; `foreign_keys = ON`. A failure rolls the whole migration back, so the file is still the untouched version 4 and the command can simply run again; the backup is a second safety, restored only by the command while it holds the exclusive lock. New CHECK values: `encounters.trigger` + `teach_ok`, `teach_incorrect`; `knowledge_items.kind` + `pattern`; `knowledge_items.status` + `ignored`; `review_answers.ease IN (1,2,3,4)`; `reading_sessions.mode` unchanged; `corrections.forgotten` is a boolean column with the CHECK of §3. Alembic's `batch_alter_table` is the alternative the libraries prototype measures. A test asserts that a migrated database's schema equals a freshly created one.

### 7.3 Network callers in `leafi` processes

| Caller | After |
|---|---|
| Brain backends (Claude, magpie, Ollama) | `egress`, study purposes |
| `tts/edge.py` | `egress`, `tts` (only `page` / `system` lines by default, §2) |
| `devices/notifiers.py` (study) | `egress`, study purpose |
| `ops/alerts.deliver`, `ops/checks.heartbeat`, `checks.push` | `egress`, `ops` |
| supervisor `http_probe` / `tcp_probe` | loopback, `lan`, or an `ops` grant |
| `doctor --download` | `egress`, `ops`, with its redirect hosts |
| `go2rtc_camera`, AnkiConnect, Frigate, MQTT | loopback or `lan` |
| `study/books.py` Open Library | `egress`, `catalog` |

### 7.4 Code that enforced the old rule

| Site | Becomes |
|---|---|
| `BrainRequest`, `SCHEMAS`, `validate`, `build_prompt`, `SYSTEM` in `services/brain/__init__.py` | replaced by ADR-0017's purpose schemas and observation; the provenance filter, not a constructor, enforces `cloud.text` off; `SYSTEM`'s exact age becomes the age band |
| `coach.py`, `controls.py` (target = page text) | kept for controls; free text allowed by provenance |
| `session.say(local_only=…)`, `tts.LocalOnlyUnavailable` | TTS routing by provenance (§2) |
| `records.export_session` ("never learner free text") | local export may include learner text; never sent |
| `REDACT_TERMS`, `setup --redact`, the `redact-terms` alert, the `.env` manifest | `household_terms` (migrated), the settings page, alert renamed |
| `envprotect.GATE_FLOOR` (`BRAIN_BACKEND=ollama`, `BRAIN_LOCAL_MODEL`) | lifted when D10 is recorded (§2) |
| `envprotect.PRIVACY_FLOOR` | extended with §5's † keys |
| `LEAFI_NO_NETWORK` | test switch: refuses every protected connect, grants included |
| `tests/test_privacy.py` | rewritten (Confirmation) |

### 7.5 Documents that state the old rule (changed in the change that accepts this ADR)

`AGENTS.md` (first MUST NOT → §8's one line); `security.md` (red lines 1–3, the destination table → §2's table, the privacy settings → §5, retention → §4.3); `product.md` (principles 1–2, Users, the Non-Goal "no cloud vision, no cloud ASR … ever"); `GLOSSARY.md` (Brain, Eye, Learner; new: learner kind, guest, provenance, remote teacher, grant, surrogate name, gateway port); `data-model.md`; `flows/reading-session.md`; `architecture/overview.md` (items 3–4), `c4-context.md`, `c4-container.md` (magpie added), `deployment.md`; `architecture/config.md` (`setup --redact`); `engineering/code-locator.md`, `engineering/testing.md`, `engineering/repo-map.md`; ADR-0003, ADR-0011 (`superseded-in-part-by: 0018`), ADR-0016 (the `redact-terms` alert, its egress rows → `ops`, magpie as a supervised child).

### 7.6 The owner's console

Buttons: `leafi migrate --learner` (once, then removed), enrol a learner and run the recognition probe (voice per Ear; face on the study camera), `forget --learner`, start magpie with `DO_NOT_TRACK=1` under the supervisor; help lines for `forget`, the export and the settings page; the console's own check.

## 8. AGENTS.md boundary (replaces the first MUST NOT when this ADR is accepted)

"MUST NOT send anything from `leafi/` to a cloud service except through `leafi.privacy.egress`, under the egress table and privacy settings of `security.md` (ADR-0018). Enforced by: `tests/test_privacy.py`, `tests/test_netguard.py`." (One line and a link; the table lives in `security.md` only.)

## 9. Provenance of this ADR's mechanisms (code-plan-review H7)

| Mechanism | Verdict | Source |
|---|---|---|
| learners, ownership, keys, `forget` with `forgetting` | original | Leafi's schema; the two-phase delete is a standard soft-delete-then-purge pattern |
| guest end states, sweep | original | owner decisions |
| speaker recognition | adapted | sherpa-onnx speaker identification; enrolment by averaged clips (prior-art LP12) |
| face models | adopted | YuNet, SFace (prior-art LP20, LP21) |
| durable confirmation (`adopt`) | original | conditional update, as for consent |
| egress seams, mediated transport, synthetic 403 | adapted | libraries §6 (mediator transport, refusal shape) |
| socket guard, grants, async `getaddrinfo` answer | original, searched | libraries §6; no library offers per-request socket authorisation in-process |
| gateway ports | original | owner decision 8 |
| one client family (`httpx2`) | adopted | libraries finding 1 |
| redirect hosts per destination | adapted | libraries §6 (urllib/HF redirects) |
| HMAC log | adopted | prior-art LP3 |
| provenance classes and sources | original, searched | prior-art §3 found no library for per-field source tracking at this scale |
| pseudonymisation lists + Presidio detector + surrogates | adopted / adapted | Presidio (prior-art LP1, LP2); surrogates (LP9, one study) |
| remote teacher, `prepare` checks | original | owner decision 6; YuNet for the face check |
| consent table | adapted | ISO/IEC TS 27560 / DPV (prior-art LP47) |
| retention table | adapted | prior-art LP41, LP43 |
| `tzlocal` for the zone | adopted | code-plan-review v3 H4.1 |
| `portalocker` for process exclusion | adopted | cross-platform file locks; searched: SQLite cannot report other connections |
| migration in one transaction with `foreign_key_check` | adopted | SQLite's documented 12-step ALTER TABLE procedure; libraries §1 |

Research findings that no decision above uses, each with its fate: C15/N4 (implicit promotion from reading) — rejected, acoustic and alignment evidence is stronger; B12 (explicit error marking) — used in ADR-0017's practice after reading; C47/D18 (magpie structured-output probe) — used, §2; §9.6 (AnkiConnect review counts) — used in ADR-0017 §3.1 `review_anki` (`getNumCardsReviewedToday` is checked against the installed add-on before it is relied on); R5/D12 (the `fallbacks` documentation fix) — done with TD-1; qwen3-vl local second opinion — deferred with the Ollama gate (§2); the person/body detector gap — stated in §4.1.

## Consequences

- The Brain can see what the children said and asked; each learner's `cloud.text` switches it off, also for stored notes and shared material; every privacy behaviour is a setting with a stated default.
- Siblings share one Leafi with separate records; voice recognition adds a model, a probe per Ear and enrolment; face waits for a measurement.
- Parent controls are absent by choice (§6); AnkiWeb sync is the household's own check.
- Enforcement is per request at the call level and per transmission at the transport, with the socket guard behind both.

## Confirmation

`tests/test_netguard.py`: refusals (outside a grant through `httpx2`, `asyncio` streams, a thread executor, `edge_tts`; a grant for A refuses B; magpie's and the local Ollama's ports without a grant; an expired grant; `LEAFI_NO_NETWORK` inside a grant) **beside positive controls** (inside a grant the real `anthropic` client and `edge_tts` resolve through the patched async `getaddrinfo` and reach a fake server on a non-loopback test address; a pooled second request through a mediated client succeeds and is logged as its own attempt; an `ops` download follows an allowed redirect and is refused on another; a `lan` device connects). `tests/test_egress.py` (a mediated client refuses a request without an attempt token, with a spent token, and with a body whose HMAC differs from the token's; media is never retried; the budget is reserved per transmission; a refusal is a 403 with a reason; a local destination receives learner text with `cloud.text` off; edge-tts through `egress.aiohttp_connector` is mediated, probe first). `tests/test_architecture.py` (SDK clients only through `egress.client`; `learner_store` imports nothing from `study`). `tests/test_privacy.py` rewritten: two canary learners, `cloud.text` on and off; no real name, exact age or school in any body, including page text that quotes a forgotten learner's correction and the system prompt; an unlisted school and a friend's name in learner text are replaced; with `cloud.text` off no `learner` / `derived_from_learner` canary appears; with `privacy.tts_learner_lines = local` edge-tts never receives a learner line; media only after a consumed `remote_teacher` consent; never for a guest or with `privacy.media = never`; the no-network run completes. `tests/test_learners.py` (identify paths; `adopt` refused for a learner being forgotten and retried on busy; text-mode identification after a lost Ear with a console, terminal without; each guest end state of §1 including a terminal before `identify` returned and a crash after an ended session; the sweep spares `anonymous` and open sessions; ids never reused). `tests/test_open_db.py` (empty file → latest schema; current → opens; data below 5 → refuses with the command; open refused while the migration holds the lock). `tests/test_migration_5.py` (refused while another process holds the database; a failure mid-rebuild leaves version 4 intact and re-runnable; schema equals fresh; new CHECKs accept their values). `tests/test_forget.py` (refused during a running session; removes every listed store and every derived copy sourced from the learner; a derived write by another learner's session naming the learner is refused while forgetting runs, and the final rescan removes one written just before; the learner's names keep being replaced in shared page text). `tests/test_learners.py` also covers `guest.keep_days = 0` (deleted at wrap, no notes). `tests/test_consent.py` (a `media` send consumes a `remote_teacher` consent; other purposes refused), `tests/test_media_prepare.py`, `tests/test_pseudonym.py`. `egress_log` rows hold an HMAC, never a body or a bare hash.

## Reviews

Under `../plans/active/reviews/`: codex design reviews 1–6 (2026-10-21), code-plan-review passes 1–2, and the independent codex and code-plan-review rounds on v3 (2026-10-22).
