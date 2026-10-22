---
status: proposed
date: 2026-10-21
revised: 2026-10-22 (v3: the owner's decisions of 2026-10-22 — a configurable default policy whose steps can each be owned by code or the Brain, evaluation by an exploration share, configurable mastery, parent features deferred; the second code-plan-review pass; the domain prior-art map; the harness-libraries research). Earlier: code-plan-review pass 1 and codex design reviews 1–6 (see Reviews).
supersedes: 0013 (session rules only, see §8)
amends: 0003, 0013 (Difficulties and Reposition speech: §8.6, §6.1)
---

# The Brain leads the study session; the study harness executes, measures and limits it

Inputs: the requirements and decisions in [`../research/2026-10-21-ai-led-study.md`](../research/2026-10-21-ai-led-study.md) §1; the provenance of every domain mechanism in [`../research/2026-10-22-domain-prior-art.md`](../research/2026-10-22-domain-prior-art.md) (this ADR applies its recommended column for §2 except where a line below says otherwise); the generic machinery in [`../research/2026-10-22-harness-libraries.md`](../research/2026-10-22-harness-libraries.md). Learners, recognition, egress, consent and the parent features deferred: ADR-0018.

## 1. Decision and terms

A study session is a sequence of **activities**. At every activity boundary a **sequencer** picks the next activity from a **menu** the **study harness** computes; the harness constructs, validates, runs, times, limits and records it. No correction happens inside a reading activity; errors found while reading are practised afterwards (owner requirement 2.2a; Reading Coach and Project LISTEN, prior-art §2).

- *Study harness*: the code around the Brain — observation, menu, construction, execution and timing, the ledger, records, routing, egress (ADR-0018), fallback. After Anthropic's "agent harness". Glossary term.
- *Sequencer*: who picks the next activity. `policy.sequencer = brain` (default): the Brain decides, except on the exploration share (§9); `= default`: the configured **default policy** (§3.3) decides and the Brain is never asked to sequence.
- *Content owner*: per activity kind, who fills its parameters and text. `policy.content.<kind> = code | brain` (owner decision 2026-10-22). `code` builds them from stored data (§3.3 `default_params`); `brain` asks the Brain (purpose `generate`). Kinds whose content only a model can write (`teach_items` explanations, `quiz` questions, `learner_questions` answers) have no `code` option and are absent from the menu without a Brain.
- *Cycle*: an `open` record started by a reading activity chosen at a boundary; it owns every candidate its `read_listen` activities create, on any page. It closes when another boundary-chosen reading activity starts, at wrap, or on `stop`; closing settles what it still owns (§8.1). Continuations (§2) stay in it.
- *Epoch*: `(session_id, learner_id, cycle_id, page_read_id, revision_id, turn_id, learner_settings_version, household_settings_version)`. `turn_id` (ADR-0013 → Async guard) also increments on activity start and end, page turn, correction, learner confirmation, a settings change. An item built under one epoch is dropped if the epoch has changed when it would be spoken, executed or written.
- *Controls*: the console reader, the Listener's control parser and the lease watcher post control events. `s.terminal ∈ {None, stop, lease_lost, time_up_session, listener_lost_no_console}` is **monotonic**: the first terminal wins. `skip` events go into a queue consumed exactly once by `take_skip(s)`; a skip posted while no activity runs belongs to the current negotiation and does not change the epoch (inside an activity it increments `turn_id` as ADR-0013 says). `checkpoint(s)` runs after every await: it sets `time_up_session` at `s.deadline`; it reads both settings versions (one indexed read each) and on a change reloads settings and ledger limits and bumps the epoch; it raises `Terminal` when `s.terminal` is set. A `ListenerLost` from any listen sets `listener_lost_no_console` when there is no console, else switches the session to text mode and bumps the epoch (identification restarts in text mode, ADR-0018 §1).
- *Deadline*: one absolute `s.deadline = start + limits.session_max_min`; every wait — a Brain call, a listen, an activity step — is bounded by `min(its own timeout, s.deadline − now)`. **Implementation (adopted):** an `anyio` `CancelScope` with that deadline around the session, a second scope per Brain call, and the latch cancelling the session scope; blocking work in threads (ASR, TTS) gets a cooperative stop flag, because threads cannot be cancelled (libraries §2, findings 3–4). `checkpoint` remains the place the latch and settings are read.

## 2. The session loop (pseudocode is the rule)

```
run_session():
  acquire_lease()                                          # ADR-0011 lease; refused → "another session is running"
  close_stale_sessions(); sweep_guests()                   # §8.5 recovery, then ADR-0018 §1 guest sweep, in this order
  s = Session(learner = new_guest())                       # ADR-0018 §1: a guest until confirmed
  try:
    s.learner = identify(s)                                # ADR-0018 §1; local TTS only; text mode on a lost Ear
    s.book = identify_book(s)
    last = None
    while True:
      checkpoint(s)
      menu = allowed(s)                                    # §3.2; always contains "end"
      obs  = observe(s, last, menu)                        # §4; obs.epoch
      prop = sequence(s, obs, menu)                        # §3.3: Brain | default policy | exploration; never raises except Terminal
      apply_records(s, prop.records if prop else [], obs)  # §7.1; epoch-checked; never blocks
      out  = negotiate(s, prop, menu, obs.epoch)           # §2.1; Run(activity) | Reobserve
      if out is Reobserve: continue
      act = out.activity
      if act.kind == "end": record_boundary(s, obs, prop, act); break
      last = run_activity(s, act)                          # §3.1; start/finish rows inside
      while last.status == "page_turned" and s.learner_kept_reading():
        last = run_activity(s, continuation(s))            # §8.2; same cycle; repeats for every turn
      if last.status in TERMINAL: break
  except Terminal: pass
  finalize(s)                                              # local, no awaits, never raises
  try: deliver(s)                                          # optional, best effort, own 10 s cap
  finally: release_lease(s)
```

`finalize(s)` runs with `checkpoint` disabled and does only local work in one transaction: close the running activity and the open cycle (§8.1), write the summary counts, set `ended_at`, and apply ADR-0018 §1's **guest end-state rule** (the one owner of what happens to a guest's record). A `SQLITE_BUSY` here leaves the session to startup recovery, which does the same work. `deliver(s)` speaks the closing line only while the speech lease is still held (never after `lease_lost`), processes the Anki outbox, and writes each step's outcome (`closing_line`, `anki_synced`: done / skipped / failed) into the summary; nothing in `deliver` can undo `finalize`. The lease is released in a `finally`.

