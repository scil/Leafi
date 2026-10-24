Review `docs/plans/active/2026-10-24-practice-planning-design.md` (rev 3) as a design, not as prose, together with
its research `docs/research/2026-10-24-brain-planned-practice.md`, against `docs/adr/0013-reading-algorithm-v1.md`
(→ Practice, Page turns, Control precedence, worked example (l)), `docs/adr/0017-ai-led-study-session.md` (§3.1,
§5, §5.2, §6.3, §7.1, §9), `docs/adr/0018-learners-and-privacy-v2.md` (§2, §3, §4.3, §5), the M7 design it builds
on (`docs/plans/active/2026-10-23-m7-brain-design.md` rev 4: D1–D4, D6–D8, D11, D12, D14, D15, D18, D19), and the
code it changes (`leafi/study/harness/activities.py` — `practise_errors`, `_finish_candidate`, `_score` —,
`leafi/privacy/settings.py`, `leafi/privacy/egress.py` (`_gate`), `leafi/core/storage.py` (tables `miscues`,
`practices`, `learner_notes`, `brain_calls`, `utterances`), `leafi/cli.py` (`forget`), `leafi/doctor.py`,
`leafi/core/alerts.py`). The project rules are in `AGENTS.md`; Leafi runs in a child's home and its first boundary
is that learner data reaches a cloud service only as ADR-0018 allows. The owner's decisions behind the design are
in `docs/plans/active/2026-10-22-ai-led-study.md` → Decision log, entries of 2026-10-24; treat them as given, but
say when one has a cost the design does not state.

What will be hard to get right, and what will keep going wrong? In particular:

1. ADR-0013's rules (P5 hard rules 1–3): hand-execute the graph on named inputs — three candidates A, B, C where
   A passes on the first attempt after `TryFirst`, B is parked after one `fail` and revisited, C is never
   attempted; then `stop` during B's second attempt; then a page turn during an `AskMeaning` listen; then the turn
   budget running out while a word is current. Does every miscue end with the status ADR-0013 gives, no third
   attempt, nothing graded that should not be, and the cycle owning what it should?
2. Privacy (P3, P4, P6, P7): can a learner's words, a note, an interest, a real name or audio reach a cloud Brain
   when `cloud.text` is off, for a guest, or after `cloud.text` is switched off mid-activity? Walk the plan's
   sections, the conversation history `LeafiModel` re-renders, the `practice_talk` / `practice_echo` utterances,
   Brain-written interests and the free text the Brain speaks. What does the owner's "school no longer required"
   change in practice, and is the design's account of it complete?
3. The pydantic-graph / pydantic-ai seam (P4, P9): is `LeafiModel` over `brain_call` sound with M7's egress token
   (body HMAC), the budget per transmission, the tier walk and the audit rows? Which pydantic-ai facts does the
   design rely on without checking (per-run `output_type`, a custom `Model`, message-part identity for the
   `leaves` map, output-validation retries spending budget)? Does cancellation inside a node, under `graph.iter`,
   leave rows committed or half-written? Is the fallback in P9 real?
4. Latency and budget (P3, P4, P8): with a `BrainTurn` after every step on the `fast` tier, a 3 s feedback moment
   and 20 turns per activity, what does a child actually hear and wait for? Is the plan turn inside the 6 s
   `next_activity` moment? Is charging per transmission still right when one turn can re-ask?
5. The free-text check (P5 rule 5) and the ungraded steps: is the check sufficient for lines a child hears from
   a model, and what can still go wrong (tone, false information, revealing an answer, prompt injection from page
   text or the child's words)? Is `as_attempt` echo consistent with ADR-0013's attempt rules?
6. Data and migrations (P6, P7): migration 8, `forget --brain-records`, the cancelled 30-day expiry, Brain-written
   interests ageing out — do `forget --session` / `--learner` stay complete? Anything without a writer, a reader or
   a test?
7. Items marked [beyond ADR] or *original*: say for each whether it is sound or needs the owner. Is anything in
   the steps (P0–P5) left without a step, or impossible to land with the suite green?

Report findings as a numbered list, each with severity (High / Medium / Low), the decision or line it concerns,
the concrete failure (inputs → what leaks or breaks), and a suggested fix. Say plainly when a part is sound. Do
not edit any file.
