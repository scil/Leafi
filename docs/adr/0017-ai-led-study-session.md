---
status: proposed
date: 2026-10-21
revised: 2026-10-22 (code-plan-review with the owner's decisions: silence is not a yes, one status enum, settings reload, voice disagreement is not a failure, perceived-latency budgets, one path into Anki, inventory of what changes where); 2026-10-21 (codex design reviews 1–6: cycle ownership; restartable negotiation (Run | Reobserve); monotonic terminal latch and a once-taken skip; one absolute deadline for every wait; repeated continuation; generated-activity contracts and a judged `item_used`; Brain routing by task type and difficulty with full fallback chains)
supersedes: 0013 (session rules only, see §8)
amends: 0003, 0013 (Difficulties and Reposition speech: §8.6, §6.1)
---

# The Brain leads the study session; the study harness executes, measures and limits it

Research and the owner's requirements and decisions: [`../research/2026-10-21-ai-led-study.md`](../research/2026-10-21-ai-led-study.md) (pool D1–D20; this ADR takes D1–D5, D9, D11, D13, D15–D19 and the owner's 2026-10-21 request to choose the Brain by task type and difficulty; ADR-0018 takes learners, recognition, egress and consent). Reviews: [`../plans/active/reviews/`](../plans/active/reviews/) `2026-10-21-codex-ai-led-design-review-*.md`.

## 1. Decision and terms

A study session is a sequence of **activities**. At every activity boundary the **Brain** (the LLMs behind `services/brain`) chooses the next activity from a **menu** the **study harness** computes; the harness constructs, validates, runs, times, limits and records it. No correction happens inside a reading activity; errors found while reading are practised afterwards (owner requirement 2.2a; research §3.1).

- *Study harness*: the code around the Brain — observation, menu, construction, execution and timing, the ledger, records, routing, egress (ADR-0018), fallback. After Anthropic's "agent harness" (research R15). Glossary term.
- *Cycle*: an `open` record started by a reading activity chosen at a boundary; it owns every candidate its `read_listen` activities create, on any page. It closes when another boundary-chosen reading activity starts, at wrap, or on `stop`; closing settles what it still owns (§8.1). Continuations (§2) stay in it.
- *Epoch*: `(session_id, learner_id, cycle_id, page_read_id, revision_id, turn_id, settings_version)`. `turn_id` (ADR-0013 → Async guard) also increments on activity start and end, page turn, correction, learner confirmation, settings change. An item built under one epoch is dropped if the epoch has changed when it would be spoken, executed or written.
- *Controls*: the console reader, the Listener's control parser and the lease watcher post control events. `s.terminal ∈ {None, stop, lease_lost, time_up_session}` is **monotonic**: once set it is never overwritten (the first terminal wins). `skip` events go into a queue and are consumed exactly once by `take_skip(s)`; a skip posted while no activity runs belongs to the current negotiation and does not change the epoch (inside an activity it increments `turn_id` as ADR-0013 says). `checkpoint(s)` runs after every await (say, listen, Brain call, each activity step): it sets `s.terminal = time_up_session` when `now ≥ s.deadline`; it reads `learners.settings_version` (one indexed read) and, when the parent changed the settings, reloads them and the ledger limits and bumps the epoch; it raises `Terminal` when `s.terminal` is set. A `ListenerLost` raised by any listen — in an activity, in negotiation or in identification — sets `s.terminal = listener_lost_no_console` when there is no console, else switches the session to text mode and bumps the epoch.
- *Deadline*: one absolute `s.deadline = start + limits.session_max_min`. Every wait anywhere — a Brain call, a listen in negotiation or identification, an activity step — is bounded by `min(its own timeout, s.deadline − now)`.

## 2. The session loop (pseudocode is the rule)

```
run_session():
  s = Session(learner = new_guest())                       # ADR-0018 §1: a guest until confirmed; latch and finalize cover all
  try:
    s.learner = identify(s)                                # ADR-0018 §1; prompts use local TTS only
    s.book = identify_book(s)
    last = None
    while True:
      checkpoint(s)
      menu = allowed(s)                                    # §3.2; always contains "end"
      obs  = observe(s, last, menu)                        # §4; obs.epoch
      prop = brain_decide(s, obs)                          # §5; Decision | None; never raises except Terminal
      apply_records(s, prop.records if prop else [], obs)  # §7.1; epoch-checked; never blocks
      out  = negotiate(s, prop, menu, obs.epoch)           # §2.1; Run(activity) | Reobserve
      if out is Reobserve: continue                        # the state changed while deciding or asking
      act = out.activity
      if act.kind == "end": record_boundary(s, obs, prop, act); break
      last = run_activity(s, act)                          # §3.1; start/finish rows inside
      while last.status == "page_turned" and s.learner_kept_reading():
        last = run_activity(s, continuation(s))            # §8.2; same cycle; repeats for every turn
      if last.status in TERMINAL: break
  except Terminal: pass
  finalize(s)                                              # local, no awaits, never raises: below
  try: deliver(s)                                          # optional, best effort, own 10 s cap: below
  finally: release_lease(s)
```

