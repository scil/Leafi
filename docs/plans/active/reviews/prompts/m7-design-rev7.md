Confirming review of `docs/plans/active/2026-10-23-m7-brain-design.md` revision 7, before M7b's code. M7a is built
(commits 92b68de..de7dabc; the plan's Progress lines M7a-1 … M7a-6e say what landed). The review of revision 6 is
`docs/plans/active/reviews/2026-10-24-m7-design-rev6-claude.md` (findings 1–17). Revision 7 changes D21 (input
ownership) so that `listen` keeps M6's contract and only filters, and adds round 6 #8 to D15 and #16 to D19.

Code to read: `leafi/study/harness/inputs.py` (all of it), `leafi/devices/console.py`, `leafi/services/asr/__init__.py`
(`_segment_vad`, `_segment_energy`, `Vad.feed`), `leafi/core/text.py` (`typed_utterance`), `leafi/core/ports.py`
(`Utterance`), `leafi/study/harness/negotiate.py`, `leafi/study/harness/activities.py` (every `listen` and `say`),
`leafi/study/harness/world.py`, `leafi/study/harness/identify.py`, `leafi/study/harness/loop.py`,
`leafi/study/harness/latch.py`, `leafi/study/controls.py`, the M6 tests under `tests/` that drive `Inputs`
(`test_controls.py`, `test_harness_sessions.py`, `test_identify.py`, `test_negotiate*.py`).

1. For round 6's findings 1–6, 8, 9, 10, 16: "closed", "partly" (what remains) or "open".
2. Hand-execute rev 7's D21 against today's code: does `listen` really keep M6's contract for every one of the 14
   call sites (return values, the skip queue, `/page` utterances, timeouts)? Walk: "skip" in voice `read_listen`;
   `/page 5 --text p5.txt` in reply to `ask_page_text`; a `/page` typed during the `decide` wait at autonomy 8;
   "skip" during the `decide` wait; the Ear lost during `controls_only`; a line typed while a plain `say` plays
   between two questions; a scripted M6 test source. Which existing M6 tests would break, and why?
3. Is "a plain `say` presents `None`" safe with the late-voice rule (consequence 1) and the filler exception?
4. Are D15's provenance change and D19's single `forget --brain-records` definition complete?
5. Readiness: can M7b's code start? If not, exactly what blocks it.

Report a numbered list, each with severity (High / Medium / Low), the decision it concerns, the concrete failure and
a suggested fix. Say plainly what is sound. Do not edit any file.
