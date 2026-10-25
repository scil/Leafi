---
status: proposed
date: 2026-10-25
revision: 5
---

# The session panel: design

Plan `2026-10-25-study-session-panel.md` (owner decisions C1(a) and C2(a), 2026-10-25). Research:
`docs/research/2026-10-25-session-panel.md` (its questions cited as R§Qn, its source rows as S*n*, its decision pool
as A*n* / F*n* / R*n*). **Session panel** is this plan's term (industry: operator console): a loopback page in the web
UI that shows the running study session and sends typed commands into it. A **panel line** is a line the panel sends;
it is an `Utterance` with `source = "panel"`.

ADR-0017 keeps owning the loop, negotiation and statuses; ADR-0013 keeps owning reading and practice. This design
amends ADR-0017 in three places (marked **[ADR-0017 amended]**, written into the ADR by step 1) and leaves ADR-0013
unchanged. Other mechanisms are marked **[beyond ADR]** with their provenance.

History: rev 1 had three reviewers (round 1: `reviews/2026-10-25-session-panel-round-1-comparison.md`, themes T1–T24;
codex was out of quota, two fresh Claude sessions and `code-plan-review` ran). **Rev 2** answers every theme (table at
the end) and the owner's four answers of 2026-10-25: a panel question in `learner_questions` is refused; panel lines
are stored as text and counted, never evidence, with no migration; panel Anki eases go to Anki; the runtime file keeps
the profile's default permissions.

**Rev 3** answers codex's increment round on rev 2 (`reviews/2026-10-25-session-panel-rev2-codex.md`, 13
findings). Six of them, after two rounds of findings on `/do`, came from one decision: interrupting an activity at a
listen. Rev 3 restates D7 on the session's existing `stop` cancellation, narrowed to the activity's scope; the other
seven are fixed where they stand.

**Rev 4** answers codex's round 3 on D7 (`reviews/2026-10-25-session-panel-rev3-codex.md`, 9 findings): the nested
scope is sound in anyio, but cancelling at any await and continuing is not; D7 now interrupts only at safe points
(the activity's listens, where `StaleInput` already ends activities, and `read_aloud`'s sentence gaps), which removes
findings 1, 2, 4, 6 and 9 and the rev 3 Hub change; 3, 5 and 8 are answered in D7; 7 predates the panel and goes to
tech debt.

**Rev 5** answers the confirming round on rev 4 (`reviews/2026-10-25-session-panel-rev4-claude.md`: a fresh Claude
standing in for codex, out of quota mid-round; 0 High, 6 Medium, 5 Low). It confirmed the safe-point rule; its
findings were mostly in the owner's new note and banner (what the snapshot can show, Skip and Next page) and in
negotiate's exits. Rev 5 also ends an activity at its natural step before the next question (D7 safe point (a)).

Status: rev 5. Five rounds have run (the review budget). Next: a last codex increment round on the rev 5 diff when
its quota returns, or implementation at the owner's word.

## The rule in one place

A panel line moves the session and never counts as the child's: no alignment, no retrieval event, no encounter, no
practice attempt, no Brain call that takes it as the child's words. It is stored as text like any typed line and
counted per activity. The few panel actions that do write state write it under the owner's name (`parent`, `owner`)
or are the owner's judgement by decision (an Anki ease, a supplied hint word). D8 lists every site.

## Decisions

**D1 The panel device [beyond ADR].** `leafi/devices/panel.py::PanelDevice`, adapter `panel`, capabilities
`[listener, face]`, registered in `leafi/devices/__init__.py`. The composition root builds it only for
`study --panel`; `--panel` also adds it to `runner._mock_config()` (T10). Settings: `STUDY_PANEL_PORT` (a `Settings`
field and an `env-schema.json` key, default 0 = an ephemeral port).

- Face: `show(Display)` appends `(monotonic, kind, text)` to a ring buffer of 200 entries and marks the snapshot dirty.
  It never prints.
- Listener: `is_voice = False`, `main_capable = False` (D2), `pause`/`resume` as no-ops (the `Listener` port and
  `ListeningGate` need them, T24). `next_utterance(timeout)` takes the next press from an `asyncio.Queue`.
- Lifecycle: `start(snapshot_fn, loop)` is called by the runner from `Env.on_built`, which `run_session` calls after
  the speech lease is held (`loop.py:266` then `:302`), so a refused second session never binds or writes (T9). It
  binds, starts the serving thread, writes the runtime file (D4). `close()` is idempotent: it shuts down only a server
  whose thread started (`socketserver.shutdown()` waits for `serve_forever`, S4), through `anyio.to_thread.run_sync`,
  then `server_close()`, then removes its own file (T9).
