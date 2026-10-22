---
status: proposed
date: 2026-10-21
revised: 2026-10-22 (v4: the independent codex and code-plan-review rounds on v3 and the owner's answers — session length and end timing configurable for every case, evaluation randomised per session, mastery producers, quiz answers under decision 6, routing tables per household; v3: configurable default policy with per-step code/Brain content, exploration, configurable mastery, parent features deferred; earlier rounds, see Reviews)
supersedes: 0013 (session rules only, see §8)
amends: 0003, 0013 (Difficulties and Reposition speech: §8.6, §6.1)
---

# The Brain leads the study session; the study harness executes, measures and limits it

Inputs: the requirements and decisions in [`../research/2026-10-21-ai-led-study.md`](../research/2026-10-21-ai-led-study.md) §1; the domain prior art in [`../research/2026-10-22-domain-prior-art.md`](../research/2026-10-22-domain-prior-art.md); the generic machinery in [`../research/2026-10-22-harness-libraries.md`](../research/2026-10-22-harness-libraries.md). Provenance of each mechanism: §11. Learners, recognition, egress, consent, privacy settings and the deferred parent features: ADR-0018.

## 1. Decision and terms

A study session is a sequence of **activities**. At every activity boundary a **sequencer** picks the next activity from a **menu** the **study harness** computes; the harness constructs, validates, runs, times, limits and records it. No correction happens inside a reading activity; errors found while reading are practised afterwards (owner requirement 2.2a).

- *Study harness*: the code around the Brain — observation, menu, construction, execution and timing, the ledger, records, routing, egress (ADR-0018), fallback. Glossary term.
- *Sequencer*: who picks the next activity in this session: the Brain, or the configured **default policy** (§3.3). It is fixed per session (§9).
- *Content owner*: per activity kind, who fills its **content fields** (the text and the choice of material): `policy.content.<kind> = code | brain`. Selection fields (kind, page, range, ids) may come from any sequencer; content fields come only from the owner (§3.3). Kinds whose content only a model can write (`teach_items`, `quiz`, `learner_questions`) have no `code` option.
- *Cycle*: an `open` record started by a reading activity chosen at a boundary; it owns every candidate its `read_listen` activities create, on any page; it closes when another boundary-chosen reading activity starts, at wrap, or on `stop`; closing settles what it still owns (§8.1). Continuations (§2) stay in it.
- *Epoch*: `(session_id, learner_id, cycle_id, page_read_id, revision_id, turn_id, learner_settings_version, household_settings_version)`. `turn_id` (ADR-0013 → Async guard) also increments on activity start and end, page turn, correction, learner adoption, a settings change. An item built under one epoch is dropped if the epoch has changed when it would be spoken, executed or written.
- *Deadlines*: `s.soft_deadline = start + session_max_min` — from then on the menu is `{end}` and no new activity starts; `s.hard_deadline = soft_deadline + session_grace_min` — the running activity is cut there (§6.3). Every wait — a Brain call, a listen, an activity step — is bounded by `min(its own timeout, s.hard_deadline − now)`.
- *Controls and cancellation (one owner).* The console reader, the Listener's control parser and the lease watcher post control events. `s.terminal ∈ {None, stop, lease_lost, time_up_session, listener_lost_no_console}` is monotonic (the first terminal wins). **Setting `s.terminal` is the only way to stop the session**: the setter also cancels the session's `anyio` `CancelScope`; the scope's own deadline is `s.hard_deadline`, and when it fires it sets `s.terminal = time_up_session` first. Every layer that can be cancelled — `run_activity`, `brain_call`, `negotiate`, `identify` — catches the scope's cancellation and maps it to `s.terminal`'s status (one mapping function), so a cancelled activity row always ends with that status, never `running`. `checkpoint(s)` after every await reads both settings versions (a change reloads settings and ledger limits and bumps the epoch) and raises `Terminal` when `s.terminal` is set — the cooperative path for code between awaits. `skip` events go into a queue consumed exactly once by `take_skip(s)`; a skip posted while no activity runs belongs to the current negotiation and does not change the epoch. Child tasks are spawned only through an `anyio` `TaskGroup` (never a raw `task.cancel()` beside a shield); blocking work in threads (ASR, TTS) gets a cooperative stop flag, because threads cannot be cancelled. A connection being opened when a cancel lands can leak from the HTTP pool, so the mediated client is rebuilt after such a cancel (libraries §2).
- *Listener lost.* A `ListenerLost` during `identify` is handled there (ADR-0018 §1). After `identify` returned it sets `listener_lost_no_console` when there is no console; with a console the session switches to text mode, keeps learner, cycle and page read, ends the running activity `aborted_stale`, and bumps the epoch.

## 2. The session loop (pseudocode is the rule)

```
run_session():
  acquire_lease()                                          # refused → "another session is running"
  try:
    close_stale_sessions(); sweep_guests()                 # §8.5 recovery (incl. guest end states), then ADR-0018 §1 sweep
    s = Session(learner = new_guest(), arm = assign_arm()) # §9: the session's sequencer, drawn once, with its propensity
    with CancelScope(deadline = s.hard_deadline) as s.scope:
      try:
        s.learner = identify(s)                            # ADR-0018 §1
        s.book = identify_book(s)
        last = None
        while True:
          checkpoint(s)
          menu = allowed(s)                                # §3.2; always contains "end"
          obs  = observe(s, last, menu)                    # §4; obs.epoch
          prop = sequence(s, obs, menu)                    # §3.3: Decision | None; never raises except Terminal
          apply_records(s, prop.records if prop else [], obs)  # §7.1; epoch-checked; never blocks
          out  = negotiate(s, prop, menu, obs.epoch)       # §2.1; Run(activity) | Reobserve
          if out is Reobserve: continue
          act = out.activity
          if act.kind == "end": record_boundary(s, obs, prop, act); break
          last = run_activity(s, act)                      # §3.1; start/finish rows inside
          while last.status == "page_turned" and s.learner_kept_reading():
            last = run_activity(s, continuation(s))        # §8.2; same cycle; repeats for every turn
          if last.status in TERMINAL: break
      except Terminal: pass
    finalize(s)                                            # outside the scope: local, no awaits, never raises
    with move_on_after(DELIVER_S, shield = True): deliver(s)          # 10 s
    with move_on_after(EXTRACT_S, shield = True): extract_notes(s)    # §7.1; 20 s; own allowance, not the session's
  finally:
    release_lease()                                        # whatever happened, including startup failures
```

`finalize(s)` does only local work in one transaction: close the running activity with its mapped status and the open cycle (§8.1), write the summary counts, set `ended_at`, and apply ADR-0018 §1's guest end-state rule. `deliver(s)` speaks the closing line only while the speech lease is still held (never after `lease_lost`), processes the Anki outbox, and writes each step's outcome (`closing_line`, `anki_synced`: done / skipped / failed) into the summary. `extract_notes(s)` is the post-session learner-note call (§7.1) with its own deadline and its own Brain allowance (`limits.extract_calls` 2), so a session that ended at its deadline or with its budget spent still gets notes; if it cannot run, no notes are written for that session and the summary says so. Nothing after `finalize` can undo it. A failure in `finalize` (e.g. busy) leaves the work to startup recovery, which applies the same rules.

`ActivityStatus` is one enum; §3.1's table says which kind can end in which status, and a test fails when a kind can end in a status the table omits. `TERMINAL = {stopped, lease_lost, idle_session, time_up_session, listener_lost_no_console}`; the others (`completed`, `skipped`, `page_turned`, `aborted_stale`, `store_busy`) return to the menu; `interrupted` is written only by startup recovery.

### 2.1 Autonomy and negotiation (Leafi's autonomy 0–10, owner decision 1)

```
negotiate(s, prop, menu, epoch) -> Run(activity) | Reobserve:
  END = {"kind": "end"}
  props = [p for p in ([prop.activity, prop.alternative] if prop else []) if p]
  def settle(specs, refusing = False):                   # the ONLY way a branch returns an activity
    a = first_constructible(s, specs + default_chain(s, menu) + [END])   # §3.3: the whole default policy, then END
    checkpoint(s)
    if take_skip(s):
      if refusing or a.kind == "end": drain_skips(s); a = construct(s, END)
      else: return refused_of(a)
    return Reobserve if s.epoch() != epoch else Run(a)
  def refused_of(x):
    rest = menu - {x.kind}
    return settle([p for p in props if p.kind != x.kind] + default_chain(s, rest), refusing = True)
  first = settle(props)
  if first is Reobserve: return Reobserve
  act = first.activity
  if s.autonomy <= 1:                                      # a short list: Leafi offers 2–3 choices
    ask("Would you like to " + describe_choices(s, act, menu, n = 3) + "?")
  elif s.autonomy <= 7:
    say(rationale_line(prop, act))                         # a reason at every band up to 7 (prior-art §2 #9)
    if s.autonomy <= 3: ask("Shall we " + describe(act) + "? Or something else?")
  else:
    say(describe(act))
  silences = 0
  for turn in (1, 2):
    if s.autonomy >= 8: break
    c = parse_choice(listen(ASK_S))      # ASK_S = 8 s; c ∈ yes | no | skip | named k | none | unparsed
    checkpoint(s)
    if take_skip(s) or c in ("skip", "no"): return refused_of(act)
    if s.epoch() != epoch: return Reobserve
    if c == "yes": break
    if c in ("none", "unparsed"):
      silences += 1
      if s.autonomy <= 3:
        if silences == 1: ask("Shall we " + describe(act) + "?"); continue
        return settle([wait_spec(s)])                      # two silences at 0–3: never start it; wait (decision 4)
      break
    if c.named in menu: return settle([learner_spec(s, c.named), act.spec])
    say(why_not(c.named))
  checkpoint(s)
  if take_skip(s): return refused_of(act)
  return Reobserve if s.epoch() != epoch else Run(act)
wait_spec(s) = {"kind": "break", "seconds": 30} unless the previous boundary was already such a wait, then END
```

Every return passes through `settle` or the final check, so it is either an activity constructed and checked under the current epoch or `Reobserve`. A refusal never re-selects the refused kind. `stop` ends the session at every level, including 10.

## 3. Activities, construction and the menu

### 3.1 Activities

**Statuses every kind can end in:** `completed`, `stopped`, `lease_lost`, `listener_lost_no_console`, `time_up_session`, `aborted_stale`, `store_busy` (§7.3). **`skip`**: in `review_anki`, `read_aloud`, `teach_items`, `recall_items`, `quiz` it skips the current card, sentence, item or question (the last one → `completed`); in `read_listen` it completes the current sentence; in `practise_errors` it settles the current candidate `unsure(skipped)`; in `learner_questions`, `break` and `add_cards` it ends the activity with `skipped`. Each activity is also capped at `limits.activity_max_min` (8; attention plateau, research P31) and ends with `completed` at its next natural step after that.

| Activity | Params (selection / content) | Inside (harness) | Kind-specific statuses |
|---|---|---|---|
| `review_anki` | sel: `max_cards` ≤ min(due, 20) | ADR-0004 review loop; each answer graded again / hard / good / easy (eases 1–4) and sent to Anki (FSRS schedules); writes a retrieval event per card's item (§3.4) | skipped, idle_session |
| `read_listen` | sel: `page: current\|next\|familiar`, range `rest\|{from, to}` | acquires the page when `next` or `familiar` (a page this learner read before), then resolves the range; ADR-0013 alignment and sentence completion; speech only as §6.1 | page_turned, skipped, idle_session |
| `read_aloud` | sel: page, range; content: `translate: none\|all\|hard` (default `none`), `hard_sentence_ids` (≤ 3 per page; chosen by the count of words unknown to this learner) | Kokoro reads with highlighting on Faces; translation lines after a sentence when asked | skipped |
| `practise_errors` | sel: `candidate_ids` (open, owned by the open cycle, within the ledger) | ADR-0013 → Practice per candidate on its own `page_read` state | page_turned, skipped |
| `teach_items` | sel: `item_ids`; content: per item `method`, `explanation`, `prompt`, `expect ∈ {item_said, item_used, cloze_word}` | explanation (generated from the item, its context sentence, the learner's error if any, and the goal — Explain-My-Answer style), then the prompt; scored by §3.4 | skipped |
| `recall_items` | sel: `item_ids` (items in `learning` without an acknowledged Anki card, due by the spacing in §6.2) | cued recall from the item's stored explanation (no generation needed); scored by §3.4 | skipped |
| `quiz` | sel: `evidence_sentence_ids`; content: `questions: [{text, type, answers (keyword sets), item_ids}]` ≤ the ledger | construction rejects a question whose answers are not supported by its cited sentences; question types from CROWD (completion, recall, open-ended, wh-, distancing); ADR-0013 → CHECK outcomes, with §3.4's spoken-answer rule | skipped, idle_session |
| `learner_questions` | sel: `max_turns` ≤ 5 | the learner asks; each answer is one Brain call, purpose `answer`, grounded in the page and `book_notes`, on an eligible backend (ADR-0018 §2) | skipped, idle_session |
| `add_cards` | sel: `item_ids`; content: per card `front`, `back`, `sentence` | card checks (§7.2) → `anki_outbox` | skipped |
| `break` | sel: `seconds` ≤ 120 | silence, a Face timer | skipped |
| `end` | content: `say` | — | — |

### 3.2 Menu

```
allowed(s) -> set[kind]:
  if now >= s.soft_deadline or s.ledger.minutes >= session_max_min: return {"end"}
  m = {"end", "break"}
  gen = routable(s, purpose = "generate") and s.ledger.can_afford("standard")
  if anki_reachable and s.anki_due > 0 and not s.goal_met("reviews"):               m += {"review_anki"}
  if s.book and (s.unread_range(current) or s.can_acquire_next_page or s.familiar_pages): m += {"read_listen", "read_aloud"}
  if s.recall_due:                                                                  m += {"recall_items"}
  if s.cycle:
    if s.cycle.open_candidates and s.ledger.cycle_errors_left > 0:                  m += {"practise_errors"}
    if s.cycle.new_item_candidates and s.ledger.cycle_new_left > 0 and gen:        m += {"teach_items"}
    if s.cycle.read_sentences and s.ledger.cycle_quiz_left > 0 and gen:            m += {"quiz"}
    if s.cycle.read_sentences and routable(s, purpose = "answer"):                 m += {"learner_questions"}
    if s.cycle.cardable_items and s.ledger.cards_left > 0:                         m += {"add_cards"}
    if s.cycle.boundary_activities >= limits.activities_per_cycle:                 # continuations do not count
      m = m ∩ {"read_listen", "read_aloud", "end"}
  return m
```

`cardable_items` are practised or taught items that have card text: a stored explanation and context sentence (`code` owner), or `gen` when `policy.content.add_cards = brain`.

### 3.3 Sequencing, construction and the configurable default policy

```
sequence(s, obs, menu) -> Decision | None:
  if s.arm == "default": return None                       # §9; negotiate's default chain decides
  d = brain_call(s, "decide", obs, DECIDE_SCHEMA, moment_deadline = moment("next_activity"))
  if d is None: s.boundary.override = "brain_unavailable"  # recorded; executed choice comes from the default chain
  return d
```

**The default policy is a setting** (owner decision 2026-10-22): `policy.default_order`, an ordered list of steps `{kind, when}`, with this built-in default:

| # | step | when |
|---|---|---|
| 1 | `review_anki` | `first_boundary` |
| 2 | `recall_items` | `has_recall_due` |
| 3 | `practise_errors` | `has_candidates` (top by Difficulty weight) |
| 4 | `teach_items` | `has_new_items` |
| 5 | `add_cards` | `has_cardable` |
| 6 | `read_listen` | `unread` (`page: current, range: rest`, else `page: next`) |
| 7 | `end` | `always` |

`default_chain(s, menu)` returns **every** step, in order, whose kind is in `menu` and whose `when` holds; `first_constructible` tries them in turn, so a step that cannot be constructed (e.g. generation timed out) falls through to the next step, not straight to `end`. The `when` vocabulary is fixed (`first_boundary`, `has_recall_due`, `has_candidates`, `has_new_items`, `has_cardable`, `unread`, `always`); a learner or household may reorder, remove or add steps from §3.1's kinds; an invalid order is rejected at save and the built-in default is used. The policy has a `policy_version` (a hash) recorded on every boundary.

`construct(s, spec) -> Activity | Rejected(reason)` validates against the **current** state:

1. `kind ∈ allowed(s)`.
2. **Selection fields** from the spec (Brain, learner or default). **Content fields only from the content owner**: with `code`, `default_params(s, kind)` builds them from stored data (`knowledge.card_fields` for cards, the stored explanation for recall) and any content fields in a Brain spec are discarded; with `brain`, one `generate` call (its kind's schema, the moment's remaining deadline) fills them, and Brain-proposed content in the `decide` output is used only if it passes the same schema; failure → `Rejected("not available now")`.
3. Ids: `page: current` ranges belong to the current page read, ordered and non-empty; `page: next|familiar` carry no sentence ids; candidate ids open and owned by the open cycle; item ids exist for this learner; quiz answerability (§3.1).
4. Counts ≤ the ledger's **remaining** budgets; text lengths; no URLs.

### 3.4 Answer scores (teaching, recall, quiz)

A spoken answer counts only when it is **confidently recognised**: every word of the transcript has confidence ≥ `ANSWER_MIN_CONF` (0.8, *untuned*); otherwise the outcome is `unavailable`, whatever it seems to say (owner decision 6, extended to success as well as failure, and to `quiz`). Typed answers always count.

- `item_said`: ADR-0013's retry test on the whole answer; `cloze_word`: the answer is the cloze word (exact, a homophone, or the same phones — ADR-0013 v2's real-word rule, §8); `item_used`: one `judge` call (§5.1) with few-shot examples → `yes` / `no` / `cannot_tell`.
- `quiz`: ADR-0013 → CHECK outcomes on a counted answer; an uncounted spoken answer is `unavailable` and writes no encounter.
- Silence, `skip`, `cannot_tell`, no eligible `judge` backend → `unavailable`: no retrieval event, no encounter.
- `success` / `fail` write a `retrieval_events` row (full timestamp, household day, evidence `typed` | `heard_confident` | `acoustic`) and, for teaching, an encounter (§8.6).

## 4. Observation

Built by `study/observe.py`; ADR-0018's egress filter removes local-only fields at send time. Plain-text sections: `epoch`; `session` (elapsed, soft and hard deadlines, ledger remainders, goals, `autonomy`); `page` (book, printed page, sentences with ids, unread range, familiar pages); `last_activity` (id, kind, status, duration, per-item results with categories; heard words only when ADR-0018 allows); `cycle` (open candidates with Difficulty weight and ASR confidence band; new-item candidates with kind and level band; cardable items; recall due); `memory` (recent difficulties over 14 days, familiar books and topics, current learner notes); `menu` (allowed kinds, the default chain, the policy text, §6.3).

## 5. Decision and the Brain

A `decide` call returns one structured output, one schema for the whole session: `activity` (an `anyOf` of one object per kind, selection fields and optional content fields), `alternative`, `say_before` (≤ 300 chars), `rationale` with Bridge's slots `evidence`, `strategy`, `intention` (≤ 150 chars each), `records` (optional, §7.1), `epoch`. Each `generate` kind has its own fixed schema. Schemas, effort and thinking stay constant within a session per (purpose, tier). Typed outputs are Pydantic models validated by the harness.

```
brain_call(s, purpose, payload, schema, moment_deadline = None) -> Result | None:   # never raises except Terminal
  deadline = min(now + TOTAL_S[purpose], (moment_deadline or ∞) − OUTPUT_RESERVE[mouth], s.hard_deadline)
  for tier in route(purpose, difficulty(s, purpose, payload)):     # §5.1
    if not s.ledger.can_afford(tier): continue
    for b in eligible(tier, purpose, s.learner):                    # ADR-0018 §2
      if now >= deadline: return None
      r = b.call(payload, schema, timeout = min(PER_CALL_S[purpose], deadline − now),
                 budget = s.ledger.transmission_budget(tier))       # the mediated transport reserves before each send
      checkpoint(s)
      if r is None: continue
      ok, reason = check_shape(r, payload)
      if ok: return r
      payload = payload.with_rejection(reason); break
  return None
```

**Budget per transmission.** The mediated transport (ADR-0018 §2) asks the ledger before **each** transmission — first send and retry — and charges it at once; a transmission the budget cannot cover is not sent, and a cancelled call has already been charged for what it sent. **Output reserve.** `OUTPUT_RESERVE` (PC Mouth 1.0 s, camera Mouth 3.5 s, *measured values replace these*) is subtracted from the moment's deadline, so model work ends in time for TTS and the Mouth; when a moment's budget runs out, negotiation falls through the default chain, whose `code`-owned steps need no generation. A filler line is due when a `decide` or `generate` call has not returned after 0.8 s; on the camera Mouth it is pushed at the call's start and made audible at 0.8 s, or replaced by Face text. Retries: SDKs built with `max_retries=0`; the mediated transport owns transport retry; `brain_call` owns escalation.

### 5.1 Routing by task type and difficulty

Purposes: `decide`, `generate`, `answer`, `judge`, `word`. `judge` and `answer` carry learner text and follow ADR-0018's eligibility. `difficulty(s, purpose, payload) ∈ {low, normal, high}` from local signals: item kind `grammar` or `pattern` → high; a learner question over 12 words, or why/how → high; a translation of a sentence over 20 words → high; a retry after an invalid answer → one step up; a `word` line → low; else normal (*untuned*). `BRAIN_TIERS` and `BRAIN_ROUTES` are **household** settings (ADR-0018 §1, §5). `route()` returns preferred → escalation → every other configured tier, strongest first, then weaker ones marked `degraded` (a FrugalGPT-style cascade). Defaults (the one place the `judge` tier is stated):

| purpose \ difficulty | low | normal | high |
|---|---|---|---|
| `decide` | standard → deep | standard → deep | standard → deep |
| `generate` | fast → standard | standard → deep | deep → standard |
| `answer` | fast → standard | standard → deep | deep → standard |
| `judge` | standard → deep | standard → deep | standard → deep |
| `word` | fast → standard | fast → standard | standard → fast |

`judge` stays on `standard` with few-shot examples until a labelled set of this child's answers justifies `fast`. A `degraded` answer is prefaced "here is a short answer"; an exhausted chain returns `None`. `routable(s, purpose)` is true when an eligible, affordable backend exists. Tiers: `standard` = a mid model; `deep` = the strongest configured; `fast` per ADR-0018 §2. The ledger charges `fast` 0.25, `standard` 1, `deep` 3 per transmission against `brain_calls_per_session`, with tokens and estimated cost recorded.

### 5.2 Budgets for what the learner perceives

Stage values are measured p50/p95 per Mouth before the design relies on them (AGENTS.md → Verification). Each moment's deadline is passed into `brain_call` and construction.

| Moment | Stages | Budget (PC Mouth / camera Mouth) | Past the budget |
|---|---|---|---|
| Leafi reacts after the learner stops | VAD end → decision started → filler or Face text | 1.0 s / Face text at 1.0 s | Face text "…" |
| The next activity's first word (`next_activity`) | `decide` + `generate` if needed + output reserve | 6 s / 9 s | the default chain's next constructible step |
| Feedback on an answer | `judge` or local scoring + output reserve | 3 s / 6 s | `unavailable`, neutral line |
| An answer to a learner's question | `answer` + output reserve | 8 s / 12 s | "I can't answer that one right now" |

`PER_CALL_S` (*untuned*): decide 3, generate 4, answer 5, judge 2, word 1.5. `TOTAL_S`: decide 5, generate 8, answer 10, judge 4, word 2.

## 6. Settings and policy

Every default is a starting value; *untuned* ones have no measured or published basis yet.

### 6.1 Speech inside `read_listen`

| `reading.interrupt` | silence ≥ `silence_backchannel_s` (3) | silence ≥ + `silence_prompt_s` (3) | sentence end | page end |
|---|---|---|---|---|
| `never` | nothing | nothing | nothing | `reading.encourage` line (≤ 1) |
| `stuck_only` (default) | soft non-verbal cue on Mouths, "…" on Faces | "Want a hint?"; on yes Leafi says the word, the token is marked `supplied` | nothing | `reading.encourage` line (≤ 1) |
| `sentence_end` | as `stuck_only` | as `stuck_only` | an encourage line when the sentence had a self-correction | as above |

**Recovery dialogue is outside this table** and always allowed (the Reposition prompt, "I can't see the page", listener lost, page uncertain, lease or device messages). `reading.encourage`: `none` | `specific` (default; names a self-correction or effort, never "smart") | `frequent` (offered, though research P37/P38 warn against frequent praise). Leafi never prompts guessing a word from a picture (research P2). A `supplied` token becomes a candidate with `heard = null`, reason `supplied`.

### 6.2 Items, what is new, and mastery

`knowledge_items` are per learner and gain the status `ignored`. New = no row for this learner, or `new`. Rank: one-unknown sentences first (AnkiMorphs), level band above the learner's (Cambridge YLE, SUBTLEX-UK children's frequency), then frequency.

