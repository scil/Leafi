# Brain-planned practice: what the owner's decision changes, and how to build the loop

Checked: 2026-10-24. Input: the owner decision of 2026-10-24 (plan `2026-10-22-ai-led-study.md` → Decision log). Feeds `docs/plans/active/2026-10-24-practice-planning-design.md`. Tiers: T1 = the repository's code and ADRs, the installed packages, vendor documentation; T2 = the earlier research notes.

## 1. Questions

1. Which of the six privacy decisions are already true in the code and ADR-0018, and which change something?
2. Which ADR owns which part of a Brain-planned `practise_errors`, given ADR-0013's single-owner rule?
3. What shape should the "constrained tool loop" take: a conversation of tool calls, or one stateless call per step?
4. Does the new design make pydantic-ai (or the `anthropic` SDK's own tool runner) worth adopting?

## 2. Findings

### 2.1 Privacy: most of the decision is the current default (T1)

| Owner decision | State today | Source | Change needed |
|---|---|---|---|
| 1. Learner notes, reading history, interests go to the cloud | notes are `derived_from_learner` and already leave under `cloud.text` on; reading history (`miscues.heard`, practice outcomes) is not in any observation yet; **interests do not exist** | ADR-0018 §2 table; `storage.py` `learner_notes`, `miscues`, `practices` | new observation section; new data (interests) |
| 2. The learner's own words (a misread "box") are sent | already allowed: `learner` text leaves pseudonymised when every source learner has `cloud.text` on | ADR-0018 §2 row 2; `egress._gate` | none in the rule; the payload description in `security.md` gains the new purposes |
| 3. Opt-out for every registered learner | `cloud.text` defaults to **on** already (`privacy/settings.py` `KEYS`); egress additionally requires the school answer (`cloud_text_allowed`) | `privacy/settings.py:20,44–47` | none to the default. Open: keep the school condition (§3) |
| 4. Pseudonymisation stays | unchanged: lists + Presidio detector | ADR-0018 §3 | none |
| 5. Audio stays local | unchanged: media only with a per-item `remote_teacher` consent; practice audio is never a payload | ADR-0018 §4 | none |
| 6. Records deleted by hand, no expiry | `brain_calls`, utterances, practices are kept "until `forget`" | ADR-0018 §4.3 | none for `brain_calls`; **conflict** with M7 D19's 30-day `decision_records` and the opt-in 30-day eval transcripts (§3); a narrower delete entrance (§2.4) |

Stale statements in the decision's commentary, corrected: AGENTS.md's boundary no longer says "MUST NOT send … the learner's own words"; since M5 it says only "except through `leafi.privacy.egress`" under `security.md` and ADR-0018. So AGENTS.md needs no edit, and `tests/test_privacy.py` needs new cases, not a changed rule. Guests keep `cloud.text` off (`from_row` forces it), so the decision's "every registered learner" already excludes them.

### 2.2 Ownership (T1)

- ADR-0013 → Practice owns the per-miscue rules (≤ 2 attempts, the outcome classes, `confirmed` only with `evidence = acoustic`, skip, page turn, final status) and AGENTS.md forbids restating them. A planner and an executor must therefore be **written into ADR-0013** as the way steps 1–2 are chosen, while steps 3–6 stay verbatim.
- ADR-0017 §3.1 owns `practise_errors`'s params (today selection only, content owner none) and §5.1 the purposes and routes; a plan is a new content field, a step call a new purpose or a new `generate` kind.
- ADR-0018 owns the data classes, the egress table and retention: interests are a new data class.
- The M7 design (rev 4, three review rounds) owns the call layer this builds on (D1–D11, D14's per-boundary content cache, D15's reference binding).

### 2.3 Loop shape (T1, T2)

Two ways to let the Brain "pick the next step from tool results":

| | A. Stateless step calls | B. Tool-use conversation (one `agent.run` per activity) |
|---|---|---|
| Mechanism | the harness owns the loop; at each step it renders the word's state (attempts left, last outcome, examples used, the plan) and asks for one structured `Step` | the model calls tools (`listen_attempt`, `say_example`, …); the conversation grows with `tool_use`/`tool_result` pairs |
| Reuses M7 | everything: `brain_call`, routes, filter (D3), budget per transmission (D7), audit rows (D11), cancellation (D8) | the call layer has to wrap a multi-turn run; one `brain_calls` row per request still needed |
| Cancellation (decision Q1) | between calls; a step's effects are committed by the harness before the next call | a tool awaits the child for up to 10 s inside a model run; stop/skip/page turn cancel the run mid-tool |
| Tier switch mid-activity (Q2) | nothing to carry: each call is complete in itself | history must be valid on the next provider |
| Provenance | each call's sent leaves are known (D2) | the history accumulates the child's words across turns; every later request re-sends them |
| Cost | the stable prefix (system + plan) is resent each step; a second cache breakpoint after the plan covers it | grows with turns |
| Hard rules | code refuses an illegal step (no third attempt, no `next` before an attempt) and takes the default step | the same checks inside each tool |

Prior art for A: ReAct-style loops where state lives in the prompt rather than in history; LiveKit's and Pipecat's harness-owned turn loops (libraries research R7, R9) keep the model as a function of the current state. Both shapes satisfy "the harness enforces the rules"; A satisfies it without a second loop owner.

Only Claude tiers are usable now: `GATE_FLOOR` blocks Ollama until its measurement (M10), and magpie's structured-output probe waits for M9. Cross-provider tool formats (Q3 of the decision commentary: local tool-call reliability) are therefore not a present need under either shape.

### 2.4 Deletion entrance (T1)

`python -m leafi forget` has `--session`, `--book`, `--learner` (`cli.py:524`). None deletes the Brain's records alone while keeping the learner's history. Decision 6 ("deleted manually by a parent or admin") is served by the existing three for whole-history deletion; a `forget --brain-records --learner N [--before DATE]` would delete `brain_calls` (and `decision_records`) rows citing N without touching reading history. The console's value-taking privacy buttons already wait for M10.

### 2.5 Libraries (T1, T2)

- **pydantic-ai**: latest `pydantic-ai-slim` 2.61.0 on PyPI (2026-10-24; the prototype measured 2.59.0, the libraries research recommended against pinning 2.31.1). Vendor docs (pydantic.dev, models overview, checked today): `FallbackModel` falls back on `ModelAPIError` (4xx/5xx, connection errors, timeouts before a response starts) and context-window errors; **validation errors are retried on the same model, not fallen back**; per-model settings live on each model, the `FallbackModel` has none; SDK retries must be 0 for immediate fallback; no fallback after a stream's first event. The docs say nothing on whether message history stays valid across providers within one run. Not installed in `.venv` (the prototype ran it separately).
- **`anthropic` 1.17 tool runner**: present (`anthropic/lib/tools/_beta_runner.py`: `BaseToolRunner` with `max_iterations`, `append_messages`, `set_messages_params`, compaction). Claude only, beta endpoint; it would sit behind the mediated client like any SDK call (unverified: the body comparison in egress for a runner-built request).
- What each shape needs from a library: A needs structured output only, which M7 D6 already provides (Pydantic models + `api_schema`). B needs tool schemas, history assembly and pairing, which is where pydantic-ai earns its weight (the decision commentary's points 1–3).

Conclusion (rev 1): the trigger the libraries research set ("choose it if the Brain grows agentic tool loops") is met only if shape B is chosen. Under shape A pydantic-ai saves about what it saved in comb2 (≈ 13 lines) and adds 9 packages.

**Owner, 2026-10-24: not single steps; the Brain leads, orchestrated by pydantic-graph.** Shape A is dropped. The design (rev 2) is shape C, §2.6.

### 2.6 pydantic-graph (T1, vendor docs read 2026-10-24)

- `pydantic-graph` 2.61.0 (released with `pydantic-ai-slim` 2.61.0), Python ≥ 3.11, requires only `anyio`, `logfire-api`, `pydantic`, `typing-inspection`: **no `httpx`**, so TD-1's import-order trap does not apply to it alone (it does to `pydantic-ai-slim[anthropic]`, which imports `httpx`).
- Nodes are `BaseNode[State, Deps, Out]` dataclasses with `async def run(ctx: GraphRunContext)`; **outgoing edges are inferred from `run`'s return annotation, and the return type "is enforced at runtime"**. Unions branch; `End[T]` ends. Graphs are assembled with `GraphBuilder` (`g.node(...)`, `g.edge_from(g.start_node).to(...)`, `g.build()`); the builder also has decisions, `.map()` fan-out and joins (not needed here).
- `graph.iter(state=…)` is an async context manager yielding a `GraphRun`; `async for event in run` advances one task at a time; `next_task`, `output`, `next()` (with optional value injection). So the harness can checkpoint between nodes.
- **No persistence**: `pydantic_graph.persistence` was removed in V2; neither API snapshots graph state. For Leafi that is the right default: the database rows (`practices`, `miscues`, utterances) stay the only record, as ADR-0013 and ADR-0017 §7.3 require; a crash resumes from them, not from a graph snapshot.
- State is one mutable object shared by all nodes; deps via `ctx.deps`. The docs' GenAI example runs an `Agent` inside a node and keeps the agent's `message_history` in the graph state — the pattern shape C uses.
- Not documented: cancellation and timeouts. The engine runs on `anyio`, so a cancelled scope should cancel the node being awaited; prototype measure M1.

**Shape C (rev 2):** the practice is a pydantic-graph whose nodes are the harness's steps (each enforcing ADR-0013's rules and committing its rows before returning); one `BrainTurn` node runs a pydantic-ai `Agent` whose `message_history` lives in the graph state for the whole activity, so the Brain sees its own plan and every result so far and leads the practice. The Agent calls the model through a Leafi `Model` adapter onto M7's `brain_call` (tiers, egress, budget, audit), not through `AnthropicModel` + `FallbackModel`. Facts to verify in the prototype: per-run `output_type` on `Agent.run` (so the Brain's choices can be narrowed to the legal steps); a custom `Model` subclass receiving the full message list per request; history re-rendered per request under current privacy settings.

