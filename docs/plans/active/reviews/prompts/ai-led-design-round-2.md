Round 2. Review the revised docs/adr/0017-ai-led-study-session.md and docs/adr/0018-learners-and-privacy-v2.md as a design, not as prose. Round 1 findings and what they asked for: docs/plans/active/reviews/2026-10-21-codex-ai-led-design-review-1.md. Background: docs/research/2026-10-21-ai-led-study.md (§1, §8). Rules kept or changed: docs/adr/0013-reading-algorithm-v1.md, docs/adr/0011-egress-policy-and-v1-scope.md, docs/architecture/data-model.md, AGENTS.md. Read only these files and the code they name when you need to check a claim; do not explore the rest of the repository.

The owner's decisions in research §1 are settled; do not argue them.

Answer:
1. For each round-1 finding (1-18): resolved, partly resolved (what is left), or not resolved — one line each.
2. New defects the revision introduced. Hand-execute the pseudocode again (ADR-0017 §2 run_session incl. the continuation branch, §2.1 negotiate, §3.2 allowed, §3.3 construct/default_decision, §5 brain_decide; ADR-0018 §1 identify, §2 egress order, §4 consent) on: no Brain; two timeouts; a page turn mid read_listen with three candidates and the learner keeps reading; autonomy 2 with an out-of-menu request; autonomy 10 with stop during negotiate; cloud.text off with learner_questions and only Claude configured; siblings within the margin; a crash after practise_errors settled one of three candidates.
3. Anything that will keep going wrong in implementation.
Rank findings High / Medium / Low with the section cited and a concrete failing scenario. Do not edit files.