**Transitions** (`item_status.apply(event)` is the only code that changes status): `new → learning` on the item's first retrieval event of any outcome, or when its card is first acknowledged by Anki; `learning → known` and `known → lapsed` by `mastery.mode`; `* → ignored` by the Brain's request or the learner. **Retrieval-event writers**: `teach_items`, `recall_items`, `quiz` (per cited item), `review_anki` (per reviewed card's item).

**Mastery is configurable** (owner decision), `mastery.mode`:
- `retrievals` (default): `known` when the item has ≥ `mastery.min_retrievals` (6) counted successes over ≥ `mastery.min_days` (3) distinct household days. Items in `learning` without an acknowledged card are re-asked by `recall_items` at a spacing of 1, 2 and 4 days after the last success (*untuned*), which is what makes this mode reachable.
- `anki`: cardable items become cards; `review_anki` grades them; FSRS schedules; `known` when the card's interval ≥ `REVIEW_KNOWN_INTERVAL_DAYS`, `lapsed` on a lapse.

In both modes an item with an acknowledged Anki card follows Anki's state. Status is derived, not stored apart from its evidence: `forget --session` recomputes the statuses of the items whose events it deleted.

### 6.3 Practice policy, session length, goals and the ledger

| Setting | Default | Notes |
|---|---|---|
| `practice.max_errors` | 5 per cycle | Reading Coach's five |
| `practice.max_new` | 3 per cycle, 8 per session | Text Talk |
| `quiz.max_questions` | 4 per cycle | WWC |
| `cards.max` | 10 per session | *untuned* |
| `session.max_min` | by age band: 15 for ages 6–7, 20 otherwise; ceiling 30 | research §6 |
| `session.max_min_unknown_age` | 15 | owner decision: its own setting |
| `session.max_min_guest` | 15 | owner decision: its own setting |
| `session.end_mode` | `finish_activity` | `finish_activity`: at the soft deadline no new activity starts and the running one continues up to `session.grace_min`; `hard`: grace 0, the running activity is cut at the soft deadline |
| `session.grace_min` | 3 | 0–10 |
| `limits.activity_max_min` | 8 | research P31 |
| `limits.activities_per_cycle` | 6 | *untuned* |
| `limits.brain_calls_per_session` | 40 tier-weighted | *untuned* |
| `limits.extract_calls` | 2 | outside the session budget (§2) |
| `policy.sequencer` | `brain` | `brain` / `default` (the whole session) |
| `policy.explore_share` | 0.1 | §9 |

All are per-learner settings except the routing tables (household). **Goals** are composable, each with its window: `reviews: due` (per day), `new_items: N` (per day or per session), `pages: N` (per day or per session); a day is the household's local date. Goals never nag: an unmet goal is shown, never spoken as a reproach (research N18). Three or more sessions a week is the suggested rhythm (research C33), shown, not enforced. **The ledger** holds the cumulative counters per session and per open cycle; it is updated in the same transaction as each step's effects (§7.3). The policy text sent to the Brain states the defaults, the no-correction-while-reading rule, the praise rules and the autonomy level; enforcement never depends on the text.

## 7. Records

### 7.1 What the Brain may write

In a decision's `records`: `assessment` (≤ 500 chars about `last_activity.id`), `item_status` (a request, §6.2), `book_note` (topic, characters, a one-line story summary). `apply_records` validates each record on its own and writes the valid ones in one transaction before the next activity; an invalid record is dropped and logged and never affects the decision.

**Learner notes** are written only by `extract_notes(s)` after the session (§2): one `generate` call over the session's activities, each note citing the activity ids it rests on (`learner_note_citations`) and shown as the Brain's interpretation. A note whose cited activities are more than 10 sessions old with no newer citing note drops out of `memory` (*untuned*); `forget --session` deletes a note whose citations all point into that session.

### 7.2 What the harness records itself

- `cycles`: id, session_id, status, opened_by_activity, closed_reason, opened_at, closed_at.
- `activities`: id, session_id, cycle_id, kind, continuation, params (json), **arm** (the session's sequencer, §9), **propensity**, **policy_version**, **decided_by** (`brain` / `default` / `learner`), **override** (`brain_unavailable` | `learner_choice` | `refused` | `wait` | none), autonomy, epoch, status, started_at, ended_at, outcome (json, with the default chain's first step computed alongside), assessment?
- `brain_calls`: id, session_id, activity_id?, purpose, difficulty, tier, backend, endpoint host, model, effective provider and model when reported, prompt_version, payload as sent after the egress filter, response, latency_ms, transmitted attempts, tokens in / out / cached, estimated cost, outcome, created_at.
- `retrieval_events`: id, learner_id, item_id, activity_id, at, day, outcome (`success` / `fail`), evidence (`typed` / `heard_confident` / `acoustic`).
- `learner_notes`, `learner_note_citations`, `book_notes` (with provenance, ADR-0018 §3).
- **One path into Anki.** `add_cards` is the only writer of `anki_outbox`, which stores `front`, `back`, `sentence` with provenance; `anki.push` sends the stored fields for both `add` and `update`; `_queue_update_if_pushed` is removed, and `knowledge.card_fields` becomes the `code` content owner's builder for `add_cards`. Card checks: the item occurs in the sentence; at most one item unknown to this learner in it; back ≤ 200 chars; no duplicate for this learner by lemma; each returns `pass` / `flag` / `reject`; a `flag` is sent with a tag the learner sees. Cards go straight to Anki (`ANKI_PREVIEW=auto`; parent preview deferred, ADR-0018 §6). When Anki is enabled, ADR-0018 §2's AnkiWeb notice is shown.

### 7.3 Busy store

The study process opens its store with `busy_timeout` 250 ms and retries a busy write with `anyio.sleep` backoff inside the step's remaining time, so the event loop never blocks for seconds; other processes keep 5 s. A step's effects and its ledger update are one transaction (`Store.transaction()` rolls back a failed `COMMIT`, fixed in `508448b`). A step still busy at its time limit ends the activity with `store_busy`, kept in memory and written with the next successful write. `apply_records` and `record_boundary` drop their write after the retry window (logged); a busy settings read in `checkpoint` keeps the previous settings; `adopt` (ADR-0018 §1) retries identification; `finalize` leaves its work to startup recovery.

## 8. What remains of ADR-0013 and what changes

Kept as written: `align` rules 1–8, Reposition (its prompt is recovery dialogue, §6.1), Sentence completion (i)–(iii) and its token updates, Practice (run by `practise_errors`), `/back N`, Correction interaction, CHECK outcomes (run by `quiz`, with §3.4's rule), the Async guard (extended in §1).

1. **Candidate lifecycle.** Sentence completion no longer runs PRACTICE. A candidate is owned by the cycle whose `read_listen` created it and stays `candidate` across sentences and pages; `/back` reopening its sentence leaves it `candidate`; a later match withdraws it as `reread` while the cycle is open. Closing a cycle settles every candidate it still owns: `unsure(not_practised)`, or `unsure(skipped)` on `stop`.
2. **Page turn / `next page`** during `read_listen` completes the current sentence by (iii) and ends the activity with `page_turned`, without settlement; when the learner keeps reading, a continuation starts in the same cycle, again on every further turn; continuations count toward session minutes, not toward `activities_per_cycle`. A page turn during `practise_errors` ends it with `page_turned`; unpractised candidates stay owned by the cycle.
3. "After PRACTICE ends" and "Page completion → CHECK" are replaced by the menu.
4. The per-sentence line (`sentence_done`) is removed; Leafi speaks inside reading only as §6.1 allows.
5. **Interrupted session**: on startup a stale session's `running` activity becomes `interrupted`, its open cycle closes with reason `interrupted`, its candidates become `unsure(interrupted)`; guest end states per ADR-0018 §1; "continue from page N?" uses the last page read of that learner and book.
6. **Difficulties (amended).** `unsure` reasons `not_practised` and `skipped` contribute `v(s) = 0` and do not count toward the existence rule. `teach_items` and `recall_items` write an encounter with trigger `teach_incorrect` for a `fail` (counted like `check(incorrect)`) and `teach_ok` for a success (ignored by Difficulties). `confirmed` still needs acoustic evidence.

**ADR-0013 v2 is required before code.** It holds §8.1–8.6 as pseudocode, hand-run on A→B→C page turns, `/back` across a page turn and `stop` mid-practice, and folds in the prior-art changes to alignment: a real-word pair at sim ≥ 0.80 is a substitution (house/horse, there/three, though/through), fuzzy credit stays for non-words and same-phone pairs, a practice retry passes only on an exact match, a homophone or the same phones; one page-wide alignment with internal jumps, affine deletions and an off-task outcome replaces the bounded window, the "> 3 deletions" rule and the two-strike Reposition (Project LISTEN MultiMatch, *adapted*); function words kept as observations but never practised and never anchoring alone; running-record conventions (self-correction and repetition are not errors; a told word is) with a self-correction count; numbers through `num2words`; a stated false-alarm budget; dropped inflections decided for dialect; ASR hotwords for the practice retry only (TD-17). Until v2 is accepted, `align` stays as rules 1–8 and no §8 code is written.

## 9. Evaluation: the Brain leads, an exploration share measures it (owner decision, option B; randomised per session)

With `policy.sequencer = brain`, each session is assigned at its start: with probability `policy.explore_share` (0.1) the whole session is sequenced by the default policy (arm `default`), otherwise by the Brain (arm `brain`); arm and propensity are recorded on every activity row. Randomising per session keeps one sequencer's choices from leaking into the other's outcomes. **Outcome per session**: counted retrieval successes per minute, practice outcomes, sentences read, and whether the session ended early. **Estimator**: inverse-propensity weighting of the session outcome by arm, analysed by assigned arm (intention to treat): a Brain-arm boundary that fell to the default chain because the Brain was unavailable stays in the Brain arm, recorded as `override = brain_unavailable`, so failures count against the Brain. With 10 % exploration, `policy.review_after` (200 sessions, *untuned*) is a **smoke check** (are the two arms obviously different, are overrides frequent), not a conclusion; a stated effect size and its sample size are written before anyone draws one. A replay set of recorded observations (`data/evals/decisions/`, local) compares models, prompts and tiers offline. The owner can set `policy.sequencer = default` at any time.

## 10. What changes where

**Generic machinery** (libraries §7, Combination 1 "thin, own the loop", the prototype deciding where Combination 2 replaces it): `anyio` cancel scopes and `TaskGroup` (§1); `tenacity` waits in the mediated transport; the session loop hand-written as §2 (`python-statemachine` optional for `ActivityStatus`); Burr as the alternative orchestrator the prototype measures; LLM calls through the raw SDKs with Pydantic models, PydanticAI as the alternative; migrations per ADR-0018 §7.2. **Precondition: TD-1** — `anthropic` ≥ 1.x on `httpx2`, and every Leafi-built client on `httpx2` (ADR-0018 §2). The prototype's tests (libraries §7 and the P-A / P-B lists of libraries §2 and §6) are the first entries of this ADR's Confirmation once chosen.

**Existing modules**: `coach.AsyncGuard` → the epoch; `controls.parse` → the control parser; `phrases` → filler, recovery and closing lines; `knowledge.card_fields` → the `code` builder for cards; `knowledge.upsert_item` → no Anki queueing; `_queue_update_if_pushed` → removed; `anki._update_status` → `item_status.apply`; `anki.answer` → eases 1–4; `records.export_session` → activities, arms and overrides, `deliver` outcomes; `session._cancel_inputs`'s raw `task.cancel()` → `TaskGroup` cancellation; the `.env` settings manifest → per-learner and household keys on the existing settings page; `services/brain/claude.py`'s retry loop and `BRAIN_DEADLINE_S` → removed; the old Brain request types → ADR-0018 §7.4; `session.py`'s state machine → §2's loop.

**Documents changed with acceptance**: `flows/reading-session.md`; `product.md` B4 and B7; `GLOSSARY.md` (study harness, activity, cycle, epoch, menu, ledger, sequencer, arm, content owner, default policy, autonomy, tier, continuation, mastery mode, soft and hard deadline; Practice redefined); `data-model.md`; `quality-attributes/reliability.md` (`BRAIN_DEADLINE_S` → §5.2); ADR-0013 v2; `security.md`'s prompt-safety action allow-list → §3.1's kinds.

**The owner's console** (`scil/Leafi/`): buttons for the decision-replay evaluation and the arm report (§9), the session export, and the policy, session-length and routing settings.

## 11. Provenance of this ADR's mechanisms (code-plan-review H7)

| Mechanism | Verdict | Source |
|---|---|---|
| read first, practise after; ≤ 5 errors | adopted | Microsoft Reading Coach (prior-art §2) |
| menu + sequencer + harness boundary | adapted | Rasa CALM commands, Pipecat Flows nodes, StratL (research §2, §7) |
| configurable default policy, `when` vocabulary, content owner | original, searched | owner decision; no tutor product exposes a policy at this grain |
| epoch, `Reobserve` | adapted | fencing tokens (prior-art §2) |
| control latch, one cancellation owner, `TaskGroup`, shielded cleanup | adopted | `anyio` (libraries §2) |
| soft and hard deadline, `finish_activity` | original | owner decision 2026-10-22 |
| autonomy bands, short list at 0–1, rationale up to 7 | adapted | levels of automation (prior-art §2 #9) |
| `rationale` slots | adopted | Bridge (research A11) |
| routing cascade with `degraded` | adapted | FrugalGPT-style cascades (prior-art §2 #13) |
| filler at 0.8 s | adapted | Pipecat `pre_actions` (research R7) |
| perceived-moment budgets, output reserve | original | code-plan-review K3.1 |
| `difficulty()` signals | original, *untuned* | — |
| silence thresholds | adapted | Project LISTEN 2 s + 2 s, Reading Assistant ≥ 3 s |
| quiz answerability, CROWD types | adopted | research N20; CROWD (prior-art §2 #19) |
| `judge` on standard with few-shot | adopted | prior-art SS20, SS21 |
| answer counted only when confidently recognised | original | owner decision 6, extended |
| one-unknown ranking | adopted | AnkiMorphs |
| mastery modes, re-ask spacing | adapted | research P14 (retrievals); Anki FSRS; spacing 1-2-4 *untuned* |
| learner notes after the session, with citations | adopted | prior-art SS5 |
| card checks pass / flag / reject | adopted | anki-llm (research N14) |
| per-session randomisation, IPW, intention to treat | adopted | off-policy evaluation practice (prior-art SS22) |
| per-activity minute cap | adopted | research P31 |
| goals without nagging, ≥ 3 days a week shown | adopted | research N18, C33 |
| ledger, records, busy handling | original | — |

Research findings this ADR does not use, with their fate: C15/N4 (implicit promotion from reading) — rejected, alignment evidence is stronger; B12 (explicit error marking between readings) — used by `practise_errors` after `read_listen`; SS5 (a separate preparation step before the session) — rejected for v1, the filler and output reserve cover latency; B19 (`translate` default) — used, `none`, ≤ 3 hard sentences per page; N10 (explanations from error, target and goal) — used in `teach_items`; cmi5 export mapping — deferred with the parent export (ADR-0018 §6).

## Consequences

- The session's flow moves from code into a menu plus a sequencer; the owner chooses how much the Brain decides, in sequencing and per activity's content, and edits the default policy.
- Sessions without a Brain run on the default policy; Brain-only activities are then absent, not broken.
- Cost follows the task; per-session exploration makes the Brain's value measurable.
- ADR-0013 keeps the reading algorithm and gains v2 (§8) before any code.

## Confirmation

`tests/test_session_start.py` (lease, recovery, sweep, in order; the lease is released when recovery raises). `tests/test_cancellation.py` (a `stop` and a deadline inside `listen`, inside a Brain call and inside `negotiate` each end the running activity with the mapped status, never `running`; `deliver` and `extract_notes` run after `time_up_session`). `tests/test_session_menu.py`, `tests/test_construct.py` (a Brain spec's content fields are discarded when the owner is `code`; a `brain`-owned step without a Brain falls through to the next default step; an unanswerable quiz question is rejected). `tests/test_default_policy.py` (built-in order; a reordered policy is followed; a step that cannot be constructed falls through to the next one, not to `end`; an invalid order falls back). `tests/test_arms.py` (per-session assignment near 10 % over 1,000 sessions; arm, propensity, policy version and override recorded per activity; a Brain-arm fallback stays in the Brain arm). `tests/test_negotiate.py`, `tests/test_negotiate_freshness.py`, `tests/test_negotiate_silence.py` (two silences at autonomy 2 start a 30 s wait, then end; at autonomy 1 Leafi offers a short list). `tests/test_controls.py`. `tests/test_brain_call.py` (the transport refuses a retry the budget cannot cover; a cancelled call has charged what it sent; the output reserve leaves time for the camera Mouth). `tests/test_routing.py`. `tests/test_answer_scores.py` ("I don't know what through means" is not a success; a low-confidence spoken "through" is `unavailable`; a low-confidence spoken quiz answer writes no encounter). `tests/test_mastery.py` (`retrievals`: 6 over 3 days → known, 6 on one day → not; `recall_items` re-asks a `learning` item; `anki`: follows the card; `forget --session` recomputes status). `tests/test_session_length.py` (guest and unknown-age settings; `finish_activity` lets the running activity finish within grace; `hard` cuts it). `tests/test_cycle_candidates.py`, `tests/test_epoch.py`, `tests/test_reading_settings.py`, `tests/test_item_status.py`, `tests/test_activity_status.py`, `tests/test_settings_reload.py`, `tests/test_anki_single_path.py` (only `add_cards` writes the outbox; `push` sends stored fields), `tests/test_card_checks.py`, `tests/test_difficulties.py`, `tests/test_busy.py` (no step blocks the loop for more than 300 ms; each site of §7.3), and a replay of `cache/voice-diag.wav` through a mock-Brain session asserting no line inside reading with `interrupt=never`.

## Reviews

Under `../plans/active/reviews/`: codex design reviews 1–6 (2026-10-21), code-plan-review passes 1–2, the independent codex and code-plan-review rounds on v3 (2026-10-22), and the codex rounds on v4.
