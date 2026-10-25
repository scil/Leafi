Confirming round. Review **E8, E9 and E10's commit order** of
`docs/plans/active/2026-10-24-content-only-egress-design.md` **rev 5** as a design, not as prose. The rounds so far:
`reviews/2026-10-24-egress-e8e9-round-1-comparison.md` (U1–U12), `…-egress-e8e9-rev2-codex.md` (V1–V8),
`…-egress-e8e9-rev3-codex.md` (W1–W5), `…-egress-e9-rev4-claude.md` (X1–X6). `git diff 0c83d44 57d911c --
docs/plans/active/2026-10-24-content-only-egress-design.md` shows what rev 5 changed. E1–E5 are implemented
(`git show 714f4e8 accca30`); E1–E7 and the content-only rule are the owner's decisions and out of scope except where
E8–E10 depend on them.

1. For each of X1–X6: closed, partly closed (what is left), or not closed? Check each claim against the code:
   `leafi/devices/go2rtc_camera.py` (`prepare`, `play`, `stop`, construction), `leafi/core/hub.py`,
   `leafi/privacy/runtime.py` (`attribution`, `attribute`), `leafi/services/tts/__init__.py`,
   `leafi/study/harness/{rows,loop,identify,guests}.py`, `leafi/study/records.py` (`close_stale_sessions`,
   `forget_learner`), `leafi/study/anki.py` (`sync_outbox`), `leafi/core/learner_store.py`, `tests/test_architecture.py`.
2. What does rev 5 introduce that is new and wrong or underspecified? In particular: deleting the camera copy after
   playback (does go2rtc read the file after `play()` returns? is there a path where the same `<key>.cam.wav` is
   prepared for two plays at once, or a stop/skip mid-playback? Windows file locks); reading the cache owner from
   `runtime.attribution` (is it set in every context that synthesises — the hub's say from a different task, a
   `spawn`ed child, the filler, `with_filler`, before `identify` returns? contextvars copy into tasks at creation);
   deleting kept guests' folders on `forget` while another session's guest is live; the standalone guard in
   `close_stale_sessions`; the written-out allow-list (complete against every raw UPDATE of the owned tables?).
3. Anything left that makes commit 3 impossible to land with the full suite green.

If nothing in E8–E10 needs to change, say so plainly. Otherwise report findings as a numbered list, each with severity
(High / Medium / Low), the decision or line, the concrete failure (inputs → outcome), and a suggested fix. Do not edit
any file.
