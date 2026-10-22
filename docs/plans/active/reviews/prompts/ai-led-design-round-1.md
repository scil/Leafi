Review docs/adr/0017-ai-led-study-session.md and docs/adr/0018-learners-and-privacy-v2.md as a design, not as prose. Background and the owner's decisions: docs/research/2026-10-21-ai-led-study.md (§1 and §8). Rules they keep or change: docs/adr/0013-reading-algorithm-v1.md, docs/adr/0011-egress-policy-and-v1-scope.md, docs/architecture/data-model.md, AGENTS.md. Read only these files and the code they name (leafi/study/session.py, leafi/services/brain/, tests/test_privacy.py) when you need to check a claim; do not explore the rest of the repository.

The owner's decisions in research §1 (Leafi autonomy 0–10, recognition on by default, learner text to the cloud by default with pseudonymised identity, audio/images local first with per-item consent, magpie with any provider) are settled; do not argue them. Review whether the ADRs implement them soundly.

Answer:
1. What will be hard to get right, and what will keep going wrong? Hand-execute the pseudocode in ADR-0017 §2, §2.1, §3 (`allowed`, `default_decision`), §5 (`brain_decide`, `validate`) and ADR-0018 §1 (`identify`), §4 on concrete inputs: a session with no Brain; a Brain that times out twice; a page turn in the middle of `read_listen` with three open candidates; autonomy 2 with a learner who names an activity outside the menu; autonomy 10 with `stop`; `cloud.text` off with `learner_questions`; two enrolled siblings with similar voices.
2. Interactions with ADR-0013 that §8 leaves open or contradicts (candidate lifecycle across cycles and pages, page settlement, Interrupted session, async guard / turn_id, Difficulties, CHECK).
3. Privacy holes: any path where real identity, heard words with `cloud.text` off, or media without a consent row could leave; whether pseudonymisation can be bypassed; magpie as a destination.
4. Missing states, limits or records that implementation will need.
Rank findings High / Medium / Low with the section they cite and a concrete failing scenario. Do not edit files.