- Faults stay in the device (T9): every exception of `start`, of serving and of the file is caught. The device first
  disables itself (it delivers nothing; `next_utterance` waits forever), then, on the loop thread (a fault seen by the
  serving thread is handed over with the guarded `call_soon_threadsafe`), logs it and tries one
  `alerts.insert(…, "study-panel", "event", "panel_failed")` inside its own `try`: a busy store or any other failure
  of the alert write is logged and dropped (codex 12). No panel fault reaches `Latch.spawn.guarded`
  (`latch.py:131-134`) or `on_built`.
- Endpoint: a stdlib `ThreadingHTTPServer` subclass with `allow_reuse_address = os.name != "nt"` and, on Windows,
  `SO_EXCLUSIVEADDRUSE` set before bind (S5, S6), bound to `("127.0.0.1", STUDY_PANEL_PORT)`.
- Threads: the serving thread never touches session objects (S1). The loop publishes, the thread reads: one attribute
  `published = (version, publish_t, json_bytes)`, replaced whole by the loop thread. Refresh: `show`,
  `next_utterance`, the harness hooks of D3, `Inputs`' own transitions (speaking starts and ends, a listen starts
  and returns, a panel line's fate changes, `accepting` turns false; codex 10) and a POST's arrival set a dirty flag; a refresh runs at once when the last
  one is older than 0.2 s, else one trailing `loop.call_later` is armed (T6). A snapshot that raises is logged and the
  old one kept.
- Requests: `GET /status?since=<version>` → 200 with the published JSON, or 204 when `since` equals the current
  version; `POST /input` with JSON `{"session_id": n, "line": "...", "seen": <publish_t>}` → 202 (409 when
  `session_id` is not this device's session or `Inputs.accepting` is false, so a press never reaches another or an
  ending session, codex 3 and 10), handed to the loop by
  `loop.call_soon_threadsafe(queue.put_nowait, …)` guarded for the `RuntimeError` of a closed loop (S2). The device
  stamps the utterance `ended_at = seen` (the publish time of the snapshot the owner acted on, T13), so D21's owner
  timeline gives it the prompt that was on the owner's screen; a line for a prompt that has moved on is parked or
  dropped by D21's existing rules, and its fate shows on the panel (D3). Every request needs
  `Authorization: Bearer <token>` (compared with `secrets.compare_digest`), a `Host` of `127.0.0.1:<port>` or
  `localhost:<port>`, and **no** `Origin` header (A5, confirmed by all three reviewers); else 403. `Content-Length`
  over 2 KiB is 413 before the body is read; a line that is empty or holds CR/LF is 400 (T18, an empty typed line
  is a sentence end, `activities.py:142-147`). No request text goes into a response header (S3).

Provenance: *adapted* from `ConsoleDevice` (thread, `call_soon_threadsafe`) and the web UI's `_Server`; publish by
reference from the asyncio threading docs (S1, S2; A1–A3); bearer and Host from Jupyter's `check_host` (S14, S16); the
no-Origin rule A5; the trailing refresh is the standard debounce with a trailing edge (*original* here, no library
used); start after the lease is *original* (rev 1's lazy start copied the console's no-import-side-effects reason,
which does not apply to a server). Deferred: aiohttp's `AppRunner` (F1). Rejected: a hand-written server (R1), a
database command table (C1(b)).

**D2 Several typed sources in `Inputs`; the panel never leads [ADR-0017 §1 amended].** `Inputs.__init__` takes
`control_sources: list` (the runner passes every non-voice Listener of the Hub other than the main one; `Env` gains
`control_sources`; `control_source=` stays as a one-element shorthand for tests). `start()` adds one reader per
source, named `control:<device name>`. The main source is tracked by name (`self.main_name`), replacing the
`_console_is_main` flag, so only the main source's `None` is a timeout after an Ear switch (T11, `inputs.py:164`).
`_speak` requests every typed source while audio plays, the main one included when it is typed (`inputs.py:314-315`
hard-codes `"control"`, T24).

- A listener with `main_capable = False` is never the study listener and never the Ear's replacement. The composition
  root skips it when it picks the text-mode or fallback listener (`app.py:79-81, 87`, T10), and adds the console
  whenever no **main-capable** listener exists (today it adds one only when the slots are empty, `app.py:71`, so a
  panel-only configuration had none); `Hub.listener()` applies the same rule at its own fallback (`hub.py:167`)
  (codex 13); `_listener_lost` picks
  the first typed source that is `main_capable` (the console), else `listener_lost_no_console` as today (T11: a
  panel alone cannot read for the child, so the session ends honestly).
- Under `--panel` without an interactive stdin the console's end of input is ignored instead of becoming `/stop`
  (`console.py:47-48`; a console option `eof_stops`, T10).
- Two lines in one prompt: the first delivered answers, the other is dropped as stale at the next owned listen, as
  today (`inputs.py:227-234`); the panel shows the drop (D3).

Provenance: *adapted* from M7 D21's reader model (one demand-driven reader per source).

