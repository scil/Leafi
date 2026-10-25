Design round 2 (increment). Review **revision 2** of `docs/plans/active/2026-10-25-study-session-panel-design.md` as
a design, not as prose. Round 1 (three reviewers on rev 1) is compared in
`docs/plans/active/reviews/2026-10-25-session-panel-round-1-comparison.md`; rev 2 claims to answer its themes T1–T24
(table at the end of the design). The owner's decisions in the plan's Decision log
(`docs/plans/active/2026-10-25-study-session-panel.md`) are fixed and out of scope.

1. For each theme, check that rev 2's answer holds against the code as it is (`leafi/study/harness/inputs.py`,
   `latch.py`, `negotiate.py`, `loop.py`, `activities.py`, `world.py`, `rows.py`, `leafi/study/brain/scoring.py`,
   `sequence.py`, `notes.py`, `leafi/study/controls.py`, `leafi/study/anki.py`, `leafi/devices/console.py`,
   `leafi/app.py`, `leafi/runner.py`, `leafi/core/lease.py`, `leafi/privacy/egress.py`, `agent/webui/__main__.py`,
   `leafi/core/storage.py`).
2. Hand-execute the restated `/do` (D7) on the code: during playback and during the listen at each autonomy band;
   during a quiz question; mid-sentence in `read_listen` in text and voice mode; inside a Brain wait
   (`Inputs.controls_only`) and during the filler; twice; for a kind not on the menu; at a setup prompt; while the
   session is ending (`deliver`). Where does `Jump` escape, get swallowed, or leave a want or a skip behind?
3. Hand-execute D8's table: is there a site that writes evidence or sends a panel line to the Brain that the table
   misses? Does `counts_as_answer` change any console or voice behaviour?
4. D1/D3/D4: the trailing refresh and `Session.hooks` (is any state change the owner needs still unpublished?), the
   memory-only snapshot (does any field still need the database?), start after the lease, faults kept in the device,
   the per-pid file and the process check.
5. Anything new that rev 2 introduced and that is hard to get right.

If nothing needs to change, say so plainly. Otherwise report findings as a numbered list, each with severity
(High / Medium / Low), the decision or line, the concrete failure (inputs → outcome), and a suggested fix. Do not edit
any file.
