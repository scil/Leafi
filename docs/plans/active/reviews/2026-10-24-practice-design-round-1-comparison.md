# Practice design rev 3 — round 1 comparison

Object: `docs/plans/active/2026-10-24-practice-planning-design.md` rev 3. Prompt: `reviews/prompts/practice-planning.md`. Reviewers, independent and in parallel, 2026-10-24:

- **A** — a fresh Claude (`2026-10-24-practice-design-rev3-claude.md`), 21 findings;
- **B** — a second fresh Claude in codex's place, with codex's emphasis on hand-run failure paths and code checks (`…-claude-b.md`), 19 findings; codex itself stopped at its usage limit before reading anything (`…-codex-aborted.md`);
- **C** — `code-plan-review` (`…-code-plan-review.md`), 19 findings.

All three are Claude, so they share one model's blind spots. The comparing author checked these against the code: `utterances.kind`'s CHECK (`storage.py:248`) and `_gate` testing `parent` text only against `CLOUD_PARENT_TEXT` (`egress.py:587`). B's detector probe is taken as reported. No finding is judged a false positive. One finding is partly wrong: C16's "files under `data/evals/` contradict M7 D19" holds for decision records, which D19 moved into the database, but not for evaluation transcripts, which are still files.

## Themes

| # | Theme | Sev | A | B | C | Rev 4 direction |
|---|---|---|---|---|---|---|
| T1 | Per-turn `output_type=legal_steps` changes the schema almost every turn: against ADR-0017 §5 and M7 D6 (byte-stable), a compile on first use inside 2 s, a prompt-cache miss (tools render first) | High | 6 | 1 | 3 | one fixed `Step` schema per `PROMPT_VERSION`; the legal set as text in the turn prompt; code refuses |
| T2 | pydantic-ai adds parts Leafi never registered (`ToolReturnPart`, `RetryPromptPart` with Pydantic text and input values): "unregistered → refused" refuses turn 2 of every activity, and whitelisting them breaks M7 D4 | High | 1b | 2 | 2 | Leafi owns the conversation (T4) |
| T3 | Model responses in the history once `cloud.text` is switched off mid-activity: refused whole (every later turn falls back) or leaked as plain strings (`_plain_strings` skips `_gate`); P7's "categories" claim is false | High | 1a | 11 | 1 | responses stored as structured steps with D2 provenance; on re-render a response that may not leave becomes a fixed `system` stand-in (`[step: Hint]`), or the conversation restarts on a privacy-version change |
| T4 | M7's port has no multi-turn shape (`ModelRequest` = system + sections); the design amends D5, D6, D8, D10, D12, D21 and the destinations' purpose sets, not only D18/D19; M7 is now rev 5 | High | 9 | 3 | 2 | **structural**: drop the pydantic-ai `Agent`; keep pydantic-graph; `BrainTurn` calls `brain_call` with a Leafi-owned history rendered each request; list every M7 amendment |
| T5 | Two re-ask owners (pydantic-ai `retries` and M7 D8's `invalid → next tier`): up to 4 transmissions a turn; turns vs transmissions in the budget undefined | Med | 8 | 4 | 2, 13 | one owner (M7 D8); a turn = one `brain_call`; a cap on transmissions per turn |
| T6 | School relaxation: the detector misses lower-case schools (B's probe: "st marys school", "riverside primary", "oakfield" → nothing); detector off or model missing → the school leaves verbatim; `remove_term`, `cli` setup text, `doctor`, `ops/checks`, help text and 4 existing tests not listed; conflicts with M7a D1's test | High | 13 | 5 | 12 | the cost stated in ADR-0018; every site and test listed; **owner: keep the gate while the detector is off or not ready?** |
| T7 | A parent-written interest leaves for a learner with `cloud.text` off, without the detector: `_gate` checks `parent` only against `CLOUD_PARENT_TEXT` (verified) | High | 2 | — | — | store it as `derived_from_learner` with sources `[A, 0]` (M7 D2's mixed encoding); test it |
| T8 | `as_attempt` echo: the scorer rates a whole sentence against one word → a false `confirmed` and a pronunciation item; at `used = 2` it inserts `attempt = 3` against the CHECK; redefines ADR-0013 step 3 | High | 3 | 9 | 6 | an echo never scored acoustically (`evidence = none`), scored only while `used < 2`; ADR-0013 step 3 amended |
| T9 | Migration 8 misses `utterances.kind` (`practice_talk`, `practice_echo` → IntegrityError; a table rebuild) (verified) | Med | 12 | 10 | 6 | rebuild in migration 8, with a test |
| T10 | `stop` on a revisited word with an earlier `fail`: the code gives `unsure(disagreed)`, hard rule 2 and ADR-0013's table say `unsure(skipped)` | Med | 4 | 7 | — | leave stop to `close_cycle` (keeps the fail evidence); amend the ADR-0013 cell; **owner** |
| T11 | Try-first cannot happen as written: `practice_retry` and `practice_intro` speak the word; Faces cannot mark the target; hotwords bias an unmodelled attempt toward `pass` | Med | 5 | — | 7 | a try-first line that never says the word; target highlighted; hotwords off before modelling |
| T12 | `WordState` lacks `last_evidence` / `last_score` (a parked word can never be `confirmed`, or takes another word's score), `modelled`, a script cursor; "used" across activities vs "in this activity" for the end rule | Med | 14 | 8 | 8 | add the fields; the end rule counts attempts in this activity |
| T13 | Latency: the plan after `decide` in one 6 s moment usually misses (`plan_loop` silently runs as `code`); turns are fast-only on the PC (`standard` never fits); a filler between most steps; the feedback line vs the filler unordered | Med-High | 7, 8 | 6 | 4, 5 | a turn returns a short step sequence up to the next listen; the plan lean (order, method, hint) with examples in turns, or the plan on `fast`; plan-ahead (P8) by default, binding by id intersection; define the feedback/filler order |
| T14 | No plan at a spent moment: M7 D14 rejects the kind, P1 says `code` | Med | — | — | 5 | a missing plan constructs with `code` content, never rejects |
| T15 | `skip` during a `BrainTurn` (skip queue) lands on the next word the Brain focuses; during playback it only cuts the line | Med | 11 | 12 | 15 | a skip applies to the word current when it was said |
| T16 | The free-text check: not on plan hints and examples; misses "wrong" / "mistake" (ADR-0013's framing); not whole-token; rejects a target that is itself a listed word; no cap on talk-only chains; personal questions; injection | Med | 15, 16 | 13 | out of catalog | one check on every spoken Brain string; widened list; whole tokens; target exempt; ≤ 3 non-attempt steps per word; `?` only in AskMeaning / UseInSentence; injection cases in M7 D20's measured checks |
| T17 | `EndPractice` leaves candidates open → re-offered with a new charged plan for a child judged tired; `Finish` after one fail becomes `disagreed` evidence and biases the planner comparison | Med | — | 17 | 9, 10 | **owner**: no re-offer this cycle; mark planner-ended words and exclude them from the comparison |
| T18 | The ungraded steps send the child's free speech, and any voice in the room, to the cloud — wider than decision 2's "a misread 'box'" — re-sent every turn and kept indefinitely | Med | — | — | 11 | **owner**: send the transcript (with its own egress row and help line), or only a local summary (target used yes/no, length) |
| T19 | Retention "until deleted" × the history re-sent per turn: ≈ 0.3–0.5 MB per activity, growing with the square of the turns | Low-Med | 17 | 16 | 11 | store each turn's delta with a reference to the previous row; state the volume in ADR-0018 §4.3 |
| T20 | `forget --brain-records` by source learners misses rows of N's sessions with sources `[]`; no `LearnerBusy` fence; `--before` on files unstated | Low | 17 | 14 | 16 | also by `session_id → learner`; fenced; state the files |
| T21 | Interests: the ageing rule is vacuous for an uncited parent interest; every `learner_notes` reader must filter on `kind`; guests; the input for Brain-written interests is undefined; the `decide` schema change | Low | 12, 18 | 15 | 18 | exclude `parent` from ageing; readers filter; guests refused; render `practice_talk` in the post-session observation |
| T22 | Inside a node: awaits before the transaction (today `_score` sits between the utterance and the `practices` row); `next_default` ⊆ `legal_steps` or a loop never ends; exception groups from the graph turn `Terminal` into `internal_error` | Low | 10 | 18 | — | order stated; a subset test; unwrap groups at the graph boundary; prototype M1 asserts statuses |
| T23 | `method` has no consumer in `next_default`; `Syllables` has no data source | Low | 14, 15 | — | 14 | `next_default` dispatches on `method`; a plan `parts` field checked to join to the word; measure TTS of parts |
| T24 | Help text contradicting the design (echo "never leaves this computer" vs the remote teacher; "the school replaced"; "falls back to the fixed routine") | Low | 19 | — | 12 | reword |
| T25 | Dependencies and contracts: `httpx` at import and a netguard test of a full mock turn; an architecture test confining `pydantic_graph`; P9's fallback without a shared contract test | Low | 21 | 19 | 17 | moot for pydantic-ai under T4; keep the netguard and architecture tests for pydantic-graph |
| T26 | Small gaps: Faces keeps the previous word's sentence after `Focus`; "yes" / "no" in AskMeaning parse as controls; ADR-0013's ordering sentence; console steps for `report practice` and `interests list`; a Kokoro/edge-tts voice switch mid-practice | Low | 16, 20 | — | 19 | each fixed in rev 4 |

## Overlap

- Found by all three: T1–T6, T8, T9, T12, T13, T15, T16, T19–T21.
- Found by two: T10 (A, B), T11 (A, C), T17 (B, C), T22 (A, B), T23 (A, C), T24 (A, C), T25.
- Found by one: T7 (A, the only privacy leak found by a single reviewer), T14 (C), T18 (C).

## The structural reading

T1–T5 rhyme: each comes from running pydantic-ai's conversation over M7's single-message, single-schema call layer. A and B both name the same way out, which is also rev 3's own P9 fallback: keep pydantic-graph for the orchestration the owner asked for, and let `BrainTurn` call `brain_call` with a history Leafi owns. The history would be records of the turn prompts, the step results and the Brain's structured steps, each rendered from leaves with provenance at every request. That removes the unregistered parts, the second re-ask owner, the per-turn schema and the new pydantic-ai dependency. M7's `ModelRequest` still needs `messages` (assistant turns rendered from structured steps), and that has to be an explicit M7 amendment. Rev 4 should make this one move alone, then answer the rest.

## For the owner

1. **T4: drop pydantic-ai, keep pydantic-graph** (recommended), or keep the `Agent` and its adapter work.
2. **T6: the school gate** while the name detector is off or its model is missing: keep it (recommended), or send anyway.
3. **T18: the child's free speech** in AskMeaning, UseInSentence and echoes: send the transcript, or only a local summary.
4. **T10: `stop` on a revisited word with an earlier fail**: `unsure(disagreed)`, which keeps the evidence (recommended), or `unsure(skipped)`.
5. **T17**: after `EndPractice`, no re-offer of `practise_errors` this cycle (recommended); and a word the Brain finishes after one fail is marked "planner-ended" and excluded from the planner comparison (recommended).
6. **T8: `as_attempt` echo**: keep it with `evidence = none` (recommended), or drop the value.
