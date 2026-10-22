Round 5. Review the revised docs/adr/0017-ai-led-study-session.md and docs/adr/0018-learners-and-privacy-v2.md as a design, not as prose. Earlier findings: docs/plans/active/reviews/2026-10-21-codex-ai-led-design-review-1.md to -4.md. Background: docs/research/2026-10-21-ai-led-study.md (§1, §8). Rules kept or changed: docs/adr/0013-reading-algorithm-v1.md, docs/adr/0010-page-text-revisions-and-auditable-corrections.md, docs/adr/0011-egress-policy-and-v1-scope.md, docs/architecture/data-model.md, AGENTS.md, leafi/core/netguard.py. Read only these files and the code they name when you need to check a claim; do not explore the rest of the repository.

The owner's decisions in research §1 and ADR-0017 §5.1 routing are settled; magpie honouring an explicit provider/model is a stated trust assumption.

Answer:
1. For each round-4 finding (6 numbered defects and 3 recurring bullets): resolved, partly resolved (what is left), or not resolved — one line each.
2. New defects. Hand-execute ADR-0017 §2.1 negotiate including settle(), §2 finalize/deliver, §5 brain_call with affordability; ADR-0018 §1 guest re-keying, §3 forget A with an unapproved correction chain (rev1 book, rev2 A, rev3 A, rev4 B), §4 audio prepare. Scenarios: a page turn during generation inside a named choice; "no" to an announced alternative; 0.5 budget units left; /stop during identification; forget A as above.
3. Anything that will keep going wrong in implementation.
Rank High / Medium / Low with section and a concrete failing scenario. Say explicitly if there are no High findings. Do not edit files.