`finalize(s)` runs with `checkpoint` disabled and does only local work in one transaction: close the running activity and the open cycle (§8.1), write the summary counts, set `ended_at`. If no learner was confirmed the session belongs to its guest (ADR-0018 §1) and the guest's rows are deleted here, keeping only the counts row. `deliver(s)` then speaks the closing line **only while the speech lease is still held** (never after `lease_lost`), queues the parent notification (not for a guest) and processes the Anki outbox, each skipped on failure or when its time runs out, and writes each step's outcome (`closing_line`, `notified`, `anki_synced`: done / skipped / failed) into the session summary, which the parent's export shows; nothing in `deliver` can undo `finalize`. The lease is released in a `finally` after `deliver`, whatever happened.

`ActivityStatus` is one enum; §3.1's table says which kind can end in which status, and a test fails when a kind can end in a status the table omits. `TERMINAL = {stopped, lease_lost, idle_session, time_up_session, listener_lost_no_console}`; the others (`completed`, `skipped`, `page_turned`, `aborted_stale`, `store_busy`) return to the menu; `interrupted` is written only by startup recovery. An activity that sees `stop` in its own step ends with `stopped`; one that hits the latch through `checkpoint` raises `Terminal`, which `run_activity` turns into a finished row with the terminal's status (`stopped`, `lease_lost`, `time_up_session`) before re-raising.

### 2.1 Autonomy and negotiation (Leafi's autonomy 0–10, owner decision 1)

```
negotiate(s, prop, menu, epoch) -> Run(activity) | Reobserve:
  END = {"kind": "end"}
  props = [p for p in ([prop.activity, prop.alternative] if prop else []) if p]
  def settle(specs, refusing = False):                   # the ONLY way a branch returns an activity
    a = first_constructible(s, specs + [END])            # may await generation (§3.3); END always constructs
    checkpoint(s)
    if take_skip(s):                                     # a skip during construction belongs to this negotiation
      if refusing or a.kind == "end":                    # skipping while refusing ends the choice: no recursion,
        drain_skips(s); a = construct(s, END)            # so a refused kind can never come back
      else:
        return refused_of(a)
    return Reobserve if s.epoch() != epoch else Run(a)
  def refused_of(x):                                     # defined before the first settle() call
    return settle([p for p in props if p.kind != x.kind] + [default_spec(s, menu - {x.kind})], refusing = True)
  first = settle(props + [default_spec(s, menu)])
  if first is Reobserve: return Reobserve
  act = first.activity
  speak = prop.say_before if prop and act.spec is prop.activity else describe(act)   # never announce a rejected proposal
  if s.autonomy >= 4: say(speak)                                             # includes one reason at 4–7
  else: ask("Shall we " + describe(act) + "? Or something else?")
  refused = lambda: refused_of(act)
  for turn in (1, 2):                                                        # at most one re-ask
    if s.autonomy >= 8: break
    c = parse_choice(listen(ASK_S))     # ASK_S = 8 s, deadline-capped; c ∈ yes | no | skip | named k | none | unparsed
    checkpoint(s)                                                            # stop / time_up / listener lost raise here
    if take_skip(s) or c in ("skip", "no"): return refused()                # skip settled before freshness (§1)
    if s.epoch() != epoch: return Reobserve
    if c == "yes": break
    if c in ("none", "unparsed"):                                            # silence is not a yes
      if s.autonomy <= 3 and turn == 1: ask("Shall we " + describe(act) + "?"); continue
      break                                                                  # then the proposal stands
    if c.named in menu: return settle([learner_spec(s, c.named), act.spec])
    say(why_not(c.named))                                                    # named but not in the menu
  checkpoint(s)
  if take_skip(s): return refused()
  return Reobserve if s.epoch() != epoch else Run(act)
first_constructible(s, specs) = construct(s, spec) for the first spec where it is an Activity
```

