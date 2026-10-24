Review `docs/plans/active/2026-10-23-m7-brain-design.md` as a design, not as prose, against the accepted
`docs/adr/0017-ai-led-study-session.md` (§2–§9, Confirmation) and `docs/adr/0018-learners-and-privacy-v2.md`
(§2, §3, §7.4), and the code it changes (`leafi/privacy/egress.py`, `leafi/privacy/settings.py`,
`leafi/services/brain/`, `leafi/core/ports.py`, `leafi/study/harness/` — `loop.py`, `construct.py`,
`negotiate.py`, `ledger.py`, `state.py`, `activities.py`, `latch.py` —, `leafi/study/coach.py`,
`leafi/core/storage.py` (tables `brain_calls`, `retrieval_events`, `learner_notes`, `knowledge_items`),
`leafi/core/learner_store.py`, `tests/test_architecture.py`). The project rules are in `AGENTS.md`; Leafi runs in
a child's home and its first boundary is that learner data reaches a cloud service only as ADR-0018 allows.

What will be hard to get right, and what will keep going wrong? In particular:

1. Privacy (D4, D7, D14): can a learner's words, a learner note or a real name reach a cloud Brain when the
   learner's `cloud.text` is off, or for a guest? Walk every observation section, the rejection line of D6, the
   `generate` kinds, `extract_notes` and the replay script. Do the filter and egress's gate agree in every case?
2. Budget and cancellation (D5, D6, D8): hand-execute a `decide` call that is cancelled by `stop` during the
   mediator's retry, one that times out on the first tier and escalates, and the filler task racing the reply.
   Is anything charged twice or not at all, left `running`, or spoken after the epoch changed?
3. Does each decision agree with ADR-0017 / ADR-0018, or silently narrow them? Items marked [beyond ADR] are the
   author's additions; say whether each is sound or needs the owner.
4. Schemas (D3, D11): will the `decide` `anyOf`, the stripped constraints and `messages.create` +
   `output_config` work with `anthropic` 1.17 and the egress body comparison? Are the quiz-answerability and id
   checks sufficient against a model that invents ids?
5. Derived status (D13): is deriving item status and recall dates from `retrieval_events` correct for both
   mastery modes, Anki acknowledgements and `forget --session`?
6. Steps M7a–M7e: can each land with the suite green, and is anything in ADR-0017's Confirmation left without a
   step?

Report findings as a numbered list, each with severity (High / Medium / Low), the decision or line it concerns,
the concrete failure (inputs → what leaks or breaks), and a suggested fix. Say plainly when a part is sound. Do
not edit any file.