**D3 The status snapshot [beyond ADR].** `leafi/study/harness/snapshot.py::snapshot(s, w) -> dict`, synchronous,
**memory only**: it runs on the loop thread and reads no database (T7: `show()` runs before every spoken line,
`hub.py:203`, and a SELECT can wait up to the 250 ms busy timeout). The runner hands the panel
`lambda: snapshot(s, w)` through `Env.on_built`; the harness never imports the device (ADR-0002).

What the snapshot needs that is not in memory today is kept by the harness:
- `Session.log`: the session's activities in memory (`id, kind, decided_by, params, started, status, outcome`),
  appended by `run_activity` at start and updated at both finish paths (`finish_now` and the normal end);
- `Session.learner_label`: kind and first name, set when identification adopts or creates the learner (the only reads
  are the ones identification already makes);
- `Session.boundary.menu`: the menu `_body` last computed;
- `World.printed`: the printed page number, set where the page is acquired or opened (today it is SELECTed, codex 11);
- the reading state kept true in memory: when practice or a cycle's closure settles a token in the stored reading
  state (`rows._settle_token`, `rows.py:76`) for the page read that `w.state` holds, the same change is applied to
  `w.state` (one function both use), so the snapshot never shows a settled candidate as open (codex 11);
- `Inputs.panel_log`: the last 20 panel lines with their fate. Fates: `queued` (posted, not read yet: the device
  publishes its undelivered lines), `answered`, `parked`, `dropped_stale`, `refused`, `cut` (a skip that cut a
  line), `skipped`, `turned`, `ignored` (an activity had no use for it, such as `/next` in `break`), and for a `/do`:
  `pending`, `switched` (set when `run_activity` starts the wanted activity), `replaced` (a newer want), `want_refused`
  (with the session's reason), `dropped` (with its reason: `stop`, `session_end`, `soft_deadline`). A `/do` typed on
  the console has no entry; the snapshot still shows its `want` with `source = console`.

`Session.hooks` (a list of zero-argument callables, default empty) is called by `run_activity` at start and end and by
`_body` at each boundary start; the runner appends the panel's "mark dirty" there (T6).

| Field | From |
|---|---|
| `version` (`"<session_id>:<n>"`, T19), `publish_t` | the device |
| `session`: id, mode, started, deadline instants (soft, hard) as monotonic offsets from `publish_t`, arm, terminal | `Session`, `Latch`; the page counts down, so clocks do not change the version (T6) |
| `learner` | `Session.learner_label` |
| `book`, `page`: title, printed number, page id, revision id | `World` (title cached when `identify_book` sets it) |
| `activity`: the running entry of `Session.log`, or null at a boundary | memory |
| `prompt`: `Inputs.current_owner` as a string, the last `say`/`ask` text | `Inputs`, the Face buffer |
| `io`: speaking, listening, voice, Eye online, lease held | `Inputs`, `Hub` |
| `reading`: sentences completed / total, tokens by status, the current sentence with statuses | `w.state`, through `reading_counts(state)` |
| `boundary`: menu, current offer, excluded, offers | `s.boundary` |
| `activities` | `Session.log` |
| `panel_log` | `Inputs.panel_log` |
| `want`: kind, source, set at, its `panel_log` index, and `waiting_for`, checked in this order — `setup` (no boundary has started yet), `brain` (`Inputs` is inside `controls_only`; the filler may be speaking then, so `brain` wins over `speech`), `speech` (a line is playing), `step` (anything else: OCR, Anki, a write) — or null once taken | `Latch.want`, `Session.first_boundary_started`, `Inputs._waiting`, `Inputs.speaking` |

`reading_counts(state)` moves the counting out of `World.end_page_read` (`world.py:266`), which then calls it (T24).
Provenance: *original* in its fields; the exemplars push events per frame (S24–S28), which would need a second copy
of the state rules, so the panel reads state (A6).

**D4 How the web UI finds the session [beyond ADR].** After binding, the device writes
`data/run/study-panel-<pid>.json` = `{schema: 1, pid, create_time, port, token, session_id, started_at}` (token
`secrets.token_urlsafe(32)`, `create_time` from psutil) by write-to-temp and `os.replace`; `close()` removes its own
file. At `start`, the device removes other `study-panel-*.json` files whose process is gone. The web UI **never
deletes**; it lists the files and uses the newest live one: live = `leafi.core.lease.pid_alive(pid)` and psutil's
`create_time` equal to the file's (a reused pid fails this; `egress.py:227-240` does the same) (T8). A 401/403 from
the endpoint means "no live session"; a timeout with a live process is shown as "session busy", not as stale. The
file keeps the profile's default permissions (owner, Q3). Provenance: *adapted* from Jupyter's `jpserver-<pid>.json`
(S17), with the owner's process check of `lease.py` and `egress.py` in place of Jupyter's `check_pid`.

**D5 The web UI's "Reading" tab.** `agent/webui` gains `GET /api/study/status` and `POST /api/study/action`.
- Checks: the existing Host and page-token checks; for `POST /api/study/action` the Origin must be present and match
  (stricter than `_post_ok`, which accepts a missing Origin, `__main__.py:115`; T18), and `Sec-Fetch-Site`, when
  sent, must be `same-origin` or `none` (another loopback port is `same-site`, T18).
- The safe-point rule is shown on the page (owner, 2026-10-25), so a delay never looks like a broken button:
  - before a press: the "Go to activity" control carries a fixed note, "Takes effect at the next safe point: before
    Leafi asks the next question, while Leafi is listening, between two read-aloud sentences, or between activities —
    not during setup (name and book). A spoken line, a Brain answer or a page scan (OCR) always finishes first.";
  - after a press: a banner from the snapshot's `want` (D3), with the seconds since the press, until its fate is set:
    "Switching to *break* after the Brain answers" / "… after Leafi finishes speaking" / "… after this step" /
    "… once Leafi knows who is reading and which book" (`waiting_for` = `brain`, `speech`, `step`, `setup`); a press
    the session has not read yet shows "Sent, waiting for the session" (fate `queued`);
  - the result: the banner shows the fate (`switched`, `replaced`, `want_refused` with the reason the session gave,
    `dropped` with its reason, `dropped_stale`) for 5 s.
- Skip and Next page get their own, truthful notes: Skip — "Cuts the line Leafi is saying; otherwise skips the
  current question when Leafi next listens"; Next page — shown only during a reading activity or at a boundary,
  "Turns the page when Leafi next listens". Their result shows as the line's fate (`cut`, `skipped`, `turned`,
  `ignored`, `dropped_stale`) from `panel_log`; there is no "waiting" banner for them, since they create no want.