Every return passes through `settle` or the final check, so it is either an activity constructed and checked under the current epoch or `Reobserve`; a state change while deciding, generating or asking always leads back to a fresh observation. A refusal never re-selects the refused kind, whether it came from the proposal, the alternative or the default. `stop` raises at every `checkpoint`, at every level including 10; a `skip` is taken once. The Brain receives `autonomy` in the observation and words its proposal for it; whether the learner is asked is the harness's decision.

## 3. Activities, construction and the menu

### 3.1 Activities

Every wait inside an activity is bounded by `min(step timeout, s.deadline − now)` (§1) — text mode included. At the deadline `checkpoint` raises, the activity row finishes with `time_up_session`, and the session wraps. **Statuses every kind can end in:** `completed`, `stopped`, `lease_lost`, `listener_lost_no_console`, `time_up_session`, `aborted_stale` (the epoch changed before its first step), `store_busy` (a write still got `SQLITE_BUSY` after one retry). **Kind-specific**, in the table's last column. **`skip`**: in `review_anki`, `read_aloud`, `teach_items`, `quiz` it skips the current card, sentence, item or question (the last one → `completed`); in `read_listen` it completes the current sentence (ADR-0013 → Control precedence); in `practise_errors` it settles the current candidate `unsure(skipped)`; in `learner_questions`, `break` and `add_cards` it ends the activity with `skipped`.

| Activity | Params | Inside (harness) | Kind-specific statuses (besides the common ones) |
|---|---|---|---|
| `review_anki` | `max_cards` ≤ min(due, 20) | ADR-0004 review loop | skipped, idle_session |
| `read_listen` | `page: current\|next`, range `rest\|{from, to}` | acquires the page when `next` (ask to turn / Eye / `/page N`; ADR-0010 identity) and **then** resolves the range against the acquired page read; ADR-0013 alignment and sentence completion; speech only as §6.1 | page_turned, skipped, idle_session |
| `read_aloud` | page, range, `translate: none\|all\|hard`, `hard_sentence_ids` | Kokoro reads with highlighting on Faces; translation lines after a sentence when asked | skipped |
| `practise_errors` | `candidate_ids` (open, owned by the open cycle, within the ledger) | ADR-0013 → Practice per candidate on its own `page_read` state | page_turned, skipped |
| `teach_items` | `items: [{item_id, method, explanation, prompt, expect}]`, `expect ∈ {item_said, item_used, cloze_word}` | says the explanation and the prompt; scores the answer: `item_said` = the retry test of ADR-0013 → Practice on the whole answer; `cloze_word` = the answer is the cloze word (`sim ≥ 0.80`); `item_used` = one Brain call, purpose `judge` (§5.1), asks whether the answer uses the item correctly (`yes` / `no` / `cannot_tell`). Silence, `skip`, `cannot_tell` or no eligible `judge` backend → outcome `unavailable`, which writes **no** retrieval event. In voice mode an ASR disagreement on `item_said` or `cloze_word` is also `unavailable` (owner decision 6; as ADR-0013 makes a disagreement only `unsure`): `fail` needs a typed answer, a `judge` `no`, or acoustic evidence. `success` / `fail` write `retrieval_events` and an encounter (§8.6) | skipped |
| `quiz` | `questions: [{text, answers (keyword sets), item_ids}]` ≤ the ledger | ADR-0013 → CHECK outcomes per question | skipped, idle_session |
| `learner_questions` | `max_turns` ≤ 5 | the learner asks; each answer is one Brain call, purpose `answer` (§5.1), on an eligible backend (ADR-0018 §2); "no more", 20 s idle or `max_turns` ends it | skipped, idle_session |
| `add_cards` | `cards: [{item_id, front, back, sentence}]` | card checks (§7.2) → `anki_outbox` | skipped |
| `break` | `seconds` ≤ 120 | silence, a Face timer | skipped |
| `end` | `say` | — | — |

### 3.2 Menu

```
allowed(s) -> set[kind]:
  if s.ledger.minutes >= limits.session_max_min: return {"end"}
  m = {"end", "break"}
  gen = s.ledger.brain_calls_left > 0 and routable(s, purpose = "generate")   # §5.1
  if anki_reachable and s.anki_due > 0 and s.ledger.reviews_done < goals.reviews: m += {"review_anki"}
  if s.book and (s.unread_range(current) or s.can_acquire_next_page):        m += {"read_listen", "read_aloud"}
  if s.cycle:
    if s.cycle.open_candidates and s.ledger.cycle_errors_left > 0:            m += {"practise_errors"}
    if s.cycle.new_item_candidates and s.ledger.cycle_new_left > 0 and gen:  m += {"teach_items"}
    if s.cycle.read_sentences and s.ledger.cycle_quiz_left > 0 and gen:      m += {"quiz"}
    if s.cycle.read_sentences and routable(s, purpose = "answer"):           m += {"learner_questions"}
    if s.cycle.cardable_items and s.ledger.cards_left > 0:                   m += {"add_cards"}
    if s.cycle.boundary_activities >= limits.activities_per_cycle:           # continuations do not count
      m = m ∩ {"read_listen", "read_aloud", "end"}
  return m
```