`ActivityStatus` is one enum; §3.1's table says which kind can end in which status, and a test fails when a kind can end in a status the table omits. `TERMINAL = {stopped, lease_lost, idle_session, time_up_session, listener_lost_no_console}`; the others (`completed`, `skipped`, `page_turned`, `aborted_stale`, `store_busy`) return to the menu; `interrupted` is written only by startup recovery. An activity that sees `stop` in its own step ends with `stopped`; one that hits the latch through `checkpoint` raises `Terminal`, which `run_activity` turns into a finished row with the terminal's status before re-raising.

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
    checkpoint(s)
    if take_skip(s) or c in ("skip", "no"): return refused()
    if s.epoch() != epoch: return Reobserve
    if c == "yes": break
    if c in ("none", "unparsed"):                                            # silence is not a yes
      if s.autonomy <= 3 and turn == 1: ask("Shall we " + describe(act) + "?"); continue
      break
    if c.named in menu: return settle([learner_spec(s, c.named), act.spec])
    say(why_not(c.named))
  checkpoint(s)
  if take_skip(s): return refused()
  return Reobserve if s.epoch() != epoch else Run(act)
first_constructible(s, specs) = construct(s, spec) for the first spec where it is an Activity
```

Every return passes through `settle` or the final check, so it is either an activity constructed and checked under the current epoch or `Reobserve`. A refusal never re-selects the refused kind. `stop` raises at every `checkpoint`, at every level including 10; a `skip` is taken once. The autonomy bands are Leafi's own; they follow the levels-of-automation idea (the machine suggests / acts unless vetoed / acts and informs), prior-art §2 (*adapted*). Whether the learner is asked is the harness's decision, not the Brain's.

## 3. Activities, construction and the menu

### 3.1 Activities

Every wait inside an activity is bounded by `min(step timeout, s.deadline − now)`. **Statuses every kind can end in:** `completed`, `stopped`, `lease_lost`, `listener_lost_no_console`, `time_up_session`, `aborted_stale` (the epoch changed before its first step), `store_busy` (§7.3). **`skip`**: in `review_anki`, `read_aloud`, `teach_items`, `quiz` it skips the current card, sentence, item or question (the last one → `completed`); in `read_listen` it completes the current sentence (ADR-0013 → Control precedence); in `practise_errors` it settles the current candidate `unsure(skipped)`; in `learner_questions`, `break` and `add_cards` it ends the activity with `skipped`.

| Activity | Params | Inside (harness) | Kind-specific statuses |
|---|---|---|---|
| `review_anki` | `max_cards` ≤ min(due, 20) | ADR-0004 review loop; each answer is graded again / hard / good / easy and sent to Anki (FSRS schedules) | skipped, idle_session |
| `read_listen` | `page: current\|next\|familiar`, range `rest\|{from, to}` | acquires the page when `next` (ask to turn / Eye / `/page N`) or `familiar` (a page this learner read before, for a reread — Reading Recovery's familiar reading, prior-art §2); **then** resolves the range against the acquired page read; ADR-0013 alignment and sentence completion; speech only as §6.1 | page_turned, skipped, idle_session |
| `read_aloud` | page, range, `translate: none\|all\|hard`, `hard_sentence_ids` | Kokoro reads with highlighting on Faces; translation lines after a sentence when asked | skipped |
| `practise_errors` | `candidate_ids` (open, owned by the open cycle, within the ledger) | ADR-0013 → Practice per candidate on its own `page_read` state | page_turned, skipped |
| `teach_items` | `items: [{item_id, method, explanation, prompt, expect}]`, `expect ∈ {item_said, item_used, cloze_word}` | says the explanation and the prompt; scores the answer (§3.4) | skipped |
| `quiz` | `questions: [{text, answers (keyword sets), evidence_sentence_ids, item_ids}]` ≤ the ledger | construction rejects a question whose answers are not supported by its cited sentences (answerability, research N20; prior-art §2); ADR-0013 → CHECK outcomes per question | skipped, idle_session |
| `learner_questions` | `max_turns` ≤ 5 | the learner asks; each answer is one Brain call, purpose `answer`, on an eligible backend (ADR-0018 §2); "no more", 20 s idle or `max_turns` ends it | skipped, idle_session |
| `add_cards` | `cards: [{item_id, front, back, sentence}]` | card checks (§7.2) → `anki_outbox` | skipped |
| `break` | `seconds` ≤ 120 | silence, a Face timer | skipped |
| `end` | `say` | — | — |

### 3.2 Menu

```
allowed(s) -> set[kind]:
  if s.ledger.minutes >= limits.session_max_min: return {"end"}
  m = {"end", "break"}
  gen = s.ledger.brain_calls_left > 0 and routable(s, purpose = "generate")   # §5.1
  if anki_reachable and s.anki_due > 0 and not s.goal_met("reviews"):        m += {"review_anki"}
  if s.book and (s.unread_range(current) or s.can_acquire_next_page or s.familiar_pages): m += {"read_listen", "read_aloud"}
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