- States (T24): `live` (proxied snapshot, buttons shown); `busy` (live process, endpoint timed out: last snapshot
  greyed, no buttons); `none` (no live session: the last session from the database, no buttons); `db_error`
  (`SchemaError` / `DatabaseInUse`, shown as text, as the OCR tab does).
- The database fallback opens `file:<db>?mode=ro` per request and closes it at once (`storage.py:1016`), so a polling
  tab never holds the shared lock that `leafi migrate` and `backup` need (T17).
- The page polls `status` once a second while visible, with `since`; each action POST carries the `session_id` and
  `publish_t` of the snapshot on screen; buttons are disabled from a press until a newer version arrives (T13). The
  web UI forwards an action only to the runtime file whose `session_id` matches; when that session is gone the action
  is refused ("that session has ended"), never sent to the newest one (codex 3).
- The web UI server forwards with the bearer token; the browser never sees it.

Provenance: *adapted* from the OCR tab; polling A6 (SSE deferred, F2).

**D6 Actions: a fixed table [beyond ADR].** `POST /api/study/action` takes `{"action", "text", "seen"}`; the web UI
maps `action` through this table, so no free command reaches the session, and validates the values:

| action | line | validation |
|---|---|---|
| `skip`, `stop`, `next_page`, `yes`, `no`, `know` | `/skip`, `/stop`, `/next`, `/yes`, `/no`, `/know` | – |
| `ease` | `/again` … `/easy` | one of four |
| `page` | the text written to `<settings.cache_dir>/panel/page-<n>-<token8>.txt` (absolute, unique per paste), then `/page N --text <path>` | `n` an integer; the path has no spaces (`controls.py:76` rejoins with single spaces) |
| `fix` | `/fix OLD NEW` | OLD one word (`controls.py:83-85`) |
| `answer` | `/say <text>` | non-empty, ≤ 500 characters, no CR/LF, not starting with `/` |
| `do` | `/do <kind>` | a kind of `activities.KINDS` except `wait` |

`/next` becomes a page item like `/page` in `Inputs._deliver` (`inputs.py:179` makes one only for `page`) and in
negotiate's page check (`negotiate.py:173-174`), so a Next page pressed at an offer turns the page instead of being
read as "no objection" and starting the offered activity (round 4, 3c). This also changes a typed or spoken "next
page" at an offer, for the better; `tests/test_negotiate.py` covers both.

Panel lines are parsed with `controls.parse_typed` only, never the spoken grammar, so an answer "stop" or "good" is
data (T12). `/say <text>` is a new typed control whose `text` is the answer; for the console `/say` is the same as
typing the text. Both servers resolve `cache_dir` from `Settings`, so the two working directories do not matter (T20).

**D7 `/do <kind>`: the owner names the next activity; it takes effect at a safe point [ADR-0017 §2.1 amended].**
History: rev 1 posted a skip, rev 2 raised from `listen()` with the request in two copies, rev 3 cancelled the
activity's scope at any await. Codex's round 3 (`reviews/2026-10-25-session-panel-rev3-codex.md`) confirmed that the
nested scope works in anyio, but showed that cancelling at an arbitrary await and then **continuing** the session
leaves new half-done states in almost every activity (an Anki answer acknowledged but never recorded, a page request
dropped during OCR, a hint word spoken without its supplied token, feedback heard without its evidence). Its own
inventory also shows that a stop at an activity's **listen** reaches only states that exist today, because
`StaleInput` ends activities there (`inputs.py:224-225`) and `aborted_stale` is handled. Rev 4 therefore interrupts
only there.