`cardable_items` are practised or taught items that have, or can get, card text: a stored explanation and context sentence, or `gen`.

### 3.3 Construction and validation

`construct(s, spec) -> Activity | Rejected(reason)` builds a runnable activity from a Brain activity object, a learner's choice (`learner_spec`) or `default_spec`, validated against the **current** state:

1. `kind ∈ allowed(s)`.
2. Params that need generated text and are absent (a learner chose `quiz`, `teach_items`, or `add_cards` without stored text) are generated now by one Brain call with purpose `generate` (§5.1) and its kind's schema; failure → `Rejected("not available now")`.
3. Ids: `page: current` ranges belong to the current page read, ordered and non-empty; `page: next` carries no sentence ids (resolved after acquisition, §3.1); candidate ids open, owned by the open cycle, deduplicated; item ids exist for this learner.
4. Counts ≤ the ledger's **remaining** budgets (cumulative per cycle and session); text lengths; no URLs.

`default_spec(s, menu)`: the first of `review_anki` (first boundary only) → `practise_errors` (top candidates by Difficulty weight) → `add_cards` (cardable items with stored text) → `read_listen` (`page: current, range: rest` while unread sentences remain, else `page: next`) → `end`. It never needs the Brain. It is also the evaluation baseline (§9).

## 4. Observation

Built by `study/observe.py`; ADR-0018's egress filter removes local-only fields at send time. Plain-text sections (research A4):

- `epoch`; `session`: elapsed and limit minutes, ledger remainders, goals and progress, `autonomy`.
- `page`: book, printed page, sentences with ids of the current page read; the unread range.
- `last_activity`: id, kind, status, duration, per-item results (expected word; category substituted / omitted / hesitated / self-corrected / supplied / practised-matched / practised-unsure); heard words only when ADR-0018 allows them.
- `cycle`: id, open candidates (id, expected word, Difficulty weight, ASR confidence band), new-item candidates (id, kind word / phrase / pattern / grammar, level band, status), cardable items.
- `memory`: recent difficulties (14 days), familiar books, stories and topics (`book_notes`), `learner_notes`, each with its provenance (ADR-0018 §3).
- `menu`: allowed kinds, the default spec, the policy text (§6.3).

## 5. Decision and the Brain

A `decide` call returns one structured output, one schema for the whole session (`output_config.format`): `activity` (an `anyOf` of one object per kind, `kind` as a `const`), `alternative` (optional activity object), `say_before` (≤ 300 chars), `note` (≤ 200 chars, logs), `records` (optional, §7.1), `epoch` (echoed). Each `generate` kind has its own fixed schema. Schemas, effort and thinking stay constant within a session per (purpose, tier) so the caches stay warm (research R2–R3).

```
brain_call(s, purpose, payload, schema) -> Result | None:     # never raises except Terminal
  deadline = min(now + TOTAL_S[purpose], s.deadline)            # decide 5 s, generate 8 s, answer 10 s, judge 4 s, word 2 s
  for tier in route(purpose, difficulty(s, purpose, payload)):  # §5.1: the full chain of tiers, strongest preference first
    if not s.ledger.can_afford(tier): continue                   # an unaffordable tier is skipped, not fatal
    for b in eligible(tier, purpose, s.learner):                 # ADR-0018 §2 (locality by endpoint, cloud.text)
      if now >= deadline: return None
      if not s.ledger.reserve_brain_call(tier): break            # budget went in this tier → try a cheaper one
      r = b.call(payload, schema, timeout = min(PER_CALL_S[purpose], deadline − now))  # via egress (ADR-0018 §2: one retry owner)
      checkpoint(s)
      if r is None: continue                                     # timeout, network, refusal, max_tokens, error
      ok, reason = check_shape(r, payload)                       # schema, kind ∈ menu, ids ∈ payload, epoch
      if ok: return r
      payload = payload.with_rejection(reason); break            # an invalid answer escalates to the next tier
  return None
brain_decide(s, obs) = brain_call(s, "decide", obs, DECIDE_SCHEMA)
```