`cardable_items` are practised or taught items that have, or can get, card text: a stored explanation and context sentence, or `gen` when `policy.content.add_cards = brain`.

### 3.3 Sequencing, construction and the configurable default policy

```
sequence(s, obs, menu) -> Decision | None:
  if s.policy.sequencer == "default": return None                      # negotiate falls to default_spec
  if random() < s.policy.explore_share: s.explored = True; return None # §9: logged with its propensity
  return brain_call(s, "decide", obs, DECIDE_SCHEMA)                    # §5
```

**The default policy is a setting** (owner decision 2026-10-22): `policy.default_order`, an ordered list of steps, each `{kind, when}`, with this default:

| # | step | when |
|---|---|---|
| 1 | `review_anki` | first boundary of the session only |
| 2 | `practise_errors` | open candidates exist (top by Difficulty weight) |
| 3 | `teach_items` | new-item candidates exist and the content owner can fill it |
| 4 | `add_cards` | cardable items exist |
| 5 | `read_listen` | `page: current, range: rest` while unread sentences remain, else `page: next` |
| 6 | `end` | always |

`default_spec(s, menu)` returns the first step whose kind is in `menu` and whose `when` holds. The learner or owner may reorder, remove or add steps (from the activity kinds of §3.1, with `when` conditions from a fixed set: `first_boundary`, `has_candidates`, `has_new_items`, `has_cardable`, `unread`, `always`); an invalid order is rejected at save and the built-in default is used. Steps whose kind has `policy.content.<kind> = brain` get their parameters from a `generate` call; without a Brain such a step is skipped.

`construct(s, spec) -> Activity | Rejected(reason)` builds a runnable activity from a Brain activity object, a learner's choice (`learner_spec`) or a default step, validated against the **current** state:

1. `kind ∈ allowed(s)`.
2. Params: from the spec; absent ones from `default_params(s, kind)` when the content owner is `code`, or from one `generate` call (its kind's schema) when it is `brain`; failure → `Rejected("not available now")`.
3. Ids: `page: current` ranges belong to the current page read, ordered and non-empty; `page: next|familiar` carry no sentence ids (resolved after acquisition); candidate ids open, owned by the open cycle, deduplicated; item ids exist for this learner; quiz answerability (§3.1).
4. Counts ≤ the ledger's **remaining** budgets (cumulative per cycle and session); text lengths; no URLs.

### 3.4 Teaching scores

`item_said` = the retry test of ADR-0013 → Practice on the whole answer; `cloze_word` = the answer is the cloze word (exact, a homophone, or the same phones — the real-word rule of ADR-0013 v2, §8); `item_used` = one Brain call, purpose `judge`, with few-shot examples (`yes` / `no` / `cannot_tell`; prior-art §2: only GPT-4-class few-shot evidence exists, so `judge` runs on the `standard` tier until a labelled set of this child's answers justifies `fast`). **Outcomes:** silence, `skip`, `cannot_tell`, no eligible `judge` backend → `unavailable`, no retrieval event. In voice mode an ASR disagreement is `unavailable` (owner decision 6), and a `judge` `no` on a spoken answer is `unavailable` unless every word of the transcript has confidence ≥ `JUDGE_MIN_CONF` (0.8, *untuned*). `fail` therefore needs a typed answer, a confident spoken answer judged `no`, or acoustic evidence. `success` / `fail` write `retrieval_events` with full timestamps and an encounter (§8.6).

## 4. Observation

Built by `study/observe.py`; ADR-0018's egress filter removes local-only fields at send time. Plain-text sections (Khan Academy's finding that plain text beats JSON for history, research A4):

- `epoch`; `session`: elapsed and limit minutes, ledger remainders, goals and progress, `autonomy`.
- `page`: book, printed page, sentences with ids of the current page read; the unread range; familiar pages.
- `last_activity`: id, kind, status, duration, per-item results (expected word; category substituted / omitted / hesitated / self-corrected / supplied / practised-matched / practised-unsure); heard words only when ADR-0018 allows them.
- `cycle`: id, open candidates (id, expected word, Difficulty weight, ASR confidence band), new-item candidates (id, kind word / phrase / pattern / grammar, level band, status), cardable items.
- `memory`: recent difficulties (14 days), familiar books, stories and topics (`book_notes`), `learner_notes` that are still current (§7.1).
- `menu`: allowed kinds, the default spec, the policy text (§6.3).

## 5. Decision and the Brain

A `decide` call returns one structured output, one schema for the whole session: `activity` (an `anyOf` of one object per kind, `kind` as a `const`), `alternative` (optional activity object), `say_before` (≤ 300 chars), `rationale` with Bridge's three slots — `evidence` (what in the observation), `strategy`, `intention` (each ≤ 150 chars; prior-art §2, *adopted* from Bridge) — `records` (optional, §7.1), `epoch` (echoed). Each `generate` kind has its own fixed schema. Schemas, effort and thinking stay constant within a session per (purpose, tier). Typed outputs are Pydantic models validated by the harness; whether a library (PydanticAI's `Agent(output_type)` with `FallbackModel`) replaces the hand-written call and fallback is decided by the prototype of libraries §7 (exit criterion there).

```
brain_call(s, purpose, payload, schema, moment_deadline = None) -> Result | None:   # never raises except Terminal
  deadline = min(now + TOTAL_S[purpose], moment_deadline or ∞, s.deadline)  # §5.2: the perceived moment caps the call
  for tier in route(purpose, difficulty(s, purpose, payload)):    # §5.1: the full chain
    if not s.ledger.can_afford(tier): continue
    for b in eligible(tier, purpose, s.learner):                   # ADR-0018 §2: locality by LOCAL_MODELS, cloud.text
      if now >= deadline: return None
      if not s.ledger.can_afford(tier): break
      r, attempts = b.call(payload, schema, timeout = min(PER_CALL_S[purpose], deadline − now))  # via egress
      s.ledger.charge(tier, attempts)                              # egress reports transmitted attempts (ADR-0018 §2)
      checkpoint(s)
      if r is None: continue
      ok, reason = check_shape(r, payload)
      if ok: return r
      payload = payload.with_rejection(reason); break
  return None
```

A filler line (static phrase, through the listening gate) is due when a `decide` or `generate` call has not returned after 0.8 s; on a slow-start Mouth (the camera) it is pushed at the call's start and made audible at 0.8 s, or replaced by Face text (§5.2). Retries: the SDKs are built with `max_retries=0` and a per-request timeout; `egress` owns transport retry (one, with `tenacity` waits, inside the call's deadline); `brain_call` owns escalation (libraries §3, finding 2).

### 5.1 Routing by task type and difficulty (owner request, 2026-10-21)