- **Safe points**, the only places a want ends a running activity, earliest first:
  (a) the activity's natural step: `World.activity_over()` is also true while `latch.want` is set, and every item
  loop already checks it at its top and after a completed sentence (`activities.py:309, 333, 412, 494, 542, 636,
  729, 838, 880`), so the activity ends `completed` with its real outcome **before** it asks the next question (round
  4, 4: otherwise the child heard a question that was then abandoned);
  (b) the start of an owned prompt (`Inputs.ask`, `line(owner=…)`) during an activity raises `Jump`: an owned
  prompt is always followed by its listen with no write between them, so this is the same state as (c), one line
  earlier; it also covers `read_aloud`'s sentences;
  (c) every owned `listen()` of the activity, including the helpers it calls (`_offer_hint`, the practice retry,
  `acquire_page`'s listens): the positions where `StaleInput` fires today.
  Speech, Brain calls (`generate`, `judge`, `answer`, the filler), OCR and Anki calls always run to their end; a want
  waits for them. `scoring.item_used`'s `judge` call is wrapped in `controls_only` like the other Brain waits, so
  typed `stop`/`skip` act during it and the snapshot shows `brain` (round 4, 9; closes the second half of TD-30).
  The price is latency: up to one spoken line, one Brain call or one OCR read (seconds). The panel states the rule
  and shows a pending want with what it is waiting for (D3 `want`, D5).
- One representation: `Latch.want: Want | None`, `Want(kind, source, owner, at)`. The input stream gets only a
  payload-free **wake** item, which carries no request: a wake that finds no want, or no running activity, is
  ignored, so a duplicated or late wake changes nothing (codex round 2, 1).
- `controls.parse_typed` gains `do` (`Control("do", text=kind)`), typed only. `Inputs._deliver` on `do`, on the loop
  thread, in this order: (1) the owner check: a `do` whose stamp belongs to a prompt that has ended is logged
  `dropped_stale` and nothing changes; (2) `kind` must be in `activities.KINDS` minus `wait`, else
  `want_refused`; (3) `latch.want = Want(…)` (a newer want replaces an older one); (4) one wake item into the stream.
  Nothing touches speech: a line that is playing finishes.
- The panel's reader is **always asked**: it is re-armed after every delivery, whatever the line was (round 4, 1). A
  panel line is stamped with the `seen` of the snapshot the owner acted on, so reading it early cannot change which
  prompt owns it; and a press is handled (want set, banner shown) even during a step where no listen or speech asks
  the readers. Until the reader has taken a line, the device lists it as `queued`.
- `listen()`, on a wake item or when it starts with a want set: during an activity (`activity_started_at` set) it
  raises `Jump` (safe point (c)); at a setup prompt it ignores it and keeps listening (the want waits for the first boundary, codex
  round 2, 6); at a boundary it returns None to its caller only when the caller is negotiate's offer listen, which
  then re-checks the slot (below); otherwise it keeps listening.
- `run_activity` catches `Jump` beside `StaleInput` (the same place, so `except (Terminal, cancelled)` never sees it):
  the activity ends `completed` (a status every kind may end in, ADR-0017 §3.1) with
  `outcome = progress | {"ended_by": "do"}`. An activity that ended at safe point (a) returns its own outcome, to
  which `run_activity` adds `ended_by = "do"` when a want is set. Its `finally` blocks run as for `StaleInput` (`read_listen` saves its
  page read, `activities.py:355`).
- Reading after a want: the page read is saved and the next `read_listen` chosen at a boundary opens a new cycle with
  range `rest`, as after an activity that hit `limits.activity_max_min` (ADR-0013 → Cycles; `world.py:273`). A
  provisional, uncommitted run in the current sentence is read again from its start; candidates of the closed cycle
  are settled by the cycle's closure as today. This is a stated consequence, not a new rule (codex round 3, 3).
- Partial outcomes: `Session.log`'s running entry has a `progress` dict the activity updates after each completed
  step, holding every scalar outcome field a reader uses: the Ledger's `quiz.questions`, `teach_items.items`,
  `add_cards.cards` (`ledger.py:41-63`); the notes' scalar fields (`notes._activity_leaves`, `notes.py:97-105`:
  `sentences`, `page_read_id`, `questions`, `answered`, `cards`, `items`, `results`). `records.summary` reads no
  outcome (codex round 3, 8: rev 3 claimed it did). Both finish paths merge `progress`, so a jumped quiz keeps
  `questions = 3`. Evidence rows stay the only mastery record; `progress` never stands in for them.
