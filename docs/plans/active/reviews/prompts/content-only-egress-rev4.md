Structural round. Review only three parts of E9 in
`docs/plans/active/2026-10-24-content-only-egress-design.md` **rev 4**, as a design, not as prose:

1. **The TTS cache per owning learner** (E9 "Stores outside the database"; E7's pointer): `<cache_dir>/tts/learners/<id>/`,
   `TtsService.set_owner`, `shared/` for lines outside a session, deletion on `forget` (twice), the sweep by owner at
   session start, the guest sweep. It replaces rev 3's lease-based purge (`reviews/2026-10-24-egress-e8e9-rev3-codex.md`,
   findings 1–3). Hand-execute: a session that starts as a guest, synthesises, is adopted by learner L, synthesises
   again; `forget --learner L` while M's session runs; a cancelled Kokoro executor worker of L's ended session finishing
   after `forget`; the camera Mouth (`cache/tts/camera/`, `leafi/core/hub.py` or wherever clips are pushed); the habit
   track's `agent/tts.py` root files. Can any clip of L survive, or any clip of M or the habit track be deleted? Who
   calls `set_owner`, and is there a path where synthesis runs with no owner or the wrong owner (identify's prompts,
   the console, `doctor`, `leafi.cli` commands that speak, the hub's `say` before `identify` returns)? Does the cache
   layout change break any reader of the cache (the camera push, the TTS cache retention in `security.md`, tests)?
2. **The fence's UPDATE scope as a maintenance allow-list** (E9 "What the architecture test fences"): is the inversion
   sound; can `test_architecture` parse the `SET` targets of every UPDATE string in `leafi/` (f-strings, multi-line
   strings, `executemany`, helpers that build SQL); which existing raw UPDATEs of the owned tables would fall outside
   the allow-list and need `update_named` (name them), and is any of them bulk or in a path that must not raise
   `LearnerUnavailable`?
3. **Recovery's owner check** (E9 "Why the other session tables are not fenced"): is the in-transaction `EXISTS` check
   and per-session skip correct against `leafi/study/harness/rows.py` (`recover`) and `leafi/study/harness/loop.py`
   (`run_session`, finalisation)? Hand-execute the failed-finalisation state with the learner marked forgetting between
   two `forget` batches; is any write left that the check does not cover?

Check against the code: `leafi/services/tts/__init__.py`, `leafi/services/tts/kokoro.py`, `leafi/services/tts/edge.py`,
`leafi/core/hub.py`, `leafi/runner.py`, `leafi/study/harness/{identify,guests,rows,loop,inputs}.py`,
`leafi/study/records.py`, `leafi/core/learner_store.py`, `tests/test_architecture.py`, `agent/tts.py`. Out of scope:
everything else in the design (earlier rounds closed it) and the content-only rule.

If these three parts need no change, say so plainly. Otherwise report findings as a numbered list, each with severity
(High / Medium / Low), the decision or line, the concrete failure (inputs → outcome), and a suggested fix. Do not edit
any file.
