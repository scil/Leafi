---
status: proposed
date: 2026-10-24
revision: 3
---

# Practice planned and led by the Brain: design (M7f)

Plan `2026-10-22-ai-led-study.md` → owner decision 2026-10-24 (Decision log). Research: `docs/research/2026-10-24-brain-planned-practice.md` (cited as R§n). Builds on the M7 design (`2026-10-23-m7-brain-design.md`, rev 4, cited as M7 D*n*); it amends M7 D18 (records) and D19 (retention) on the owner's instruction, and nothing else there. ADR-0013 → Practice keeps owning the per-miscue rules; this note decides how the steps around the graded attempts are chosen and run. Mechanisms not in an ADR are marked **[beyond ADR]** with their provenance.

History: rev 2 answers the owner's review of rev 1 (2026-10-24): the Brain leads the practice instead of answering stateless single-step calls, orchestrated by pydantic-graph (R§2.6); the four open questions answered (R§3). Rev 3 (owner, 2026-10-24: "open everything up"): the graph becomes a hub around `BrainTurn`; the Brain may try first before modelling, speak its own checked lines, improvise hints and examples, reorder and revisit words, ask for meaning or a sentence, and end early. Only ADR-0013's per-miscue rules, the controls, the time cap, the budget and the content checks remain fixed (P5's hard rules).

Status: not reviewed. It touches privacy, egress, a new dependency, a new data shape and a loop inside an activity, so it is a risky design: codex, `code-plan-review` and a fresh Claude review it before code, and the prototype (step P2) runs before the ADR is written.

## Decisions

**P1 Three planners, one setting; the old one stays [beyond ADR, owner decision].** Learner setting `practice.planner`:
- `code`: today's ADR-0013 Practice, unchanged, in today's function (`activities.practise_errors`'s current body becomes `practise_errors_code`, untouched).
- `plan`: the Brain plans first (P3); the graph then runs the plan by a fixed script (`next_default`, P5) with no further Brain call.
- `plan_loop` (default): the Brain plans first (P3), **then leads every step** in the same conversation (P4); the plan is the first turn of that conversation, so every later choice is made knowing it.

Fallback is automatic and per level: no plan (no eligible backend, the ledger, the moment spent, a rejected plan) → `code` for this activity; a `BrainTurn` that cannot answer in time or within budget → `next_default` for that step, and the conversation continues at the next step. The activity's outcome records `planner_requested` and `planner_used`. ADR-0017 §9's arms concern sequencing and stay independent. Provenance: *original*; the levels *adapted* from M7's cascade with `degraded`.

**P2 Who owns what.** ADR-0013 → Practice gains a "Planned practice" subsection with P5's graph; its steps 2–6 (attempt budget, outcome classes, `confirmed` only with `evidence = acoustic`, skip, page turn, final status) are referenced, not restated. **Its step 1 is amended**: "Leafi shows the candidate's sentence; under `practice.planner = code` it then models the word at once (as before); under a Brain planner whether and when the word is modelled is the Brain's choice, so the learner may try first." ADR-0013 step 4's end conditions gain "the planner moves to another word or ends the practice" (P5's parked words). ADR-0017 §3.1's `practise_errors` row gains content `plan` (owner `brain` unless `practice.planner = code`) and §5.1 the purpose `practice_turn`. ADR-0018 gains the interests data class, the relaxed school condition and the retention changes (P6, P7). A new short ADR-0020 records the decision, the options and the privacy choices, and adopts pydantic-graph and pydantic-ai for this activity (P9).

**P3 The plan: the conversation's first turn [ADR-0017 §3.1 extended].** At construction, under the boundary's `next_activity` moment and M7 D14's per-boundary content cache (a re-offer reuses the plan and the conversation's first two messages). The first user message holds these sections (M7 D6's order; every leaf a `Text` with provenance, filtered per leaf by M7 D3 at every request, P4):

| Section | Content | Class |
|---|---|---|
| `page` | the page text, each target's sentence with ids | `page` |
| `targets` | `m<miscue_id>`: expected word, origin, Difficulty weight, ASR band, **heard word** | `page`; heard `learner` (withheld → category) |
| `history` | per word, last `practice.history_days` (30) days, ≤ 30 words: times missed, last heard, last outcomes | outcomes `system`; heard `learner` |
| `memory` | Difficulties, current learner notes, **interests** (P6) | `derived_from_learner` / `parent` |
| `policy` | age band, `practice.examples_generated`, `practice.echo`, the praise and no-guessing rules, the step vocabulary and its limits | `system` |

Output `PracticePlan`: `order` (a permutation of the rendered `m…` ids), per word `method` ∈ {`model_word`, `syllables`, `onset_rime`, `meaning_first`, `in_context`}, `hint` (≤ 150 chars), `examples` (≤ `practice.examples_generated`, default 3, range 0–5). Code checks, each failure dropping only its part (M7 D6's two levels): ids bound as M7 D15; each example contains the target word as a whole token after `norm`, ≤ 12 words, ≤ 100 chars, differs from the page sentence and the other examples, no URL. A plan with no valid word → `Rejected` → `code`. Age-appropriateness is not code-checkable: prompt rule plus a measured check, as M7 D20. Route: ADR-0017's `generate` row (`standard → deep` at `normal`), *untuned*; if the prototype's M4 misses the moment, P8 applies.

**P4 The Brain leads: a pydantic-ai `Agent` inside a pydantic-graph [beyond ADR; R§2.6 shape C].**

- **One conversation per activity.** `PracticeState.history` holds the `Agent`'s `message_history`; every `BrainTurn` node calls `agent.run(turn_prompt, message_history=state.history, output_type=legal_steps(state))` and appends the new messages. The Brain thus sees its plan, every step it chose, every result and every refusal, and chooses the next step — it leads; the graph only refuses what ADR-0013 forbids.
- **What the Brain may choose**: the `Step` union of P5, narrowed per turn to the members legal now. A turn may also carry one `say` line (P5's free-text check) spoken before the step. A choice outside the legal set (if the narrowing fails, or a stale history) is replaced by `next_default` and the next turn prompt says `refused: <code>` (M7 D4's codes plus `no_attempts_left`, `no_word`, `no_time`, `text_rejected`).
- **The model seam.** The `Agent` is built with `LeafiModel`, a `pydantic_ai.models.Model` subclass whose `request(messages, settings, params)` converts the message list into M7's `ModelRequest` and calls `brain_call(purpose = "practice_turn", …)`. So the tier walk (M7 D8, Leafi's own per-tier retries; no `FallbackModel`), egress `prepare` with the model-bound token (M7 D1), the budget per transmission (M7 D7), the audit row per call (M7 D11), the filler (M7 D12) and cancellation stay M7's; pydantic-ai contributes the conversation, typed output, output validation with re-ask (`retries=1`) and the tool/output schema. `api_schema` (M7 D6) still checks every schema it emits.
- **Provenance in the conversation.** Each text part Leafi adds (turn prompts, step results) is built from `Text` leaves and registered in `state.leaves[part_id]`; `LeafiModel` re-renders **every** part of the history from its leaves at **every** request, so the per-leaf filter (M7 D3) runs under the current settings: if `cloud.text` is switched off mid-activity, earlier heard words go out as categories in the next request. A part with no registered leaves (model output aside) is refused, fail-closed. Model responses get M7 D2's output provenance from what was sent.
- **Route and moments.** `practice_turn`: `fast → standard`, moment `feedback` (3 s / 6 s, ADR-0017 §5.2) minus the output reserve; `PER_CALL_S` fast 1.5 s, standard 2.5 s (*untuned*); filler at 0.8 s. Budget: `limits.practice_turns` (20 per activity, *untuned*; rev 3 has more step kinds per word) and the session ledger at `fast` 0.25 each; past either → `next_default` for the rest of the activity. Prompt cache: a breakpoint after the plan turn (stable for the activity), measured in M10.
- Provenance: graph-of-steps with an LLM node *adopted* from pydantic-graph's documented GenAI example (agent in a node, history in state); the legal-step narrowing and per-request re-render *original*.

**P5 The graph: a hub around `BrainTurn` [ADR-0013 → Practice, steps 1–2 when `planner ≠ code`; rev 3].** Every step returns to `BrainTurn`; nothing but the hard rules below fixes an order.

```
PracticeState: plan, words {mid: WordState}, current (mid | None), history, leaves, turns_left, outcomes
WordState: mid, used (count of practices rows of mid, any activity), done, shown, hints, examples, talk

Plan       → BrainTurn | End        # P3; rejected → the activity runs practise_errors_code
BrainTurn  → one Step | End         # plan_loop: agent.run (P4); plan mode, or no answer in time: next_default
every Step → BrainTurn              # a word that becomes done goes through Finish first

Steps (the Brain's vocabulary; "the word" = state.current):
  Focus(mid)           make a word current (any not-done word, in any order; a parked word may come back).
                       First time: its sentence on Faces (shown). Replaces rev 2's NextWord and Introduce.
  ModelWord(slow)      Leafi says the word (slowly, or at normal speed).
  Syllables            Leafi says the word in parts (onset–rime or syllables, from the plan or `WordInfo`).
  Hint(text | plan)    a hint from the plan, or a new one the Brain writes now (free-text check).
  Example(index | text) Leafi reads a plan example or a new one written now (example check of P3);
                       then Echo by practice.echo.
  Attempt              a graded try: ADR-0013 steps 2–5 exactly as today. Legal before any ModelWord
                       (the child tries first). The local feedback line is said at once.
  AskMeaning           "What do you think <word> means?" — listen ASK_S, never graded.
  UseInSentence        "Can you say a sentence with <word>?" — listen ASK_S, never graded.
  Say(text)            one line of the Brain's own (free-text check), e.g. encouragement or an explanation.
  Park                 leave the current word for now (it stays not-done; Focus can return to it).
  Finish               end the current word now (only after ≥ 1 attempt): ADR-0013 steps 4–6.
  EndPractice          end the activity (P5's end rule).

legal_steps(state): Attempt only while used < 2; Finish only with used ≥ 1; Focus only on not-done words;
                    any step but Focus/EndPractice needs a current word; teaching steps (ModelWord, Syllables,
                    Hint, Example, AskMeaning, UseInSentence, Say) only while the activity's time left allows
                    one (≈ 6 s each, untuned)
next_default(state): no current word → Focus(the plan's next not-done word) or EndPractice; else
                     ModelWord (if not yet) → Hint (if any) → Attempt → after fail or unclear: one Example
                     → Attempt → Finish
```

**Hard rules (code, never the Brain):**
1. ADR-0013's per-miscue rules: at most 2 graded attempts per miscue across activities; the outcome classes and `RETRY_MIN_CONF`; `confirmed` only from the acoustic scorer; the final status from every `practices` row (`_finish_candidate`). A word becomes done on `pass`, `skip`, `idle`, its second attempt, or `Finish`.
2. Controls at every listen (Attempt, Echo, AskMeaning, UseInSentence), handled by the harness: `stop` → the current word `unsure(skipped)`, the activity `stopped`; `skip` → the current word `unsure(skipped)`, then `BrainTurn`; page turn → `page_turned`, words stay `candidate`; `/back` → spoken no-op.
3. The end rule (on `EndPractice`, the 8-minute cap, the turn budget with no default left, or all words done): a word with ≥ 1 attempt goes through `Finish`; a word never attempted stays `candidate`, owned by the cycle, like a page turn (ADR-0013 → Page turns). So parking or ending early never loses or invents a status.
4. Nothing the child says in AskMeaning, UseInSentence or an unscored Echo is graded or changes a status; it is stored as an utterance (kind `practice_talk` / `practice_echo`, provenance `learner`) and enters the conversation as the child's words, filtered like any (P4).
5. **Free-text check** for `Hint(text)` and `Say(text)` [*original*]: ≤ 120 chars, ≤ 2 sentences, no URL, none of a fixed list of labels the praise rules forbid (`smart`, `clever`, `genius`, `stupid`, `lazy`, `bad`, `dumb`; ADR-0017 §6.1 "never smart"), no picture-guessing prompt (`picture`, `look at the`; research P2); surrogate names are mapped back locally before speaking; spoken with the turn's output provenance (M7 D2), so with `privacy.tts_learner_lines = local` by Kokoro. A failed line is dropped (`text_rejected`), the step itself still runs when it has a plan fallback. The check cannot judge tone or truth: the prompt states the rules and the measured check of P5 (owner present) reads a sample.
6. Budgets: the 8-minute activity cap, `limits.practice_turns`, the session ledger; past the turn budget, `next_default` runs to the end rule.

- The activity drives the run with `graph.iter(state=…)`: after each node it calls `s.checkpoint()` (the latch), so `stop`, a deadline or a lost lease ends the run between nodes; inside a node the activity's cancel scope cancels the awaited listen or Brain call (anyio, level-triggered). Each node commits its rows (`practices`, utterances, miscue status) in one transaction **before** returning, so a cut never loses a committed step and never commits half of one; ADR-0013 (l) holds with every planner (under a Brain planner "C:2" may also be a parked word; the end rule treats it the same). Nothing is persisted from the graph: pydantic-graph V2 has no persistence, and the rows are the record (resume after a crash: the miscues and their `practices` rows, as today).
- The local feedback line after an attempt is spoken before the next `BrainTurn`, so the child hears a reaction within the 1 s budget while the Brain decides.

**P6 Interests [beyond ADR; data class; migration 8; owner answer 3].** `learner_notes` gains `kind TEXT NOT NULL DEFAULT 'note' CHECK(kind IN ('note','interest'))`. Writers:
- a parent: `python -m leafi learner interests add|list|remove --learner N` and the settings page; provenance `parent`; kept until removed;
- the Brain, from the child's interactions: `extract_notes` (kind `interest`, `derived_from_learner`, citing activities like notes) and, during the session, a new record kind `interest` in `decide`'s `records` (≤ 100 chars, citing a rendered activity id; validated and written by `apply_records`, M7 D18 amended); Brain-written interests age out like notes.

Readers: P3's `memory` section, the settings page (parent sees and can delete Brain-written ones). `forget --learner` deletes them with `learner_notes`; `forget --session` deletes Brain-written interests citing only that session. Tests: `test_migration_8`, `test_privacy` (a parent interest with `CLOUD_PARENT_TEXT` off withheld from the cloud), `test_extract_notes` and `test_records` (interest kind).

**P7 Privacy [ADR-0018 amended; owner answers 1 and 2].**
- **School no longer required (answer 1).** `LearnerPrivacy.cloud_text_allowed` drops `school_answered`; `egress._gate`'s "no school answer" reason goes; ADR-0018 §3's "enrolment is not complete without it" becomes "Leafi asks; an unanswered school is not replaced unless the name detector finds it"; ADR-0016's `household-terms` check becomes a warning ("a school is unknown, so it cannot be replaced"), not a gate; `doctor`'s `schools` line and `alerts.py`'s text reworded; `identify.ask_school` stays. Recorded as the owner's choice against the recommendation (R§3.1). Tests: `test_privacy` (unanswered school, `cloud.text` on → sent pseudonymised by the lists and the detector), `test_learner_privacy`.
- **Payloads.** Every plan and turn goes through M7's filter and egress like any Brain call; decisions 2–5 are today's rules (R§2.1). `security.md`'s egress table gains `generate:practice_plan` and `practice_turn`, and interests under `derived_from_learner` / `parent`. `tests/test_privacy.py`: a plan and three turns through `prepare` for `cloud.text` on (surrogates, heard word present), off and guest (heard words as categories, notes and interests withheld; page text and expected words still sent, so a guest gets a plan without history), `cloud.text` switched off between two turns (P4's re-render), no audio reference in any body.
- **Retention (answer 2, decision 6).** `brain_calls`, `decision_records` and evaluation transcripts are all kept until a parent or admin deletes them: M7 D19's 30-day pruning of `decision_records` is removed and the evaluation transcripts' 30 days in `security.md` and ADR-0018 §4.3 becomes "until deleted". Deletion entrance: `python -m leafi forget --brain-records --learner N [--before DATE] [--yes]` deletes the `brain_calls` and `decision_records` rows whose source learners name N, and that learner's files under `data/evals/`, keeping the reading history; `--learner` as today deletes everything. Console button in M10's privacy pass (red, asks first, takes the learner).

**P8 Plan-ahead, only if measured necessary [conditional].** If the plan turn misses the `next_activity` moment (prototype M4), the boundary starts it concurrently with `decide` when `practise_errors` is in the menu, inside the same `with_filler` task group and moment; an unused plan has been charged (as M7 D14's refused offers). Not built unless M4 fails.

**P9 Dependencies [beyond ADR; a new dependency].** `pydantic-ai-slim` (no extras: the model is `LeafiModel`, so no provider SDK is pulled in by it) and `pydantic-graph`, both pinned to the exact version the prototype passes (2.61.0 today; upgrades on purpose, with M1–M8 rerun). `PYDANTIC_AI_NO_BANNER=1` and instrumentation off are set in `leafi.cli` beside the other environment settings; `pydantic_ai` is imported only after `import leafi` (TD-1: it imports `httpx`). The libraries research's trigger ("choose it if the Brain grows agentic tool loops") is met by P4. Used only by `practise_errors` under `plan` / `plan_loop`; the session loop stays comb1's hand-written loop (owner decision 2026-10-23). If the prototype fails M8 (no per-run `output_type`, or no custom `Model` seam), the fallback is the same graph with the `BrainTurn` node calling `brain_call` directly and Leafi keeping the history list itself; ADR-0020 records which.

## Settings (learner, `harness/settings.SPEC`, settings page)

| Key | Default | Range |
|---|---|---|
| `practice.planner` | `plan_loop` | `code` / `plan` / `plan_loop` |
| `practice.examples_generated` | 3 | 0–5 |
| `practice.echo` | `unscored` | `off` / `unscored` / `as_attempt` |
| `practice.history_days` | 30 | 0–365 |
| `limits.practice_turns` | 20 | 0–40 (0 behaves as `plan`) |

**Help text (settings page and `SPEC` docstring), owner answer 4.** Each key carries the text below; the settings page shows it beside the control.

- `practice.planner` — "How Leafi practises the words your child misread. `code`: the original fixed routine: show the sentence, say the word slowly, and give up to two tries. `plan`: the AI first plans each word (a hint, example sentences, the order), then Leafi follows that plan step by step without asking the AI again. `plan_loop` (default): the AI plans first, then leads the practice from how your child is doing: it may let your child try a word before hearing it, split it into parts, give or invent hints and example sentences, ask what the word means or for a sentence with it, come back to a word later, say a few words of its own (checked by Leafi for length, links and forbidden labels such as 'smart' or 'stupid'), or stop early when your child seems tired. Whatever is chosen, a word gets at most two graded tries, saying 'skip' always moves on, and only the pronunciation checker can mark a word as truly mispronounced. If the AI is slow or unavailable, Leafi falls back to the fixed routine on its own."
- `practice.examples_generated` — "How many example sentences the AI writes for each word in its plan (0–5). Under `plan_loop` it may also write new ones during the practice. More examples mean more repetition. How many are actually used depends on the time left in the activity (8 minutes at most) and the session's AI budget, so not every example is always read."
- `practice.echo` — "What happens after Leafi reads an example sentence. `off`: nothing; Leafi goes on. `unscored` (default): your child may repeat the sentence; Leafi listens and keeps the recording's text for its records, but the repetition is not a test: it never counts as one of the two tries and never changes whether the word is marked as learned or misread. `as_attempt`: the repetition is graded like a try (the word must be heard in it) and counts as one of the two tries, so an example can end the practice of that word early, for better or worse. Recordings themselves are never kept and never leave this computer."
- `practice.history_days` — "How many days of your child's earlier reading mistakes the AI sees when it plans (0 = none). The words your child said are sent to the AI service only when this learner's 'cloud text' setting is on, with names and the school replaced."
- `limits.practice_turns` — "How many times per practice activity the AI may decide the next step (each one is a short request to the AI service and counts against the session budget). When they are used up, Leafi continues with the plan by itself. 0 means: plan only."

## Evaluation

Per activity: `planner_used`, turns used, refusals; per miscue: final status, attempts, echoes and their outcome class, time. Across sessions: the same expected word missed again within 14 days (a transfer measure, *original*). `python -m leafi report practice` compares planners per learner; the owner switches `practice.planner` to compare in practice. No conclusion without effect size and sample size (ADR-0017 §9's line).

## Steps

- **P0** (with rev 1/rev 2): Decision log, research, this note.
- **P1** review round: codex (`gpt-6-astra`), `code-plan-review`, a fresh Claude, in parallel on `reviews/prompts/practice-planning.md`; compared.
- **P2** prototype `scripts/prototypes/practice/` (R§4: M1–M8; shape C, and the SDK tool runner for comparison); real-Claude latency needs `ANTHROPIC_API_KEY` with the owner present.
- **P3** ADR-0020; ADR-0013, ADR-0016, ADR-0017, ADR-0018 and `security.md` amended (P2, P6, P7); M7 design D18/D19 amended in its next revision.
- **P4 = M7f**, after M7e (needs M7a's call layer, M7c's async construction and `generate` kinds, M7d's `extract_notes` and `apply_records`, M7e's `decision_records`):
  - P7's school change can land earlier, alone, with its tests (it touches only `privacy/` and the docs), if the owner wants it before M7;
  - migration 8 and interests (P6); `LeafiModel`, the graph and its nodes (P4, P5); `practise_errors` dispatching by `practice.planner`; settings with their help text; `forget --brain-records`; `report practice`;
  - tests: `test_practice_plan` (each check), `test_practice_graph` (illegal steps replaced and reported; Attempt before ModelWord; a third Attempt refused; Park then Focus back keeps the attempt count; EndPractice with an attempted and an unattempted word (the end rule); AskMeaning and UseInSentence never graded; ADR-0013 (l) under all three planners; echo in each `practice.echo` mode; stop, skip and page turn during each listening step and during a `BrainTurn`; the turn budget running out), `test_practice_text` (the free-text check: each forbidden label, length, URL, a picture prompt, surrogate mapped back), `test_leafi_model` (history re-rendered from leaves; an unregistered part refused; tier walk on `invalid` / `timeout`), `test_practice` unchanged and green for `code`, `test_privacy` (P7), `test_cancellation` (stop during a `BrainTurn`), `test_forget` (`--brain-records`).
- **P5** owner present: real sessions per planner; the age-appropriateness check (M7 D20 style); M10 measures turn latency on the camera Mouth.

Not in M7f: Ollama or magpie as practice backends (their gates), plan-ahead unless P2's M4 fails, the console button (M10), pydantic-graph anywhere outside `practise_errors`.