Purposes: `decide`, `generate` (questions, teaching items, card text, translations), `answer` (the learner's own questions), `judge`, `word` (short coach lines, a gloss). `judge` and `answer` carry learner text and follow ADR-0018's eligibility. `difficulty(s, purpose, payload) ∈ {low, normal, high}` from local signals: item kind `grammar` or `pattern` → high; a learner question over 12 words, or why/how → high; a translation of a sentence over 20 words → high; a retry after an invalid answer → one step up; a `word` line → low; else normal.

`BRAIN_TIERS` maps tiers to ordered backend:model lists (`claude`, `magpie` with `provider/model`, `ollama`, `mock`); `BRAIN_ROUTES` maps (purpose, difficulty) to a preferred and an escalation tier; `route()` returns preferred → escalation → every other configured tier, strongest first, then weaker ones marked `degraded`. Defaults:

| purpose \ difficulty | low | normal | high |
|---|---|---|---|
| `decide` | standard → deep | standard → deep | standard → deep |
| `generate` | fast → standard | standard → deep | deep → standard |
| `answer` | fast → standard | standard → deep | deep → standard |
| `judge` | standard → deep | standard → deep | standard → deep |
| `word` | fast → standard | fast → standard | standard → fast |

A `degraded` answer is prefaced "here is a short answer"; an exhausted chain returns `None` (a generated activity is rejected at construction; a learner question gets "I can't answer that one right now"). `routable(s, purpose)` is true when an eligible backend exists. Tiers: `standard` = a mid model (e.g. Claude Sonnet or a magpie `provider/model`); `deep` = the strongest configured; `fast` = per ADR-0018 §2 (a local Ollama model only once its measurement is recorded, else the cheapest cloud model). The ledger charges `fast` 0.25, `standard` 1, `deep` 3 per transmitted attempt against `brain_calls_per_session`, and records tokens and estimated cost. Routing tables are per-learner settings.

### 5.2 Budgets for what the learner perceives

Stage values are measured p50/p95 per Mouth before the design relies on them (AGENTS.md → Verification); the camera's push-to-audible of 2.7–3.3 s already exceeds what a PC speaker needs. Each moment's deadline is passed into `brain_call` and construction, so the budget is what stops the work.

| Moment | Stages | Budget (PC Mouth / camera Mouth) | Past the budget |
|---|---|---|---|
| Leafi reacts after the learner stops | VAD end → decision started → filler or Face text | 1.0 s / Face text at 1.0 s | Face text "…" |
| The next activity's first word | `decide` + `generate` if needed + TTS + Mouth start | 6 s / 9 s | the default policy's next step, announced |
| Feedback on an answer | `judge` or local scoring + TTS + Mouth start | 3 s / 6 s | `unavailable`, neutral line |
| An answer to a learner's question | `answer` + TTS + Mouth start | 8 s / 12 s | "I can't answer that one right now" |

`PER_CALL_S` (settings, *untuned*): decide 3, generate 4, answer 5, judge 2, word 1.5. `TOTAL_S`: decide 5, generate 8, answer 10, judge 4, word 2.

## 6. Settings and policy (per learner unless marked household)

Every default below is a starting value; those marked *untuned* have no measured or published basis yet (prior-art §2 lists them).

### 6.1 Speech inside `read_listen`

| `reading.interrupt` | silence ≥ `silence_backchannel_s` (3) | silence ≥ + `silence_prompt_s` (3) | sentence end | page end |
|---|---|---|---|---|
| `never` | nothing | nothing | nothing | `reading.encourage` line (≤ 1) |
| `stuck_only` (default) | soft non-verbal cue on Mouths, "…" on Faces | "Want a hint?"; on yes Leafi says the word, the token is marked `supplied` | nothing | `reading.encourage` line (≤ 1) |
| `sentence_end` | as `stuck_only` | as `stuck_only` | an encourage line when the sentence had a self-correction | as above |

The silence thresholds follow Project LISTEN's 2 s + 2 s and Reading Assistant's ≥ 3 s (*adapted*). **Recovery dialogue is outside this table** and always allowed: the Reposition prompt (ADR-0013), "I can't see the page", listener lost, page uncertain, lease or device messages. `reading.encourage`: `none` | `specific` (default; names a self-correction or effort, never "smart") | `frequent`. A `supplied` token becomes a candidate with `heard = null`, reason `supplied` — a told word is an error in running-record convention (prior-art §1).

### 6.2 Items, what is new, and mastery

`knowledge_items` are per learner (ADR-0018 §1) and gain the status `ignored`. New = no row for this learner, or `new`. Rank: not known or ignored; one-unknown sentences first (AnkiMorphs, *adopted*); level band above the learner's (Cambridge YLE wordlists, SUBTLEX-UK children's frequency as the prior); then frequency.