- At a boundary: `negotiate` takes the want (`latch.take_want()` → `b.wanted = want.kind`) at the top of each pass and
  checks the slot before **every** exit — each `return Run(…)` (the wanted path, `negotiate.py:131`; the announce
  band, `:162`; the `yes` path, `:185`; the argue band's no-objection path, `:197`), each `return wait_or_end(s)`
  (`:140, :151`, and the silence path), and the named-choice `end` — and re-starts the pass when a want is set (codex
  round 2, 1; round 3, 5; round 4, 7). The offer listen's result is checked against the slot **first**, before
  `parse_choice` and before `b.silences` or `b.offers` change, so a wake is never counted as a silence (round 4, 6).
- `_body`'s continuation loop (`loop.py:405-410`: a page turn or an Ear switch continues `read_listen` without
  negotiating) runs only while `latch.want is None`; with a want it goes to the boundary (round 4, 5). A want taken
  and then lost to the soft deadline (`loop.py:400`) gets fate `dropped` (`soft_deadline`). `_body` checks it
  before the Brain's `sequence` call (`loop.py:386`). A want that arrives during a boundary's Brain call, speech or
  offer listen takes effect when that step returns (the same safe-point rule). Taking a want drains the skips.
  The existing `wanted` path then runs it with `decided_by = "learner"`, `override = "learner_choice"`, or says
  "I can't … right now" when it is not constructible; the snapshot shows that line (`want_refused`).
- A want set at a setup prompt waits for the first boundary, where `wanted` validates it against the first real menu
  (codex 6); a typed kind that is not a kind at all was already refused at (2).
- The activity a want starts carries `params.by = want.source` (T21).
- Ending: after `_body` returns or the session scope is cancelled, `Inputs.accepting = False` is set before
  `finalize`; `_deliver` drops every line after it (logged `refused`), and the device answers 409 (D1, codex 10).

Provenance: *adapted* from `StaleInput` (an input that ends the running activity at its listen, ADR-0017 §1) and
negotiate's named-activity path; the wake item and the progress dict are *original*. Rejected: rev 3's cancellation
at any await (codex round 3: new half-done states; making it safe needs a commit point in every activity).

Outside this change, recorded rather than fixed (codex round 3, 7): today's normal finish retries a busy write
outside the cancellation handler, so `/stop` during that retry leaves the row `running` for startup recovery; and an
outcome kept in `pending_rows` is not visible to the next boundary's Ledger. Both predate the panel; `/do` adds no new
path to them. They go to `docs/plans/tech-debt.md`.

**D8 Every site where a panel line could count as the child's [ADR-0017 §3.4 amended].** ADR-0017 §3.4 says typed
answers always count (0017:223); the amendment adds "except a panel line, which never counts". One predicate owns it:
`scoring.counts_as_answer(u)` = not `source == "panel"` and (`typed` or (`u.words` non-empty and every word
confident)); `activities._confident` and `scoring.confident` both become this one function (T1). The non-empty
condition is `scoring.confident`'s today (`scoring.py:28-29`); for `activities._confident` it is a tightening: a voice
utterance with no words no longer counts in quiz and review (codex 9; today `all([])` is true there).

Panel lines are also limited at the device: `POST /input` accepts only the lines of D6's table (`/skip`, `/stop`,
`/next`, `/yes`, `/no`, `/know`, the four eases, `/page N --text <path>`, `/fix`, `/say`, `/do`); anything else, such as
`/explain` (which creates a knowledge item and an encounter, `activities.py:336`), is 400 (codex 7). A `/say` payload
stays answer data: `Inputs` hands activities an `Utterance` whose `text` is the payload (which may not start with
`/`, D6) and `source = "panel"`; command lines arrive as their canonical typed text (`/skip`). Every
`controls.parse(u.text)` call site in the harness becomes `controls.of(u)`, which for a panel utterance is
`parse_typed` on a `/` line and None otherwise, so no spoken grammar re-reads a payload ("stop", "good").

| Site | Panel line behaviour |
|---|---|
| `quiz` (`activities.py:659`) | outcome `unavailable`; the Coach says the answer; no retrieval event, no encounter |
| `review_anki` (`:516`) | the ease is sent to Anki as the child's review (owner, Q1): `review_answers`, then `card_state` and the item's re-fold on Anki's ack (`anki.py:268-290`); no retrieval event |
| `teach_items` / `recall_items` (`scoring.py:45, 52, 71`) | `unavailable`; `item_used` makes no `judge` call, so the owner's text never reaches the Brain as the child's (T1) |
| `learner_questions` (`:753`) | refused (owner): the Face shows "questions here come from the child"; no `answer` call, no turn used, listen again |
| `read_listen` / `read_aloud` | a free panel line is not aligned: a `noop` line, listen again; `/skip`, `/next`, `/page`, `/fix` act as typed |
| `practise_errors` | a free panel line is not an attempt: a `noop` line, listen again, no `practices` row; `/skip` acts as typed (ADR-0013 untouched, T5) |
| hint offer (`:225-249`) | `/yes` supplies the word as for the child: the owner saw the child stuck (T15) |
| `/know` (`:800`) | `item_status_events.source = 'owner'` (today `'learner'`) |
| `/fix` (`:192`) | `corrections.source = 'parent'` (allowed and handled, `corrections.py:106-110`) |
| learner notes | `notes._activity_leaves` (`notes.py:99-105`) reads outcomes: it sees `panel_inputs` and `ended_by` |

