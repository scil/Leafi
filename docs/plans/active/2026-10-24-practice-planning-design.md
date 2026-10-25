---
status: proposed
date: 2026-10-24
revision: 4
---

# Practice planned and led by the Brain: design (M7f)

Plan `2026-10-22-ai-led-study.md` → owner decisions 2026-10-24 (Decision log). Research: `docs/research/2026-10-24-brain-planned-practice.md` (cited as R§n). Builds on the M7 design (`2026-10-23-m7-brain-design.md`, **rev 9**, cited as M7 D*n*), which already carries what rev 3 had to add: the multi-turn `Turn` with assistant provenance (D5, C1), the second breakpoint on the plan (D6, C3), `practice_turn` as a purpose of its own routed `fast` only (B3, B4), two fixed `practice_turn` schemas (B1), the conversation ending when `cloud.text` is switched off (B2), records kept until deleted and `forget --brain-records` (D19, A2), and the relaxed rejection line (D4, owner 2026-10-24). This note amends M7 only where listed under P10. ADR-0013 → Practice keeps owning the per-miscue rules; this note decides how the steps around the graded attempts are chosen and run. Mechanisms not in an ADR are marked **[beyond ADR]** with their provenance.

History: rev 2 answered the owner's review of rev 1 (the Brain leads one conversation, orchestrated by pydantic-graph). Rev 3 opened the practice up (a hub around `BrainTurn`; P5's hard rules are all that stays fixed). **Rev 4** answers round 1 (`reviews/2026-10-24-practice-design-round-1-comparison.md`, themes T1–T26, cited as T*n*) and the owner's six answers of 2026-10-24: keep the pydantic-ai `Agent` (T4, against the recommendation, for the features to come), relax M7 D4, send the school when unknown even without the detector (T6), send the child's free speech as a transcript (T18), `stop` keeps an earlier fail (T10), `as_attempt` with `evidence = none` (T8), no re-offer after `EndPractice` and planner-ended words out of the comparison (T17). The upstream check behind the T4 answer (pydantic-ai 2.61.0 and main, 2026-10-24) is in the Decision log. The table at the end maps each theme to its answer.

**Migration number:** this design's "migration 8" is **migration 9** (M5e's ADR-0021 lands as 7, M7's `item_status_events` as 8); renumbered in rev 5.

**Superseded in part (owner, 2026-10-24, after rev 4):** egress now redacts by content only (plan Decision log). P4's stamps, the fail-closed guard and the per-request re-render, the `cloud.text` cases of P1, P5 rule 4 and P7, and P6's `[N, 0]` encoding no longer apply; rev 5 rewrites them once the content-only egress design exists.

Status: rev 4 not reviewed. Per `AGENTS.md`, an increment round with one reviewer (codex, or a fresh Claude while its quota is out); the privacy-only choices (P7) need no review (owner, 2026-10-24). The prototype (step P2) runs before the ADR is written.

## Decisions

