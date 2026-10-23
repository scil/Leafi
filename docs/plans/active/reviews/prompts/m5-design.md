Review `docs/plans/active/2026-10-23-m5-egress-design.md` as a design, not as prose, against the accepted
`docs/adr/0018-learners-and-privacy-v2.md` (§2–§5, §7.3–§7.5, §8, Confirmation) and the code it changes
(`leafi/core/netguard.py`, `leafi/services/brain/`, `leafi/services/tts/`, `leafi/devices/notifiers.py`,
`leafi/ops/`, `leafi/doctor.py`, `leafi/services/catalog/`, `leafi/envprotect.py`, `leafi/envedit.py`,
`leafi/study/harness/inputs.py`, `tests/test_architecture.py`). The project rules are in `AGENTS.md`; Leafi runs
in a child's home and its first boundary is that learner data never reaches a cloud service except as ADR-0018
allows.

What will be hard to get right, and what will keep going wrong? In particular:

1. Can any byte reach a non-loopback (or gateway-port) socket without passing `prepare` and the mediated
   transport, or without a grant? Walk each inventory row and each third-party client (anthropic SDK, edge-tts
   library, huggingface_hub, rapidocr, aiohttp, subprocesses). Check D2's contextvar grant propagation, D6's
   canonical HMAC binding, D7's token consumption and the retry, D16's redirects for holes, races and failure
   paths.
2. Does each decision agree with ADR-0018, or does it contradict or silently narrow it? Items marked
   [beyond ADR] are the author's additions; say whether each is sound or needs the owner.
3. Pseudonymisation (D10, D11): surrogate collisions, possessives, names inside other words, mapping replies
   back, the detector's offline guarantee (`tldextract`), and what happens when the model is missing.
4. Settings and provenance (D12, D13): every path a learner's text can take to edge-tts or the Brain; the typed
   confirmation; the `REDACT_TERMS` migration.
5. Ordering and testability of steps M5a–M5f: can each land with the suite green and without a window in which
   the old enforcement is gone and the new one not yet in place?

Report findings as a numbered list, each with severity (High / Medium / Low), the decision or line it concerns,
the concrete failure (inputs → what leaks or breaks), and a suggested fix. Say plainly when a part is sound. Do
not edit any file.