Records (owner: stored as text and counted): one path, exactly once (codex 8). `Inputs._deliver` appends every panel
line to `Inputs.panel_log` as `{at, line, activity_id or null, fate}` when it handles it, whatever happens next
(`stop`, a playback skip, a `do`, an answer; `listen` later updates `fate` to `answered`, `parked` or
`dropped_stale` and marks the snapshot dirty), and adds one to the running entry's `progress.panel_inputs`. `finalize`
merges the log into `reading_sessions.summary.panel_lines` (it builds the summary, so nothing written earlier is
lost, `loop.py:218-221`). The `utterances` rows activities already write stay as they are and are not counted again.
The Brain's observation of the last activity (`sequence.gather`, `sequence.py:64`) gains `panel_inputs` and
`ended_by` (T22).

**D9 Privacy.** The Reading tab shows the child's first name and words: loopback only; both hops refuse a foreign Host
(DNS rebinding) and a missing token; the web UI checks Origin and `Sec-Fetch-Site` on POST (R§Q3). No page image in
the Reading tab. The runtime file holds a token, not data (default permissions, owner Q3). Chrome's Local Network
Access does not gate loopback to loopback (S19, S20), so it replaces no check (R2). Egress: the Brain's
`last_activity` gains two counts (`panel_inputs`, `ended_by`): no text, through `leafi.privacy.egress` as today;
`security.md`'s egress table and the `sequence` prompt version name them (T22). No panel line is sent to the Brain as
the child's words (D8). The Windows Firewall prompt for a 127.0.0.1-only bind is measured once at step 6 (G2).

## Steps

Each step is one commit with `.venv\Scripts\python -m pytest -q` green.

1. **ADR-0017 amendments and the predicate.** §1 (several typed sources; `main_capable`), §2.1 (`/do` and the want
   slot), §3.4 (a panel line never counts). `scoring.counts_as_answer`; `activities._confident` and
   `scoring.confident` replaced; `/say`. Tests: a panel answer in quiz, review, teach `item_said` / `cloze_word` /
   `item_used` (no `judge` call), recall writes no retrieval event and no encounter; `learner_questions` refuses with
   no turn used; practice writes no `practices` row; reading does not align; `/know` and `/fix` carry `owner` /
   `parent`; "stop" as `/say stop` does not stop.