**P1 Three planners, one setting; the old one stays [beyond ADR, owner decision].** Learner setting `practice.planner`:
- `code`: today's ADR-0013 Practice in today's function (`activities.practise_errors`'s current body becomes `practise_errors_code`), changed only by the `stop` cell of P5 rule 2 (T10).
- `plan`: the Brain plans first (P3); the graph then runs the plan by the fixed script (`next_default`, P5) with no further Brain call.
- `plan_loop` (default): the Brain plans first, **then leads every step** in one conversation (P4); the plan is that conversation's first turn.

Fallback, per level, never a rejection (T14): no plan (no eligible backend, the ledger, the moment spent, a rejected plan) → construction succeeds with `code` content and the activity runs `practise_errors_code`; a `BrainTurn` refused, unanswered in time, out of budget or with an unstamped part (P4) → `next_default` for that turn, and the next turn asks again; a privacy change during the activity (B2) or the turn budget spent → `next_default` for the rest of the activity. The activity's outcome records `planner_requested`, `planner_used` (the weakest level that ran a step) and `planner_ended` (P5 rule 3). ADR-0017 §9's arms concern sequencing and stay independent. Provenance: *original*; the levels *adapted* from M7's cascade with `degraded`.

**P2 Who owns what.** ADR-0013 → Practice gains a "Planned practice" subsection with P5's graph; its steps 2–6 are referenced, not restated. Amended there:
- step 1: "under `practice.planner = code` Leafi models the word at once; under a Brain planner whether and when it is modelled is the Brain's choice, so the learner may try first (P5 TryFirst)";
- step 3: "an echo graded under `practice.echo = as_attempt` is an attempt with `evidence = none`" (T8);
- step 4's end conditions gain "the planner moves to another word or ends the practice";
- Control precedence, `stop`: "the current word → `practice_final` over its rows; with no row, `unsure(skipped)`" (T10, every planner);
- the ordering sentence ("model, then retry") gains "under `code`" (T26).

ADR-0017 §3.1's `practise_errors` row gains content `plan` (owner `brain` unless `practice.planner = code`); §5.1 records `practice_turn` (M7 B3, B4) and §5's "schemas constant within a session per (purpose, tier)" gains the exception of `practice_turn`'s two fixed schemas (M7 B1). ADR-0018 gains the interests data class (P6), the learner free-speech row (P7), the school's stated cost (P7) and the record volume (P7). A new short ADR-0020 records the decision, the options and the privacy choices, and adopts pydantic-graph and pydantic-ai for this activity (P9).

**P3 The plan: lean, started early, the conversation's first turn [ADR-0017 §3.1 extended].** The plan call (`generate:practice_plan`) starts at the boundary **concurrently with `decide`** whenever `practise_errors` is in the menu (rev 3's conditional P8, now the default, T13), inside the same `with_filler` task group and the `next_activity` moment; construction awaits it until the moment ends; a plan unused because another activity was chosen has been charged (as M7 D14's refused offers). Construction binds it by id intersection: plan entries whose `m…` id is still a candidate are kept, the rest dropped; a candidate the plan lacks gets `next_default`'s scripted steps. The first user message holds these sections (M7 D6's order; every leaf a `Text` with provenance, filtered per leaf by M7 D3):

| Section | Content | Class |
|---|---|---|
| `page` | the page text, each target's sentence with ids | `page` |
| `targets` | `m<miscue_id>`: expected word, origin, Difficulty weight, ASR band, **heard word** | `page`; heard `learner` (withheld → category) |
| `history` | per word, last `practice.history_days` (30) days, ≤ 30 words: times missed, last heard, last outcomes | outcomes `system`; heard `learner` |
| `memory` | Difficulties, current learner notes, **interests** (P6) | `derived_from_learner` |
| `policy` | age band, `practice.examples_generated`, `practice.echo`, the praise and no-guessing rules, the step vocabulary and its limits, two worked turns | `system` |

Output `PracticePlan`, kept lean so `fast` can write it (T13): `order` (a permutation of the rendered `m…` ids); per word `method` ∈ {`model_word`, `syllables`, `onset_rime`, `meaning_first`, `in_context`}, `hint` (≤ 150 chars), `parts` (for `syllables` / `onset_rime`: 2–4 strings whose concatenation equals the word after `norm`, else dropped and `method` falls back to `model_word`; T23), `examples` (≤ `practice.examples_generated`, default 3, range 0–5). Code checks, each failure dropping only its part (M7 D6's two levels): ids bound as M7 D15; every hint and example passes P5 rule 5; each example contains the target word as a whole token after `norm`, ≤ 12 words, ≤ 100 chars, differs from the page sentence and the other examples. A plan with no valid word → `Rejected` → `code` (P1). Age-appropriateness is not code-checkable: prompt rule plus a measured check, as M7 D20. Route: `fast → standard` at every difficulty (*untuned*, like O1's `decide` route; M10 measures). P2's M4 measures whether five words fit the moment; if not, `examples_generated` caps lower on `fast`, never the moment.

**P4 The Brain leads: a pydantic-ai `Agent` inside a pydantic-graph, every message stamped [beyond ADR; R§2.6 shape C; owner T4].**

- **One conversation per activity.** `PracticeState.history` holds the `Agent`'s `message_history`; each `BrainTurn` node calls `agent.run(turn_prompt, message_history=state.history, output_type=NativeOutput(schema))` and appends `result.new_messages()`. The Brain sees its plan, every step it chose, every result and every refusal. The `Agent` has no instructions, no tools and no history processors: the system text is M7's frozen `PROMPT_VERSION` text, added by `LeafiModel`.
- **Two fixed schemas, legality in code (T1, M7 B1).** The output is `BrainReply{say: str | None, steps: list[Step]}` with `steps` 1–4 long, ending at the first listening step (Attempt, Echo, AskMeaning, UseInSentence) or at Park, Finish or EndPractice (T13: one Brain call per listen, not per step). `schema` is `full` (every Step kind) or `wrap_up` (`Focus`, `Attempt`, `Finish`, `Park`, `EndPractice`): `wrap_up` from the turn when the time left is under 90 s or the turns left under 3 (*untuned*); both built once per `PROMPT_VERSION`, byte-stable, checked by `api_schema` (M7 D6). The legal set is rendered as text in the turn prompt; `legal_steps` (P5) checks each step in order, and the first illegal one and every later step are replaced by `next_default`, reported in the next turn prompt as `refused: <code>` (M7 D4's codes plus `no_attempts_left`, `no_word`, `no_time`, `text_rejected`, `talk_cap`). `NativeOutput` (the provider's JSON-schema output) keeps tool calls and tool returns out of the history (*unverified*: P2's M8).
- **The model seam.** `LeafiModel`, a `pydantic_ai.models.Model` subclass, is the only place a request leaves: `request(messages, settings, params)` renders M7's `ModelRequest` (`purpose = "practice_turn"`, `turns`) from the stamps below and calls `brain_call`. The tier walk, the relaxed rejection line (M7 D4, D8), egress `prepare` with the model-bound token (D1), the budget per transmission (D7), the audit row (D11, P7's delta), the filler (D12) and cancellation stay M7's.
- **Stamps carry provenance in pydantic-ai's own messages (T2, T3) [beyond ADR, *original*; the fields *adopted* from pydantic-ai 2.61].** Leafi writes every user message as `UserPromptPart(content=[TextContent(text, metadata={"leafi": leaf})…])`, one `TextContent` per `Text` leaf (value, provenance class, sources, substitute). `LeafiModel` returns `ModelResponse(parts=[TextPart(json)], metadata={"leafi": {"reply": <the validated BrainReply>, "provenance": <M7 D2's output provenance>}})`. At every request `LeafiModel` renders the user `Turn`s **only from the stamped leaves** (re-filtered per leaf by M7 D3 under the current settings) and the assistant `Turn`s **only from the stamped validated reply** (canonical JSON, D2 provenance), never from the parts' text. **Fail-closed guard:** a part without a Leafi stamp — a `SystemPromptPart`, a `ToolCallPart` or `ToolReturnPart`, a `RetryFeedbackPart`, a `TextContent` without metadata, a response whose metadata a merge dropped — refuses the request before `prepare` (`unstamped_part`, logged with the part kind and the pydantic-ai version): the turn runs `next_default`, so a lost stamp is a fallback, never a leak. The history merge is patched only if P2's M8 shows stamps lost in normal use; the patch is pinned with the version (P9).
- **One re-ask owner (T5).** The `Agent` runs with `retries={'output': 0}`. `brain_call` validates with the same Pydantic model and walks the tiers, so `LeafiModel` returns only a validated reply and pydantic-ai's own validation always passes; if the library still re-asks (0 refused, or a validator mismatch), its `RetryFeedbackPart` is unstamped and the guard turns it into `next_default`. A turn is one `agent.run`, one model request, one `brain_call`: at most one transmission per route entry, plus the mediator's retry, each charged by M7 D7; `limits.practice_turns` counts `brain_call`s.
- **Route and moments (M7 B4).** `practice_turn` routes `fast` only until M10; moment `feedback` (3 s PC, 6 s camera) minus the output reserve; `PER_CALL_S[practice_turn][fast]` 1.5 s (*untuned*). **Order around an attempt (T13):** the local feedback line is spoken at once and the `BrainTurn` starts concurrently with it; the filler's 0.8 s clock starts when the feedback line ends; a reply that arrives while the line plays waits for it (one speaker). Budget: `limits.practice_turns` (20 per activity, *untuned*) and the session ledger at `fast` 0.25 each; past either → `next_default` for the rest of the activity. Prompt cache: the second breakpoint after the plan turn (M7 D6, C3), measured in M10.
- **A privacy change ends the conversation (T3, M7 B2).** When the learner's `cloud.text` is switched off, or `admit` refuses a turn for a household or learner privacy-version change, the conversation ends and the rest of the activity runs `next_default` (`planner_used = plan`). So within one conversation every earlier turn renders to the same bytes, which P7's delta storage relies on. Any other refusal ends only that turn.
- Provenance: graph-of-steps with an LLM node *adopted* from pydantic-graph's documented GenAI example (agent in a node, history in state); the stamps, the guard and the step sequence *original*.

**P5 The graph: a hub around `BrainTurn` [ADR-0013 → Practice, steps 1–2 when `planner ≠ code`].** Every step sequence returns to `BrainTurn`; nothing but the hard rules below fixes an order.

```
PracticeState: plan, words {mid: WordState}, current (mid | None), history, turns_left, voice, outcomes
WordState: mid, used_total (practices rows of mid, any activity), used_here (rows in this activity),
           modelled, last_evidence, last_score, shown, hints, examples, talk (non-attempt steps since the
           last attempt), cursor (next_default's position), done, planner_ended

Plan       → BrainTurn | End        # P3; no plan → the activity runs practise_errors_code
BrainTurn  → steps → BrainTurn | End  # plan_loop: agent.run (P4); plan mode or no usable reply: next_default
a word that becomes done goes through Finish first

Steps (the Brain's vocabulary; "the word" = state.current):
  Focus(mid)           make a not-done word current (any order; a parked word may come back). Faces clears
                       the previous word's sentence and shows this one with the target highlighted (shown).
  ModelWord(slow)      Leafi says the word (slowly or at normal speed); modelled = true.
  Syllables            Leafi says the plan's parts (P3); without parts the step is illegal.
  Hint(text | plan)    a plan hint, or one written now.
  Example(index | text) Leafi reads a plan example or one written now; then Echo by practice.echo.
  Attempt              a graded try, ADR-0013 steps 2–5. Before modelled it is TryFirst: the fixed line
                       practice_try ("Can you read the highlighted word?") never says the word, and the
                       target's ASR hotword is off until modelled (T11). The local feedback line follows.
  AskMeaning           "What do you think <word> means?" — listen ASK_S, never graded.
  UseInSentence        "Can you say a sentence with <word>?" — listen ASK_S, never graded.
  Say(text)            one line of the Brain's own.
  Park                 leave the current word for now (not done; Focus can return to it).
  Finish               end the current word (only with used_here ≥ 1): ADR-0013 steps 4–6, with the word's
                       last_evidence and last_score (T12).
  EndPractice          end the activity (rule 3).

legal_steps(state): Attempt only while used_total < 2; Finish only with used_here ≥ 1; Focus only on not-done
                    words; any step but Focus / EndPractice needs a current word; teaching steps (ModelWord,
                    Syllables, Hint, Example, AskMeaning, UseInSentence, Say) only while the time left allows
                    one (≈ 6 s each, untuned) and talk < 3 (T16); Syllables only with plan parts
next_default(state): no current word → Focus(the plan's next not-done word) or EndPractice; else by the
                     word's plan method (T23): model_word → ModelWord; syllables / onset_rime → Syllables;
                     meaning_first → AskMeaning, then ModelWord; in_context → Example, then ModelWord;
                     then Hint (if any) → Attempt → after fail or unclear: one Example → Attempt → Finish;
                     every step it proposes is filtered by legal_steps and skipped when illegal, and it ends
                     in Finish or EndPractice, so it always terminates (tested: next_default ⊆ legal_steps)
```

**Hard rules (code, never the Brain):**
1. ADR-0013's per-miscue rules: at most 2 graded attempts per miscue across activities; the outcome classes and `RETRY_MIN_CONF`; `confirmed` only from the acoustic scorer; the final status from every `practices` row (`_finish_candidate`). A word becomes done on `pass`, `skip`, `idle`, its second attempt, or `Finish`.
2. Controls at every listen, handled by the harness. **`stop`** → the activity `stopped`; the current word gets `practice_final` over its rows, `unsure(skipped)` with none (T10: a revisited word with an earlier fail stays `unsure(disagreed)`, keeping the evidence); other words are left to `close_cycle`. **`skip`** applies to the word current when the learner finished saying it (M7 D21; practice prompts carry `("act", aid, "practice", mid)`), also during a `BrainTurn`, a teaching step or a filler (T15): that word `unsure(skipped)` as today, then `BrainTurn`. Page turn → `page_turned`, words stay `candidate`. `/back` → spoken no-op. In AskMeaning and UseInSentence only the control words are controls; "yes" or "no" there is an answer (T26).
3. **The end rule** (on `EndPractice`, the 8-minute cap, the turn budget with no default left, or all words done), counted **in this activity** (T12): a word with `used_here ≥ 1` goes through `Finish`; a word with `used_here = 0` stays `candidate`, owned by the cycle, like a page turn (ADR-0013 → Page turns). After a Brain-chosen `EndPractice`, `practise_errors` is not offered again in this cycle (T17). A word the Brain finished (`Finish` or the end rule after `EndPractice`) with one attempt that was not `pass` is marked `planner_ended` in the activity outcome, and the planner comparison leaves it out (T17).
4. **Ungraded speech** (AskMeaning, UseInSentence, an unscored Echo) never changes a status. It is stored as an utterance of kind `practice_talk` / `practice_echo` (migration 8, P6), provenance `learner`, and enters the conversation as the child's transcript (owner T18): sent when the learner's `cloud.text` allows it, otherwise its substitute `{words: n, target word used: yes|no}` (M7 D3).
5. **One free-text check on every spoken Brain string** (plan hints and examples, `Hint(text)`, `Example(text)`, `Say(text)`, the `say` line) [*original*; T16]: ≤ 120 chars (examples ≤ 100 and ≤ 12 words), ≤ 2 sentences, no URL, no `?` (questions are the fixed AskMeaning and UseInSentence lines only, so the Brain cannot ask personal ones), none of a fixed list as whole tokens after `norm` (`smart`, `clever`, `genius`, `stupid`, `lazy`, `bad`, `dumb`, `silly`, `wrong`, `mistake`, `incorrect`, `error`, `fail`, `failed`; ADR-0017 §6.1 "never smart", ADR-0013's "let's practise", never "wrong"), the current target word exempt; no picture-guessing prompt (`picture`, `look at the`); before the word is modelled, no line names it (TryFirst). Surrogate names are mapped back locally before speaking; spoken with the reply's output provenance (M7 D2), so with `privacy.tts_learner_lines = local` by Kokoro. A failed string is dropped (`text_rejected`); the step still runs when it has a plan fallback. The check cannot judge tone, truth or phonics: the prompt states the rules, and D20's measured checks gain the injection cases (P10).
6. **Echo.** Under `practice.echo = unscored` an echo is rule 4's speech. Under `as_attempt` it is graded only while `used_total < 2`: the alignment decides `pass` / `fail` / `unclear` from whether the word is heard in the echo, `evidence = none` (never scored acoustically, so never `confirmed`), and it consumes an attempt (T8).
7. Budgets: the 8-minute activity cap, `limits.practice_turns`, the session ledger; past the turn budget `next_default` runs to the end rule.

**Running the graph.** The activity drives it with `graph.iter(state=…)`: after each node it calls `s.checkpoint()` (the latch), so `stop`, a deadline or a lost lease ends the run between nodes; inside a node the activity's cancel scope cancels the awaited listen or Brain call (anyio, level-triggered). In each node every await (the listen, `_score` in its executor, TTS) comes first and the writes (`practices`, utterance, miscue status) follow in one synchronous transaction (T22: today `_store_utterance` precedes `await _score`; the node reorders it), so a cut never commits half a step. Exception groups from the graph are unwrapped at the graph boundary, so `Terminal` and cancellation keep M6's mapping to the latch's status (T22). ADR-0013 (l) holds with every planner. The TTS voice is fixed for the activity at its start (T26). Nothing is persisted from the graph: pydantic-graph has no persistence, and the rows are the record.

**P6 Interests and migration 8 [beyond ADR; data class; owner answer 3].** Migration 8 (schema 7 → 8, after M7's 7):
- `learner_notes` gains `kind TEXT NOT NULL DEFAULT 'note' CHECK(kind IN ('note','interest'))`;
- `utterances` is rebuilt (SQLite cannot alter a CHECK) with `practice_talk` and `practice_echo` in its `kind` CHECK (T9);
- `egress_log`'s purpose CHECK and the destinations' purpose sets gain `practice_turn` (M7 B3).

Writers of interests:
- a parent: `python -m leafi learner interests add|list|remove --learner N` and the settings page; stored as `derived_from_learner` with sources `[N, 0]` (M7 D2's mixed encoding, source `0` the parent), so `_gate` withholds it like the learner's own text when `cloud.text` is off (T7); kept until removed and excluded from ageing (T21);
- the Brain, from the child's interactions: `extract_notes` (kind `interest`, `derived_from_learner`, citing activities; the post-session observation renders the session's `practice_talk` utterances as its input) and a record kind `interest` in `decide`'s `records` (≤ 100 chars, citing a rendered activity id; M7 D18 amended, P10); both age out like notes; neither writes for a guest (T21).

Readers filter on `kind` (T21): P3's `memory` section takes both; `decide`'s `memory`, `extract_notes`' existing-notes input and every other notes reader take `kind = 'note'`; the settings page shows both, and a parent can delete Brain-written ones. `forget --learner` deletes them with `learner_notes`; `forget --session` deletes Brain-written interests citing only that session. Tests: `test_migration_8` (each change; the rebuild keeps every row and index), `test_privacy` (a parent interest withheld for a learner with `cloud.text` off, with `CLOUD_PARENT_TEXT` on), `test_extract_notes` and `test_records` (interest kind, guest refused).

**P7 Privacy [ADR-0018 amended; owner answers 1, 2, T6, T18].**
- **School (owner T6: send anyway).** The relaxation landed in M7a-3 (`31b1466`): an unanswered school no longer keeps a learner's words local. Rev 4 states its cost in ADR-0018 §3, as the owner's choice against the recommendation: an unanswered school leaves verbatim when the name detector is `off` or its model is missing, and even when it is ready it misses lower-case names (probe, round 1: "st marys school", "riverside primary", "oakfield" → nothing), which typed lines and rule 4's free speech make common. Sites still saying otherwise are reworded: `cli.py`'s setup text ("a learner without one keeps their own words off the cloud"), `remove_term`'s effect line (adds "and their school's name may now be sent"), `doctor.py`'s `schools` purpose line. `test_privacy` records the known limits as cases: a lower-case school with the detector ready, and any school with the detector off, both sent verbatim for a learner with no answer.
- **Payloads.** Every plan and turn goes through M7's filter and egress. `security.md`'s egress table gains `generate:practice_plan`, `practice_turn`, interests under `derived_from_learner`, and **a row for the child's free speech** (owner T18): the transcript of AskMeaning, UseInSentence and echoes, which may include other voices in the room, sent with `practice_turn` when `cloud.text` allows it, kept until deleted; the settings page's `cloud.text` help gains that line. `tests/test_privacy.py`: a plan and three turns through `prepare` for `cloud.text` on (surrogates, heard word and transcript present), off and guest (heard words and transcripts as substitutes, notes and interests withheld; page text and expected words still sent), `cloud.text` switched off between two turns (the conversation ends; the next request is never prepared), a stamp removed from one part (refused before `prepare`), no audio reference in any body.
- **Retention.** Records are kept until deleted (M7 D19, A2); `forget --brain-records` is M7 D19's, which also selects by `session_id` and is fenced (T20). M7f adds that it deletes the learner's evaluation transcripts under `data/evals/` (files, still; M7 D19 moved only decision records into the database), and `--before` compares each file's recorded session date.
- **Volume (T19).** A `practice_turn` `brain_calls` row stores the **delta**: the turns new since the previous `practice_turn` row of the same activity, plus `prev_call_id`; the full request is the chain. P4's rule that a privacy change ends the conversation keeps earlier turns byte-identical, so the chain is exact. With it an activity stores ≈ 20–40 KB instead of 0.3–0.5 MB; the figure goes into ADR-0018 §4.3.

**P8 Plan-ahead.** Folded into P3 (default since rev 4).

**P9 Dependencies [beyond ADR; a new dependency].** `pydantic-ai-slim` (no extras: the model is `LeafiModel`, so no provider SDK is pulled in) and `pydantic-graph`, both pinned to the exact version the prototype passes (2.61.0 today). An upgrade is on purpose and reruns the **contract test** `test_pydantic_ai_contract`: stamps survive two turns, a run with a forced invalid reply, a cancelled run and a history merge; `NativeOutput` adds no tool parts; `retries={'output': 0}` is accepted; an unstamped part is refused. `PYDANTIC_AI_NO_BANNER=1` and instrumentation off are set in `leafi.cli`; `pydantic_ai` is imported only after `import leafi` (TD-1: it imports `httpx`). `test_netguard` runs a full mock practice with pydantic-ai imported and asserts no socket (logfire, opentelemetry, price data) (T25). `test_architecture` confines `pydantic_ai` and `pydantic_graph` imports to `leafi/study/practice/` (T25). Used only by `practise_errors` under `plan` / `plan_loop`; the session loop stays Combination 1 (M7 A5). If the prototype fails M8, the fallback is the same graph with `BrainTurn` calling `brain_call` directly over a Leafi-owned `Turn` list; `test_practice_graph` runs against both through one `TurnSource` seam, so the fallback has the same contract (T25); ADR-0020 records which.

**P10 Amendments to the M7 design (in its next revision; T4).**
- D4: done (owner, 2026-10-24).
- D11: a `practice_turn` row stores the delta with `prev_call_id` (P7).
- D18: `decide`'s records gain kind `interest`; `PROMPT_VERSION` moves, so the `decide` schema stays byte-stable per version (P6).
- D20: the measured checks gain a page asking for a scary story, an AskMeaning answer asking the Brain to say a rude word, and a learner asking where Leafi lives, each run against `practice_turn` (T16).
- D21: the owner table gains the practice prompts and their `mid` (P5 rule 2).
- Nothing else: D5, D6 and D8 already carry multi-turn turns, the breakpoint, the schemas and the route.

## Settings (learner, `harness/settings.SPEC`, settings page)

| Key | Default | Range |
|---|---|---|
| `practice.planner` | `plan_loop` | `code` / `plan` / `plan_loop` |
| `practice.examples_generated` | 3 | 0–5 |
| `practice.echo` | `unscored` | `off` / `unscored` / `as_attempt` |
| `practice.history_days` | 30 | 0–365 |
| `limits.practice_turns` | 20 | 0–40 (0 behaves as `plan`) |

**Help text (settings page and `SPEC` docstring), owner answer 4; reworded in rev 4 (T24).**

- `practice.planner` — "How Leafi practises the words your child misread. `code`: the original fixed routine: show the sentence, say the word slowly, and give up to two tries. `plan`: the AI first plans each word (a hint, example sentences, the order), then Leafi follows that plan step by step without asking the AI again. `plan_loop` (default): the AI plans first, then leads the practice from how your child is doing: it may let your child try a word before hearing it, split it into parts, give or invent hints and example sentences, ask what the word means or for a sentence with it, come back to a word later, say a few words of its own (checked by Leafi for length, links, questions and forbidden words such as 'smart', 'stupid' or 'wrong'), or stop early when your child seems tired. Whatever is chosen, a word gets at most two graded tries, saying 'skip' always moves on, and only the pronunciation checker can mark a word as truly mispronounced. If the AI is slow or unavailable, Leafi continues by itself with the plan, or with the fixed routine when there is no plan."
- `practice.examples_generated` — "How many example sentences the AI writes for each word in its plan (0–5). Under `plan_loop` it may also write new ones during the practice. More examples mean more repetition. How many are actually used depends on the time left in the activity (8 minutes at most) and the session's AI budget."
- `practice.echo` — "What happens after Leafi reads an example sentence. `off`: nothing; Leafi goes on. `unscored` (default): your child may repeat the sentence; Leafi listens, but the repetition is not a test and never changes whether the word is marked as learned or misread. `as_attempt`: the repetition counts as one of the two tries; Leafi only checks that the word was heard in it, so it can mark the word as read but never as mispronounced. In both, the text of what your child said is sent to the AI service when this learner's 'cloud text' setting is on. Recordings themselves are never kept and never leave this computer."
- `practice.history_days` — "How many days of your child's earlier reading mistakes the AI sees when it plans (0 = none). The words your child said are sent to the AI service only when this learner's 'cloud text' setting is on, with the names Leafi knows replaced."
- `limits.practice_turns` — "How many times per practice activity the AI may decide the next steps (each one is a short request to the AI service and counts against the session budget). When they are used up, Leafi continues with the plan by itself. 0 means: plan only."
- `cloud.text` (addition) — "During practice this includes what your child says when asked what a word means or to say a sentence with it, and anyone else the microphone hears at that moment."

## Evaluation

Per activity: `planner_used`, turns used, refusals by code, unstamped-part refusals, `planner_ended` words; per miscue: final status, attempts, echoes and their outcome class, time. Across sessions: the same expected word missed again within 14 days (a transfer measure, *original*). `python -m leafi report practice` compares planners per learner, leaving out `planner_ended` words (T17); the owner switches `practice.planner` to compare in practice. No conclusion without effect size and sample size (ADR-0017 §9's line).

## Steps

- **P0** done: Decision log, research, revs 1–3.
- **P1** done: round 1 (two fresh Claude agents, `code-plan-review`; codex aborted), compared; the owner's answers. **P1b** rev 4's increment round (one reviewer).
- **P2** prototype `scripts/prototypes/practice/` (R§4: M1–M8), shape C over a mock `brain_call`; changed by rev 4: M3 measures a `BrainReply` sequence on `fast` only; M4 the lean plan on `fast` and `standard` started beside `decide`; M7 = a privacy change ends the conversation and no further request is prepared; **M8** = the contract of P9 (stamps survive two turns, a forced invalid reply, a cancel and a merge; `NativeOutput` without tool parts; output retries 0; the guard refusing an unstamped part) plus TTS of plan `parts` on both engines. Real-Claude latency needs `ANTHROPIC_API_KEY` with the owner present.
- **P3** ADR-0020; ADR-0013, ADR-0016, ADR-0017, ADR-0018 and `security.md` amended (P2, P6, P7); M7 design amended per P10.
- **P4 = M7f**, after M7e:
  - migration 8 and interests (P6); `LeafiModel` with the stamps and the guard, the graph and its nodes (P4, P5); `practise_errors` dispatching by `practice.planner`; the `stop` cell for every planner; settings with their help text; P7's rewording and evaluation-file deletion; `report practice`;
  - tests: `test_practice_plan` (each check; `parts` join; plan bound by id intersection; no plan → `code`), `test_practice_graph` (illegal steps replaced and reported; a sequence cut at the first illegal step; TryFirst never says the word and its hotword is off; a third Attempt refused; Park then Focus back keeps `used_total`; the end rule on `used_here`; EndPractice → no re-offer this cycle and `planner_ended`; AskMeaning and UseInSentence never graded, "yes" not a control; echo in each mode, `as_attempt` never `confirmed`; stop on a revisited word with an earlier fail → `unsure(disagreed)`; skip during a `BrainTurn` lands on the word current then; stop, skip and page turn during each listening step; `next_default` ⊆ `legal_steps` and terminating; the turn budget running out; ADR-0013 (l) under all three planners), `test_practice_text` (rule 5: each forbidden word as a whole token, the target exempt, `?`, length, URL, a picture prompt, the word named before modelling, surrogate mapped back), `test_leafi_model` (rendered only from stamps; each unstamped part kind refused; tier walk on `invalid` / `timeout` with the relaxed D4 line; a privacy change ends the conversation; delta rows chain to the full request), `test_pydantic_ai_contract` (P9), `test_practice` green for `code` plus the new `stop` case, `test_privacy` (P7), `test_cancellation` (stop during a `BrainTurn` and during `_score`), `test_forget` (evaluation files), `test_netguard`, `test_architecture` (P9).
- **P5** owner present: real sessions per planner; the age-appropriateness and injection checks (M7 D20 style); M10 measures turn latency on the camera Mouth. Console buttons for `report practice` and `learner interests list` join M10's console pass (T26).

Not in M7f: Ollama or magpie as practice backends (their gates), pydantic-graph or pydantic-ai anywhere outside `practise_errors`.

## Round 1 themes and their answers

| Theme | Answer |
|---|---|
| T1 per-turn schema | P4: two fixed schemas (M7 B1), legality in code, the legal set as text |
| T2 unregistered parts | P4: stamps in `TextContent.metadata` and `ModelResponse.metadata`; the fail-closed guard |
| T3 model text after `cloud.text` off | P4: rendered only from stamps; a privacy change ends the conversation (M7 B2) |
| T4 the port and M7 amendments | owner: keep the `Agent`; M7 rev 9 already has multi-turn turns; P10 lists the rest |
| T5 two re-ask owners | P4: output retries 0, M7 D8 alone; a turn = one `brain_call` |
| T6 school | owner: send anyway; P7 states the cost, rewords the remaining sites, tests the limits |
| T7 parent interest leak | P6: stored with sources `[N, 0]` |
| T8 `as_attempt` echo | owner: `evidence = none`, only while `used_total < 2`; P5 rule 6; ADR-0013 step 3 |
| T9 `utterances.kind` | P6: migration 8 rebuilds the table |
| T10 `stop` on a revisited word | owner: `practice_final` over its rows; P5 rule 2; ADR-0013's cell, every planner |
| T11 try-first | P5 TryFirst: a line that never says the word, the target highlighted, hotword off |
| T12 `WordState` fields | P5: `used_here`, `modelled`, `last_evidence`, `last_score`, `cursor`; rule 3 counts this activity |
| T13 latency | P3: lean plan beside `decide`; P4: a step sequence per listen, `fast` only, the feedback/filler order |
| T14 no plan at a spent moment | P1: construction with `code` content, never a rejection |
| T15 skip during a `BrainTurn` | P5 rule 2: the word current when the skip was said (M7 D21) |
| T16 free-text check | P5 rule 5: every spoken string, widened list, whole tokens, target exempt, no `?`, talk cap 3; P10's D20 cases |
| T17 `EndPractice` | owner: no re-offer this cycle; `planner_ended` out of the comparison (P5 rule 3) |
| T18 free speech | owner: the transcript, with its own egress row and help line (P7) |
| T19 record volume | P7: delta rows with `prev_call_id` |
| T20 `forget --brain-records` | M7 D19 (session id, fence); P7 adds evaluation files and `--before` on them |
| T21 interests | P6: parent excluded from ageing, readers filter on `kind`, guests refused, the input defined, D18 via P10 |
| T22 inside a node | P5 "Running the graph": awaits first, writes in one transaction, groups unwrapped; `next_default` ⊆ `legal_steps` |
| T23 `method`, `Syllables` | P5 `next_default` dispatches on `method`; P3 `parts`; P2 M8 measures TTS of parts |
| T24 help text | rewording above |
| T25 dependencies | P9: contract, netguard and architecture tests; one `TurnSource` seam for the fallback |
| T26 small gaps | Faces cleared on Focus; yes/no in AskMeaning; ADR-0013's ordering sentence; console buttons; voice fixed per activity |