**Mastery is configurable** (owner decision 2026-10-22), `mastery.mode`:
- `retrievals` (default): `learning → known` when `retrieval_events` hold ≥ `mastery.min_retrievals` (6) successes over ≥ `mastery.min_days` (3) distinct days (research P14; the earlier "2 on different days" is withdrawn).
- `anki`: each cycle's cardable items become cards (`add_cards`); later sessions review them (`review_anki`, graded again / hard / good / easy); FSRS schedules; `known` when the card's interval ≥ `REVIEW_KNOWN_INTERVAL_DAYS`, `lapsed` on a lapse.

In both modes an item that has an acknowledged Anki card follows Anki's state (`anki_outbox.anki_note_id` set). `* → ignored` by the Brain's request or the learner. `item_status.apply(event)` is the only code that changes status. Retrieval events keep full timestamps so a half-life or FSRS model can be fitted later.

### 6.3 Practice policy, goals and the ledger

Defaults: `practice.max_errors` 5 per cycle (Reading Coach's five); `practice.max_new` 3 per cycle, 8 per session (Text Talk); `quiz.max_questions` 4 per cycle (WWC); `cards.max` 10 per session; `limits.session_max_min` by age band — 15 for ages 6–7, else 20 — with a hard ceiling of 30 (research §6); `limits.activities_per_cycle` 6 (boundary activities, *untuned*); `limits.brain_calls_per_session` 40 (tier-weighted, *untuned*); `policy.explore_share` 0.1 (§9, *untuned*). **Goals** are composable, each with its window: `reviews: due` (per day), `new_items: N` (per day or per session), `pages: N` (per day or per session); a day is the household's local date (ADR-0018 §1). The **ledger** holds the cumulative counters per session and per open cycle; only activity start and finish and the charge calls write it. The policy text sent to the Brain states the defaults, the no-correction-while-reading rule, the praise rules and the autonomy level; enforcement never depends on the text.

## 7. Records

### 7.1 What the Brain may write (`records` in a decision)

`assessment` (≤ 500 chars about `last_activity.id`), `item_status` (a request, §6.2), `book_note` (topic, characters, a one-line story summary). **Learner notes are not written per turn**: a post-session extraction call (purpose `generate`, after `finalize`, from the session's activities) writes them (prior-art §2: memory written after the session, *adopted*), each citing the activity ids it rests on (`learner_note_citations`) and shown as the Brain's interpretation; a note whose cited activities are more than 10 sessions old with no newer citing note drops out of `memory`; `forget --session` deletes a note whose citations all point into that session. `apply_records` validates each record on its own and writes the valid ones in one transaction before the next activity; an invalid record is dropped and logged and never affects the decision.

### 7.2 What the harness records itself

- `cycles`: id, session_id, status (`open` / `closed`), opened_by_activity, closed_reason, opened_at, closed_at.
- `activities`: id, session_id, cycle_id, kind, continuation (bool), params (json), decided_by (`brain` / `default` / `explore` / `learner`), propensity (the probability the chosen sequencer had, §9), autonomy, epoch (json), status (`running` → a final status), started_at, ended_at, outcome (json, with the default spec computed alongside), assessment?
- `brain_calls`: id, session_id, activity_id?, purpose, difficulty, tier, backend, endpoint host, model, effective provider and model when reported, prompt_version, payload as sent after the egress filter, response (json), latency_ms, transmitted attempts, tokens in / out / cached, estimated cost, outcome, created_at.
- `retrieval_events`: id, learner_id, item_id, activity_id, at (timestamp), day (household date), outcome (`success` / `fail`), evidence (`typed` / `heard_confident` / `acoustic`).
- `learner_notes` (id, learner_id, text, provenance, created_at), `learner_note_citations` (note_id, activity_id), `book_notes` (id, learner_id, book_id, text, provenance, created_at).
- **One path into Anki.** `add_cards` is the only writer of `anki_outbox`, which gains `front`, `back`, `sentence` columns with their provenance (ADR-0018 §3); `knowledge.upsert_item` stops queueing a card for every new item. Card checks: the item occurs in the sentence; at most one item unknown to this learner in it; back ≤ 200 chars; no duplicate for this learner by lemma. Each check returns `pass` / `flag` / `reject` (anki-llm, *adopted*); a `flag` is sent with a tag the learner sees in Anki. Cards go straight to Anki (`ANKI_PREVIEW=auto`); a parent preview is deferred (ADR-0018 §5).

### 7.3 Busy store

Activity effects and the `activities` / ledger update are one transaction at each step that changes miscues or items. A write that gets `SQLITE_BUSY` is retried once; a second failure keeps `store_busy` in memory, ends the activity, and is written with the next successful write. `apply_records` and `record_boundary` drop their write on a second failure (logged); a BUSY on `checkpoint`'s settings read keeps the previous settings; identification's re-key and `finalize` leave their work to startup recovery.

## 8. What remains of ADR-0013 and what changes

Kept as written: `align` rules 1–8, Reposition (its prompt is recovery dialogue, §6.1), Sentence completion (i)–(iii) and its token updates, Practice (run by `practise_errors`), `/back N`, Correction interaction, CHECK outcomes (run by `quiz`), the Async guard (extended in §1).

1. **Candidate lifecycle.** Sentence completion no longer runs PRACTICE. A candidate is owned by the cycle whose `read_listen` created it and stays `candidate` across sentences and pages; its token state stays in its own `page_reads.reading_state`. `/back` reopening its sentence leaves it `candidate`; a later match withdraws it as `reread` while the cycle is open. **Closing a cycle** settles every candidate it still owns: `unsure(not_practised)`, or `unsure(skipped)` on `stop`.
2. **Page turn / `next page`** during `read_listen` completes the current sentence by (iii) and ends the activity with `page_turned`, without settlement. When the learner keeps reading, the harness starts a **continuation** in the same cycle, again on every further turn; continuations count toward session minutes, not toward `activities_per_cycle`. A page turn during `practise_errors` ends it with `page_turned`; candidates not yet practised stay owned by the cycle.
3. "After PRACTICE ends" and "Page completion → CHECK" are replaced by the menu.
4. The per-sentence line (`sentence_done`) is removed; Leafi speaks inside reading only as §6.1 allows.
5. **Interrupted session**: on startup a stale session's `running` activity becomes `interrupted`, its open cycle closes with reason `interrupted`, its candidates become `unsure(interrupted)`; "continue from page N?" uses the last page read of that learner and book.
6. **Difficulties (amended).** `unsure` reasons `not_practised` and `skipped` contribute `v(s) = 0` and do not count toward the existence rule. Knowledge items: `teach_items` writes an encounter with trigger `teach_incorrect` only for a `fail` (a success writes `teach_ok`, which Difficulties ignore), counted like `check(incorrect)`; a `quiz` question writes encounters only for its `item_ids`. `confirmed` still needs acoustic evidence.

**ADR-0013 v2 is required before code** (AGENTS.md names ADR-0013 the one owner of the reading rules). It holds §8.1–8.6 as pseudocode, hand-run on A→B→C page turns, `/back` across a page turn and `stop` mid-practice, and folds in the prior-art changes to alignment (prior-art §1, top changes 1–3): a **real-word pair at sim ≥ 0.80 is a substitution** (house/horse, there/three, though/through), fuzzy credit stays for non-words and same-phone pairs, a practice retry passes only on an exact match, a homophone or the same phones; **one page-wide alignment with internal jumps and affine deletions** replaces the bounded window, the "> 3 deletions" rule and the two-strike Reposition, with an **off-task** outcome (Project LISTEN MultiMatch, *adapted*); **function words are kept as observations but never practised** and never anchor alone; running-record conventions written down (self-correction and repetition are not errors; a told word is) with a self-correction count; numbers through `num2words` in `norm()`. Until v2 is accepted, `align` stays as rules 1–8 and no §8 code is written.

## 9. Evaluation: the Brain leads, an exploration share measures it (owner decision 2026-10-22, option B)

With `policy.sequencer = brain`, a share `policy.explore_share` (default 0.1) of boundaries is sequenced by the configured default policy instead, chosen at random; every boundary records `decided_by` and its `propensity` (0.9 / 0.1 for the default share). Comparing what follows — practice outcomes, retrieval successes, reading completed, sessions ended early — between the two groups, weighted by propensity, estimates whether the Brain sequences better than the default without the bias of judging a policy by its own choices (prior-art §2, *adopted* from off-policy evaluation practice). A replay set of recorded observations (`data/evals/decisions/`, local) compares models, prompts and tiers offline. If the Brain is not at least as good after a stated number of boundaries (`policy.review_after`, 200, *untuned*), the owner can switch `policy.sequencer = default`.

## 10. What changes where

**Generic machinery** (libraries §7, Combination 1 "thin, own the loop", with the prototype deciding where Combination 2 replaces it): deadlines and cancellation by `anyio` cancel scopes; retry waits by `tenacity`, SDK retries off; the session loop hand-written as §2 (`python-statemachine` optional for `ActivityStatus`); Burr as the alternative orchestrator the prototype measures; LLM calls through the raw SDKs with Pydantic models, PydanticAI as the alternative; migrations as ADR-0018 §6.2. **Precondition: TD-1** — move to `anthropic` ≥ 1.x on `httpx2` (the ecosystem moved in August 2026; libraries finding 1) before the egress transport and retry layer are written.

**Existing modules**: `coach.AsyncGuard` → the epoch; `controls.parse` → the control parser feeding the latch; `phrases` → filler, recovery and closing lines; `knowledge.card_fields` → beside generated card text; `knowledge.upsert_item` → no longer queues Anki; `anki._update_status` → `item_status.apply`; `records.export_session` → activities, sequencer departures and `deliver` outcomes; the `.env` settings manifest → per-learner policy keys (`policy.*`, `mastery.*`, `reading.*`, routing) on the existing settings page; `services/brain/claude.py`'s retry loop and `BRAIN_DEADLINE_S` → removed; `session.py`'s state machine → §2's loop.

**Documents changed with acceptance**: `flows/reading-session.md` redrawn around activities and cycles; `product.md` B4 and B7; `GLOSSARY.md` (study harness, activity, cycle, epoch, menu, ledger, sequencer, content owner, default policy, autonomy, tier, continuation, mastery mode; Practice redefined); `data-model.md` (§7.2's tables); `quality-attributes/reliability.md` (`BRAIN_DEADLINE_S` → §5.2); ADR-0013 v2; `security.md`'s prompt-safety action allow-list → the activity kinds of §3.1.

**The owner's console** (`scil/Leafi/`): buttons for the decision-replay evaluation and the exploration report (§9), the session export, and the policy / routing settings.

## Consequences

- The session's flow moves from code into a menu plus a sequencer; the owner chooses how much the Brain decides, both in sequencing and per activity's content, and the default policy is editable.
- Sessions without a Brain run on the default policy; Brain-only activities are then absent, not broken.
- Cost follows the task; the exploration share makes the Brain's value measurable from the first week.
- ADR-0013 keeps the reading algorithm and gains v2 (§8) before any code.

## Confirmation

`tests/test_session_menu.py`, `tests/test_construct.py` (reversed range rejected; `page: next|familiar` construct without ids; an unanswerable quiz question rejected; a `brain`-owned step without a Brain skipped), `tests/test_default_policy.py` (the built-in order; a reordered policy is followed; an invalid order falls back), `tests/test_sequence.py` (`sequencer = default` never calls the Brain; the exploration share is close to 0.1 over 1,000 boundaries; propensities recorded), `tests/test_negotiate.py`, `tests/test_negotiate_freshness.py`, `tests/test_negotiate_silence.py`, `tests/test_controls.py` (one skip taken once; `stop` then `skip` stays `stop`; `listener_lost_no_console` is a latch value; the deadline cancels a Brain call and a listen through the cancel scope), `tests/test_session_start.py` (lease, then recovery, then the guest sweep, in that order), `tests/test_finalize.py` (guest end states per ADR-0018 §1; no closing line after `lease_lost`; the lease released when `deliver` fails), `tests/test_brain_call.py` (a moment deadline stops `decide` + `generate` at 6 s; the ledger charges two transmitted attempts; with 0.5 units left `standard` falls through to `fast`; SDK clients built with `max_retries=0`), `tests/test_routing.py`, `tests/test_teach_scoring.py` (a mentioned-but-unused word is not a success; a low-confidence spoken answer judged `no` is `unavailable`), `tests/test_mastery.py` (`retrievals`: 6 over 3 days → known, 6 on one day → not; `anki`: follows the card interval), `tests/test_cycle_candidates.py`, `tests/test_epoch.py`, `tests/test_deadline.py`, `tests/test_reading_settings.py`, `tests/test_item_status.py`, `tests/test_activity_status.py`, `tests/test_settings_reload.py` (a learner or household setting change takes effect at the next checkpoint), `tests/test_anki_single_path.py`, `tests/test_card_checks.py` (`flag` sends with a tag), `tests/test_difficulties.py` (`teach_ok` ignored), `tests/test_busy.py` (each site of §7.3), and a replay of `cache/voice-diag.wav` through a mock-Brain session asserting no line inside reading with `interrupt=never`.

## Reviews

Codex design reviews 1–6 and code-plan-review passes 1–2 under `../plans/active/reviews/` (2026-10-21, 2026-10-22).