A filler line (static phrase, through the listening gate) is due when a `decide` or `generate` call has not returned after 0.8 s; on a Mouth with a slow start (the camera) it is prepared and pushed at the call's start and only made audible at 0.8 s, or replaced by text on Faces when the Mouth cannot meet that (§5.2). `check_shape` is the cheap check against the payload; `construct` (§3.3) is the binding check against the current state.

### 5.1 Routing by task type and difficulty (owner request, 2026-10-21)

Purposes (task types): `decide` (the next activity), `generate` (questions, teaching items, card text, translations of hard sentences), `answer` (the learner's own questions), `judge` (whether a learner's answer uses an item correctly), `word` (short coach lines, a one-word gloss). `judge` and `answer` carry learner text and follow ADR-0018's eligibility. The harness computes `difficulty(s, purpose, payload) ∈ {low, normal, high}` from local signals only: item kind `grammar` or `pattern` → high; a learner question of more than 12 words, or a why/how question → high; a translation of a sentence over 20 words → high; a retry after an invalid answer → one step up; a `word` line or a gloss → low; otherwise normal.

`BRAIN_TIERS` maps tiers to ordered backend:model lists (any of `claude`, `magpie` with `provider/model`, `ollama`, `mock`); `BRAIN_ROUTES` maps (purpose, difficulty) to a **preferred tier and an escalation tier**. `route()` returns the full chain: preferred → escalation → every other configured tier, strongest first, then weaker ones marked `degraded`. So a route is never empty while any backend is eligible, and an invalid answer always has a next tier unless the chain is exhausted. Defaults:

| purpose \ difficulty | low | normal | high |
|---|---|---|---|
| `decide` | standard → deep | standard → deep | standard → deep |
| `generate` | fast → standard | standard → deep | deep → standard |
| `answer` | fast → standard | standard → deep | deep → standard |
| `judge` | fast → standard | fast → standard | standard → deep |
| `word` | fast → standard | fast → standard | standard → fast |

A `degraded` result is used and recorded as such (an `answer` from a weaker tier than preferred is prefaced "here is a short answer"); an exhausted chain returns `None`: the generated activity is rejected at construction, a learner question gets "I can't answer that one right now — let's ask a grown-up later" and is listed in the parent's export, and `routable(s, purpose)` (the menu test) is true when at least one eligible backend exists for that purpose.

Default tiers: `fast` = a local Ollama model if configured, else the cheapest configured cloud model; `standard` = a mid model (e.g. Claude Sonnet, or a magpie `provider/model`); `deep` = the strongest configured (e.g. Claude Opus). The ledger charges each call by tier (`fast` 0.25, `standard` 1, `deep` 3 of `brain_calls_per_session`) and records tokens and an estimated cost per call. A tier with no eligible backend is skipped. Routing tables are per-learner settings with these defaults; §9 compares tiers.

### 5.2 Budgets for what the learner perceives

One budget per moment the learner perceives, each with the stages on its path and the deadline after which the default runs (code-plan-review K3.1). Stage values are **measured** p50/p95 per Mouth before the design relies on them (AGENTS.md → Verification); the camera's push-to-audible of 2.7–3.3 s (`docs/hardware/`) already exceeds what a PC speaker needs.

| Moment | Stages | Budget (PC Mouth / camera Mouth) | Past the budget |
|---|---|---|---|
| Leafi reacts after the learner stops (any sign) | VAD end → decision started → filler or Face text | 1.0 s / Face text at 1.0 s, audible filler when the camera can | Face text "…" |
| The next activity's first word | `decide` (`PER_CALL_S` 3 s, `TOTAL_S` 5 s) + `generate` if needed (4 s / 8 s) + TTS + Mouth start | 6 s / 9 s | `default_spec`, announced |
| Feedback on an answer | `judge` (2 s / 4 s) or local scoring + TTS + Mouth start | 3 s / 6 s | outcome `unavailable`, neutral line |
| An answer to a learner's question | `answer` (5 s / 10 s) + TTS + Mouth start | 8 s / 12 s | "let's ask a grown-up later" |

`PER_CALL_S`: decide 3, generate 4, answer 5, judge 2, word 1.5 (seconds; settings). A `standard → deep` escalation only runs when the remaining `TOTAL_S` still covers the deep tier's `PER_CALL_S`.

## 6. Settings and policy (per learner; defaults from research §6)

### 6.1 Speech inside `read_listen`