2. **`/do`.** `controls`, `Latch.want`, the wake item, `listen`'s `Jump`, `read_aloud`'s check, `run_activity` and
   `progress`, `negotiate`'s exits, `_body`, `Inputs.accepting`. Tests: `/do break` during playback and during the
   listen at each autonomy band (the pass restarts, the announced kind never starts, a wait or end never wins over
   the want); during a quiz question after three answers (`questions = 3` kept, the Ledger sees it); during a quiz
   question's playback (the line finishes, then the activity ends); during `read_listen` mid-sentence in text and
   voice mode with a silent child (ends `completed`, `ended_by = "do"`, `break` runs, no sentence skipped); during
   `read_aloud` (ends after the current sentence); during a Brain `answer` wait in `learner_questions` (the call and
   the answer finish, then the activity ends at its next listen); during a practice score (the attempt row is
   written, the activity ends at the next listen); twice with different kinds (the second wins; two wakes, one jump);
   a kind that does not exist (refused, the activity goes on, the reader is re-armed); at a setup prompt (kept,
   validated at the first boundary); `/stop` while a want is pending (the session ends, the want is `dropped`);
   during a quiz's "Correct!" (the quiz ends before question 4 is asked); a want during a page-turn continuation (no
   OCR, no new page read, straight to the boundary); a wake at an offer below the argue band (`b.silences`
   unchanged); a queued child "yes" and a want at one offer (the want wins); two wants during the wanted path's
   construction (one `completed` row, the newer kind runs); once `accepting` is false, `_deliver` drops the line
   (logged `refused`; the device's 409 is tested in step 6).
3. **`Inputs` with several typed sources.** `control_sources`, `main_name`, `main_capable`, `_speak`, the console's
   `eof_stops`. Tests: a console and a panel line in one prompt (the first answers, the second is dropped and logged);
   Ear lost with console and panel (console leads), with the panel only (`listener_lost_no_console`); text mode with
   `--panel` keeps the console main.
4. **Snapshot.** `Session.log`, `learner_label`, `boundary.menu`, `hooks`, `Inputs.panel_log`, `reading_counts`,
   `snapshot.py`. Tests on a mock session through `Env.on_built`: fields at a boundary, during each activity kind,
   after an activity ends; the snapshot reads no database (a `Store` that raises on any call).
5. **Records.** `panel_inputs` counts on both finish paths and at boundaries; `sequence.gather`; `security.md`.
   Tests: counts after a `Jump`, after a cancelled activity, at a boundary; the observation carries them.
6. **`PanelDevice`, runtime file, runner and CLI wiring.** `--panel`, `STUDY_PANEL_PORT`, `start` from `on_built`,
   `close` in the runner's `finally`. `tests/test_panel.py`: missing token, foreign Host, any `Origin`, oversized body,
   CR/LF and empty lines refused; 409 for another session's id and after the body ended; a POST reaches
   `next_utterance` stamped with `seen`; a press during a step with no listen and no speech is read at once (always
   asked) and shows as `pending`; a GET answers from the
   published snapshot while the loop is blocked; the trailing refresh publishes the listening state; a raising
   snapshot keeps the old one; a bind failure and a file failure leave the session running with one alert; `close()`
   before start does not hang and is idempotent; a refused second `study --panel` (`LeaseHeld`) leaves the live file;
   stale files of dead processes are swept. Measure the firewall prompt once (G2).
7. **Web UI tab.** `tests/test_webui_study.py`: the action table and its validation; the safe-point note is on the
   page, and a snapshot with a `want` renders the banner with each `waiting_for` (`setup`, `brain`, `speech`,
   `step`, and `queued`) and then each fate; Skip and Next page show their own notes, and Next page only where it
   acts; Origin missing or foreign and
   `Sec-Fetch-Site: same-site` refused; each tab state; `since` across two sessions; the fallback opens `mode=ro` and
   leaves no lock (a `migrate` lock can be taken while the tab polls).
8. **Console button and docs.** `scripts/win/run_for_obsidian_console.ps1` case `study-panel`, its card, checked with
   `check-console.js` (AGENTS.md → Pointers); `GLOSSARY.md` (Session panel, panel line), `ownership-map.md`,
   `code-locator.md`; the plan's Progress.

End to end: `python -m leafi study --text --mock --panel --book X --page-text <file>` driven from the panel and the
console together: identify on the console, reading with a page turn, a quiz answered from the panel (no retrieval
event), `/do break` mid-reading, stop.

## Provenance summary

| Mechanism | Provenance |
|---|---|
| Panel device as Face + Listener | adapted: `ConsoleDevice` |
| HTTP in a daemon thread; no `SO_REUSEADDR`, `SO_EXCLUSIVEADDRUSE` on Windows; port 0 | adopted: stdlib, web UI `_Server`, Winsock docs (S3–S6, A1) |
| Publish by reference; commands by guarded `call_soon_threadsafe` | adapted: console; asyncio docs (S1, S2, A2) |
| Trailing-edge refresh | original (a standard debounce) |
| Start after the lease; faults kept in the device | original |
| Shutdown of a started server only; idempotent close | adopted: socketserver docs (S4, A3) |
| Bearer + Host + no Origin on the session hop | adapted: Jupyter `check_host` (S16); A5 |
| Web UI hop: Host, Origin required, JSON, token, `Sec-Fetch-Site` | adopted: OWASP CSRF (S12, A4) |
| `study-panel-<pid>.json`, reader never deletes, process check | adapted: Jupyter (S17); `lease.pid_alive`, `egress` create time |
| Stamp from the snapshot the owner saw | adapted: M7 D21's `ended_at` |
| Several typed readers; main by name; `main_capable` | adapted: M7 D21 |
| Memory-only snapshot, `Session.log`, hooks | original (exemplars stream events instead, S24–S28) |
| Read-only database fallback | adopted: `storage.py:1016` |
| 1 s polling with a session-scoped `since` | adopted: A6 (SSE deferred, F2) |
| Fixed action table, `parse_typed` only, `/say` | original |
| `/do` at safe points (listens, `read_aloud` sentence gaps, boundary exits), one `Want` slot, a payload-free wake | adapted: `StaleInput` (ADR-0017 §1); negotiate's named path |
| Partial outcomes in `progress` | original |
| One `counts_as_answer` predicate | adapted: ADR-0017 §3.4's unconfident-answer rule |

## Round 1 themes answered

T1 D8 · T2–T4 D7 · T5 D8 (practice, ADR-0013 untouched) · T6 D1, D3 · T7 D3 · T8 D4 · T9 D1 · T10 D1, D2 · T11 D2 ·
T12 D6 · T13 D1, D5 · T14 D8 (owner: refused) · T15 D8 · T16 D8 (owner: to Anki) · T17 D5 · T18 D1, D5 · T19 D3 ·
T20 D6 · T21 D7, D8 · T22 D8, D9 · T23 step 1 · T24 D1, D2, D3, D5, step 8.