## 3. Owner's answers (2026-10-24)

1. **School answer: not required.** A learner's own words leave with `cloud.text` on whether or not the school is answered (against the recommendation, which was to keep it because an unknown school cannot be replaced; the name detector still replaces organisations it finds). Leafi still asks the school question so the school can be replaced when known.
2. **The two 30-day rules are cancelled.** `decision_records` and evaluation transcripts are kept until a parent or admin deletes them, like `brain_calls` (decision 6 applies to them too).
3. **Interests:** written by a parent and by the Brain from the child's interactions.
4. **Echo repetitions:** a setting with a detailed explanation beside it (design `practice.echo`).

## 4. What the prototype must measure (before the ADR)

`scripts/prototypes/practice/`, like M2: shape C (pydantic-graph + `Agent` with history on a Leafi `Model` over a mock `brain_call`), and for comparison shape B with the SDK tool runner. Same scripted child (pass, fail-then-pass, silence, skip mid-listen, stop mid-listen, page turn mid-listen), same fake clock.

| # | Measure | Pass |
|---|---|---|
| M1 | stop / skip / page turn during a listening step | committed `practices` rows exactly as ADR-0013 (l); no row for the cut attempt; the run ends within 50 ms |
| M2 | tier switch after 3 steps (fast fails → standard) | the next step valid; for B, the history accepted by the second model |
| M3 | latency per step, mock and real Claude (`fast` tier, owner's API key) | p95 from "attempt scored" to "next step known" ≤ the feedback moment (3 s PC) minus the output reserve; filler at 0.8 s |
| M4 | plan call latency (`generate:practice_plan`, 5 words × 3 examples) on `fast` and `standard` | p95 inside the `next_activity` moment (6 s PC); else plan-ahead (design D7) |
| M5 | lines of code per shape, dependencies added | reported |
| M6 | privacy canary through egress | no real name, school or audio in any body; with `cloud.text` off the heard words appear only as categories |
| M7 | `cloud.text` switched off mid-activity | the next request's history carries the earlier heard words only as categories |
| M8 | the three facts of §2.6 (per-run `output_type`, custom `Model`, per-request re-render) | each shown by a test, or the design changes |

Not measured now: Ollama and magpie tool calling (gated, M9/M10).

## Sources

- T1: `leafi/privacy/settings.py`, `leafi/privacy/egress.py` (`_gate`), `leafi/study/harness/activities.py` (`practise_errors`), `leafi/core/storage.py`, `leafi/cli.py`; ADR-0013 → Practice, ADR-0017 §3.1, §5, §6.3, ADR-0018 §2–§5; AGENTS.md; `.venv/Lib/site-packages/anthropic/lib/tools/_beta_runner.py` (1.17.0).
- T1: https://pypi.org/pypi/pydantic-ai-slim/json (version 2.61.0, read 2026-10-24); https://pydantic.dev/docs/ai/models/overview/ (`FallbackModel`, read 2026-10-24); https://pypi.org/pypi/pydantic-graph/json (2.61.0, requirements); https://pydantic.dev/docs/ai/graph/ and https://pydantic.dev/docs/ai/graph/builder/ (nodes, runtime-checked edges, `iter`, persistence removed in V2; read 2026-10-24).
- T2: `docs/research/2026-10-22-harness-libraries.md` (runner-up and its trigger, L4, L12), `docs/research/2026-10-23-harness-combinations-compared.md` (comb2 costs).