| `reading.interrupt` | silence ≥ `silence_backchannel_s` (3) | silence ≥ + `silence_prompt_s` (3) | sentence end | page end |
|---|---|---|---|---|
| `never` | nothing | nothing | nothing | `reading.encourage` line (≤ 1) |
| `stuck_only` (default) | soft non-verbal cue on Mouths, "…" on Faces | "Want a hint?"; on yes Leafi says the word, the token is marked `supplied` | nothing | `reading.encourage` line (≤ 1) |
| `sentence_end` | as `stuck_only` | as `stuck_only` | an encourage line when the sentence had a self-correction | as above |

**Recovery dialogue is outside this table** and always allowed, because without it reading cannot continue: the Reposition prompt (ADR-0013), "I can't see the page", listener lost, page uncertain, lease or device messages. `reading.encourage`: `none` | `specific` (default; names a self-correction or effort, never "smart") | `frequent`. A `supplied` token becomes a candidate with `heard = null`, reason `supplied`.

### 6.2 Items and what is new

`knowledge_items` are per learner (ADR-0018 §1) and gain the status `ignored`. New = no row for this learner, or `new`. Rank: not known or ignored for this learner; one-unknown sentences first; level band above the learner's (Cambridge YLE wordlists, SUBTLEX-UK children's frequency as the prior); then frequency.

**Authority over status.** An item with an Anki card follows Anki only (interval ≥ `REVIEW_KNOWN_INTERVAL_DAYS` → known, lapse → lapsed). An item without a card moves `new → learning` on its first `teach_items` outcome and `learning → known` only when `retrieval_events` hold ≥ 2 successes on different days; `* → ignored` by the Brain or the parent. The Brain's `item_status` record is a request granted only under these rules.

### 6.3 Practice policy and the ledger

Defaults: `practice.max_errors` 5 per cycle; `practice.max_new` 3 per cycle, 8 per session; `quiz.max_questions` 4 per cycle; `cards.max` 10 per session; `limits.session_max_min` 20 (hard ceiling 30, not settable above); `limits.activities_per_cycle` 6 (boundary activities); `limits.brain_calls_per_session` 40 (tier-weighted, §5.1); `goals`: composable (`reviews: due`, `new_items: N`, `pages: N`). The **ledger** holds the cumulative counters per session and per open cycle; `allowed`, `construct` and the activities read it; only activity start and finish and the reservation calls write it. The policy text sent to the Brain states the defaults, the no-correction-while-reading rule, the praise rules and the autonomy level; enforcement never depends on the text.

## 7. Records

### 7.1 What the Brain may write (`records` in a decision)

