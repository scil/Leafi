Increment review of `docs/plans/active/2026-10-23-m7-brain-design.md` revision 8 (D21 input ownership and D12), the
last gate before M7b's code. The review of revision 7 is `docs/plans/active/reviews/2026-10-24-m7-design-rev7-claude.md`
(findings 1–9). Revision 8 changes D21's pseudocode (`ear_lost`, the reader's non-main sources, `listen`'s `Switched`
and late wait-owned items, `controls_only`'s exit returning skips and pages) and adds the "Rev 8 details" paragraphs.

Code: `leafi/study/harness/inputs.py`, `leafi/services/asr/__init__.py` and `leafi/services/asr/vad.py`,
`leafi/devices/console.py`, `leafi/study/harness/negotiate.py`, `leafi/study/harness/activities.py`,
`leafi/study/harness/world.py`, `leafi/study/harness/identify.py`, `leafi/study/harness/loop.py`,
`leafi/study/knowledge.py`, `leafi/study/cards.py`, and the M6 tests driving `Inputs` (`tests/test_controls.py`,
`tests/harness_helpers.py`, `tests/test_harness_sessions.py`).

1. For round 7's findings 1–9: "closed", "partly" (what remains) or "open".
2. Hand-execute rev 8 on: the Ear lost while a console read is in flight in voice mode during `read_listen`; the same
   during a `decide` wait; "skip" spoken during `decide` whose recognition finishes after the wait; "next page" spoken
   during an in-activity `judge` wait; a "no thanks" reply to `_offer_hint`; a 1.2 s pause ending speech just before
   B's question (energy segmenter).
3. Is anything in rev 8 new and wrong, or does any of the 15 `listen` sites still change behaviour against M6?
4. Readiness: can M7b's code start now?

Report a numbered list (severity High / Medium / Low, decision, concrete failure, suggested fix), say what is sound,
and give a one-line readiness verdict. Do not edit any file.