`assessment` (≤ 500 chars about `last_activity.id`), `learner_note` (durable, visible and editable by the parent; it must cite the activity ids it rests on and is shown as the Brain's interpretation; a note whose cited activities are more than 10 sessions old with no newer citing note drops out of `memory`), `item_status` (a request, §6.2), `book_note` (topic, characters, a one-line story summary for reuse). `apply_records` validates each record on its own (ids exist, `assessment` names the last activity, epoch unchanged) and writes the valid ones in one transaction before the next activity; an invalid record is dropped and logged and never affects the decision. Records of a terminal decision are applied before the loop exits.

### 7.2 What the harness records itself

- `cycles`: id, session_id, status (`open` / `closed`), opened_by_activity, closed_reason, opened_at, closed_at.
- `activities`: id, session_id, cycle_id, kind, continuation (bool), params (json), decided_by (`brain` / `default` / `learner`), autonomy, epoch (json), status (`running` → a final status), started_at, ended_at, outcome (json, with the default spec computed alongside, §9), assessment?
- `brain_calls`: id, session_id, activity_id?, purpose, difficulty, tier, backend, endpoint host, model, effective provider and model when reported, prompt_version (hash of policy text and schema), payload as sent after the egress filter, response (json), latency_ms, tokens in / out / cached, estimated cost, outcome (`ok` / `timeout` / `refusal` / `invalid:<reason>` / `error`), created_at.
- `retrieval_events`: id, learner_id, item_id, activity_id, day, outcome (`success` / `fail`), evidence (`typed` / `heard` / `acoustic`).
- `learner_notes`, `book_notes`: id, learner_id, book_id?, text, provenance (ADR-0018 §3), source (`brain` / `parent`), created_at, edited_at?
- **One path into Anki.** `add_cards` is the only writer of `anki_outbox`; `knowledge.upsert_item` stops queueing a card for every new item (today it does, for the explain, check and miscue paths). **One owner of item status**: `item_status.apply(event)` performs every transition of §6.2; "has an Anki card" means `anki_outbox.anki_note_id` is set (acknowledged by AnkiConnect).
- Card checks before `anki_outbox`: the item occurs in the sentence; at most one item unknown to this learner in it; back ≤ 200 chars; no duplicate for this learner by lemma. `ANKI_PREVIEW=parent` (default) queues cards for the parent's approval in the web UI; `auto` sends them.

Activity effects and the `activities` / ledger update are one transaction at each step that changes miscues or items, so a crash leaves either the step or nothing. A write that gets `SQLITE_BUSY` (another process holds the lock past `busy_timeout`) is retried once; a second failure ends the activity with `store_busy` and the loop re-observes.

## 8. What remains of ADR-0013 and what changes

Kept as written: `align` rules 1–8, Reposition (its prompt is recovery dialogue, §6.1), Sentence completion (i)–(iii) and its token updates, Practice (run by `practise_errors`), `/back N` (inside `read_listen`), Correction interaction, CHECK outcomes (run by `quiz`), the Async guard (extended in §1).

1. **Candidate lifecycle.** Sentence completion no longer runs PRACTICE. A candidate is owned by the cycle whose `read_listen` created it and stays `candidate` across sentences and pages; its token state stays in its own `page_reads.reading_state`. `/back` reopening its sentence leaves it `candidate`; a later match withdraws it as `reread` while the cycle is open. **Closing a cycle** settles every candidate it still owns: `unsure(not_practised)`, or `unsure(skipped)` on `stop`; token → `settled` in its page read's state.
2. **Page turn / `next page`** during `read_listen` completes the current sentence by (iii) and ends the activity with `page_turned`, without settlement. When the learner keeps reading, the harness starts a **continuation** — a `read_listen` on the new page, `continuation = true`, in the same cycle, no Brain call — and does so again on every further turn (the inner loop of §2); continuations count toward session minutes, not toward `activities_per_cycle`. When the learner does not keep reading, the next boundary decides. A page turn during `practise_errors` ends it with `page_turned`; candidates not yet practised stay owned by the cycle.
3. "After PRACTICE ends" and "Page completion → CHECK" are replaced by the menu.
4. The per-sentence line (`sentence_done`) is removed; Leafi speaks inside reading only as §6.1 allows.
5. **Interrupted session** (kept, extended): on startup a stale session's `running` activity becomes `interrupted`, its open cycle closes with reason `interrupted`, its candidates become `unsure(interrupted)`; "continue from page N?" uses the last page read of that learner and book.
6. **Difficulties (amended).** `unsure` reasons `not_practised` and `skipped` are not evidence about the word: they contribute `v(s) = 0` **and do not count** toward the "unsure evidence in ≥ 3 distinct sessions" existence rule. Knowledge items: `teach_items` writes an encounter with trigger `teach`, and `teach(incorrect)` for a failed recall, counted like `check(incorrect)`; a `quiz` question writes encounters only for its `item_ids`. `confirmed` still needs acoustic evidence.

Alignment v2 (research D5) is a separate ADR after a prototype on recorded readings; until then `align` stays as ADR-0013 rules 1–8.

**One owner for the reading rules.** AGENTS.md names ADR-0013 the single owner of the reading algorithm, so this section must not stay a second copy. In the change that accepts this ADR: ADR-0013 gets a v2 section (or a successor ADR that the AGENTS.md line then names) holding §8.1–8.6 **as pseudocode** — `read_listen`, `practise_errors`, `close_cycle`, continuation — hand-run on A→B→C page turns with three candidates, `/back` across a page turn, and `stop` mid-practice, the traces kept as the first tests; the replaced ADR-0013 paragraphs are marked where they stand; this section then shrinks to a link. No code for §8 is written before that.

## 9. Evaluation before trust

For every Brain decision the harness also computes `default_spec` and stores it in `activities.outcome.default`. A replay set of recorded observations (`data/evals/decisions/`, local) compares models, prompts, backends and tiers offline; the parent's session export shows where the Brain departed from the default and what followed, with cost per tier. The Brain stays primary only while the parent judges its sessions at least as good as the default (two studies favour code-chosen moves, research §2).

## 10. What changes where (inventory for the implementation)

**Existing modules** (reuse / extend / replace): `coach.AsyncGuard` → extended into the epoch (§1); `controls.parse` → reused as the control parser feeding the latch; `phrases` → reused for filler, recovery and closing lines; `knowledge.card_fields` → reused beside generated card text; `knowledge.upsert_item` → no longer queues Anki (§7.2); `anki._update_status` → moved into `item_status.apply`; `records.export_session` → extended with activities, Brain departures from the default and `deliver` outcomes; the `.env` settings manifest (`core/envschema.py`, `envedit.py`, `agent.webui`) → extended with per-learner keys in a **Learners tab** (ADR-0018 §1) so one page edits both; `services/brain/claude.py`'s retry loop and `BRAIN_DEADLINE_S` → removed (ADR-0018 §2); `session.py`'s state machine → replaced by §2's loop.

**Documents changed with acceptance** (one truth each): `flows/reading-session.md` redrawn around activities and cycles; `product.md` B4 ("at a sentence end") and B7 (answers judged locally → by setting); `GLOSSARY.md` new terms (study harness, activity, cycle, epoch, menu, ledger, autonomy, tier, continuation) and Practice redefined; `data-model.md` the new tables of §7.2; ADR-0013 as above; `security.md`'s prompt-safety action allow-list → the activity kinds of §3.1.

**The owner's console** (`scil/Leafi/`): buttons for the decision-replay evaluation (§9), the per-learner session export, and the routing / tier settings; help lines for the changed `study` command.

## Consequences

- The session's flow moves from code into a menu plus a decision; the harness grows (observation, menu, construction, ledger, routing, records) while the prompts hold the pedagogy.
- Sessions without a Brain still run on the default policy; generated activities are then absent, not broken.
- Cost follows the task: short lines on a fast local model, hard questions on the strongest one.
- ADR-0013 keeps the reading algorithm with the changes in §8; `flows/reading-session.md` is redrawn around activities and cycles.

## Confirmation

`tests/test_session_menu.py` (`allowed` per state and ledger; the activities-per-cycle cut ignores continuations; no generate route → no generated kinds), `tests/test_construct.py` (reversed range rejected → next spec; `page: next` constructs without ids; a learner's `quiz` generates its questions or is rejected), `tests/test_negotiate.py` (autonomy 2 out-of-menu then `stop` raises; autonomy 10 `/stop` during the announcement ends the session; refusal → alternative → default → `end`; a page turn while a learner-chosen `quiz` generates → `Reobserve`; a rejected proposal is never announced), `tests/test_controls.py` (one `skip` is taken once; `stop` then `skip` stays `stop`; a skip while listening in negotiation is consumed there and does not cause `Reobserve`; the deadline sets `time_up_session` during a Brain call and during negotiation; `/stop` during identification finalizes a guest session), `tests/test_negotiate_freshness.py` (a change injected at every await of `negotiate` — during initial construction, generation inside a named choice, the refusal fallback, the announcement — yields `Reobserve`; a skip injected at the same awaits is consumed by `negotiate` and never reaches the activity; "no" to an announced alternative never re-selects its kind), `tests/test_finalize.py` (`/stop` before identification completes leaves only the counts row on `anonymous`; after `lease_lost` no closing line plays; the lease is released when `deliver` fails), `tests/test_default_policy.py`, `tests/test_brain_call.py` (two timeouts → `None` within the total; invalid → escalates one tier; exception → next backend; tier-weighted budget; with 0.5 units left a `standard`-preferred call falls through to `fast`), `tests/test_routing.py` (difficulty signals; a high-difficulty question with only `fast` configured is answered `degraded`; no eligible backend → the "ask a grown-up" line; `cloud.text` off removes cloud backends for `answer` and `judge`), `tests/test_teach_scoring.py` ("I don't know what through means" is not a success; silence → `unavailable`, no retrieval event), `tests/test_cycle_candidates.py` (A→B→C turns while reading keep A's three candidates practisable; a boundary `read_listen` settles them `not_practised`; `stop` settles `skipped`; `/back` withdraws as `reread`), `tests/test_epoch.py`, `tests/test_deadline.py` (a text-mode retry at 29:59 ends at 30:00), `tests/test_reading_settings.py` (each `reading.interrupt` value: exactly §6.1's lines; Reposition still asks under `never`), `tests/test_item_status.py` (every transition through `item_status.apply`; a voice disagreement in `teach_items` writes no `fail`), `tests/test_activity_status.py` (each kind ends only in the statuses §3.1 lists; `skip` per kind), `tests/test_settings_reload.py` (a parent change to `reading.interrupt` mid-session takes effect at the next checkpoint), `tests/test_anki_single_path.py` (an explain, check or miscue item creates no `anki_outbox` row; only `add_cards` does), `tests/test_negotiate_silence.py` (at autonomy 2 silence re-asks once, then the proposal stands; a lost listener in negotiation is terminal without a console), `tests/test_difficulties.py` (three sessions of `not_practised` create no row), and a replay of `cache/voice-diag.wav` through a mock-Brain session asserting no line inside reading with `interrupt=never`.
