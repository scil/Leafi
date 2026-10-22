# Fallback review of the ADR-0017/0018 v4 increment (70b2076..HEAD)

Reviewer: a fresh Claude agent (fallback for codex, whose quota was exhausted), 2026-10-22. Prompt: [prompts/ai-led-v4-codex-increment.md](prompts/ai-led-v4-codex-increment.md).

Line numbers below are of the current files (`docs/adr/0017-ai-led-study-session.md`, `docs/adr/0018-learners-and-privacy-v2.md`). Owner decisions (a) `tts.edge_mode` and (b) negotiation numbers as settings are taken as settled; findings about them concern only consistency and specification gaps, not the choice.

## 1. Round-2 findings

| Finding | Status |
|---|---|
| F1 (connection grant does not authorise the text sent) | **Superseded by owner decision (a)** for the default `library` mode; the `mediated` option gates each outgoing text frame against its chunk's token (one specification gap, L6). |
| F2 (child exceptions bypass finalize) | **Partly** — child errors now reach `except*` and `finalize`, but the child-triggered cancellation reaches the body while `s.terminal` is still `None` (H1). |
| F3 (exclusions lost between `settle` calls) | **Resolved** within one negotiation (`excluded` is loop state, lines 80–116); exclusions still reset on `Reobserve` (L2). |
| F4 (unaccepted alternative starts at 0–3) | **Resolved** — below `bands.argue` the only returns are "yes" to `a` (109), the named kind constructed as named (92), `end` (91) or `wait_or_end` (84, 115). |
| F5 (refusing END empties the menu) | **Resolved** — `end` is never added to `excluded` (90, and 97/108 cannot see `end` because 91 returns first); `or end_activity(s)` backs the chain (87). |
| F6 (library retries and chunking outside the mediator) | **Superseded by owner decision (a)** for `library`; `mediated` chunks itself, one token per chunk, no own retry. |
| F7 (deleting the learner deletes the fence) | **Resolved** — the conditional insert requires every source to exist and not be forgetting; test added. |
| F8 (zero retention after an early terminal) | **Resolved** — normalise, then apply zero retention in the same `finalize` (small residual, L3). |
| C1 (continuation during grace) | **Partly** — §1 now states the exception; §6.3's `session.end_mode` row (line 308) still says "no new activity starts", and whether `continuation(s)` passes `construct` rule 1 (`kind ∈ allowed(s)`, which is `{end}` in grace, line 157/202) is still unstated. |
| C2 (`internal_error` not an allowed status) | **Resolved** — added to §3.1's universal statuses. |
| C3 (locality vs "no learner text / no real name in any body") | **Partly** — Confirmation now says cloud-destination; ADR-0018 §2's data-class table (lines 83–84: learner text "removed" with `cloud.text` off, real names "never") still reads unqualified beside the locality stage (line 76). |
| C4 (only the latch stops a session) | **Resolved** — "interrupt" plus the stated normal endings (`end`, soft deadline at a boundary). |
| C5 (guest notice promises a week) | **Resolved** — `guest_notice(guest.keep_days)`, with a 0-day wording and a test. |
| C6 (architecture test names only `egress.client`) | **Resolved** — `egress.ws_client` and the `edge-tts` library exception (imported only by `tts/edge.py`) are named. |

## 2. Defects the increment introduces

There is **one High finding** (H1).

### Hand-execution: `run_session` with a child task raising (ADR-0017 §2, lines 34–62)

1. The body is in `run_activity(read_listen)` awaiting a listen; `s.terminal = None`. The task group holds the deadline watcher and the control readers (§1: console reader, Listener control parser, lease watcher post control events).
2. A child (say the console reader, on a `UnicodeDecodeError`) raises. anyio's `TaskGroup` records it and cancels **`tg.cancel_scope`** — not via `terminate`. The watcher and the other children are cancelled; the host task (the body) receives the cancellation at its current await.
3. `run_activity` "catches the scope's cancellation and maps it to `s.terminal`'s status" (§1, line 23). The latch is `None`: the mapping has no value. This breaks §1's own invariant "the latch is always set before anything is cancelled".
4. Line 56: `run_activity` returns (the loop's `if last.status in TERMINAL: break` shows it returns, not re-raises). The mapped status is not in `TERMINAL`, so no break. Line 43: `checkpoint(s)` raises `Terminal` only when the latch is set — it is not. Lines 44–48: `observe` / `sequence` → `brain_call` await again inside a cancelled scope; anyio cancellation is level-triggered, so each await is cancelled at once, each layer catches and maps to `None`, and returns.
5. Nothing in the loop can now end it: the latch is unset, the deadline watcher was cancelled in step 2, and `terminate(s, internal_error)` runs only in `except*` (line 60), which is reached only after the task group exits, which needs the body to return. Outcome depends on unspecified behaviour of `negotiate` under a `None` latch; at best the activity row gets an undefined status, at worst the session spins with the lease held and `finalize` never runs.
6. Compare the paths that do work: a **body** exception (e.g. `ValueError` in `observe`) unwinds through the inner `finally`, the group raises `ExceptionGroup([ValueError])`, `except* Exception` sets `internal_error`, `finalize` closes the running row with it — correct. A `stop`: `terminate` sets the latch then cancels `s.scope`; layers map to `stopped`; line 56 breaks; `finalize` — correct. A body `Terminal` plus a child `ValueError` together: both `except*` clauses run, the latch is monotonic — correct.

### Hand-execution: `negotiate` (ADR-0017 §2.1, lines 78–117), default bands (ask 2, argue 4, announce 8, max_offers 3)

Menu used: `{end, break, review_anki, read_listen, read_aloud, quiz}`; default arm, so `props = []` and candidates come from `default_chain` (review_anki, …, read_listen, end).

**"No" then silence.**
- Autonomy 0: offer 1 `review_anki` with a 3-item list (offers=1) → "no" → `excluded={review_anki}` (108). Offer 2 `read_listen` (offers=2) → silence → `silence_reasked=True` (116). Offer 3 `read_listen` (offers=3) → silence → `wait_or_end` (115) → `wait_activity`. Correct per decision 4.
- Autonomy 2: same path with "Shall we …? Or something else?" (102). Correct.
- Autonomy 5: offer 1 argued (100), "no" → excluded; offer 2 `read_listen` argued → silence → line 114 `Run(read_listen)`. Correct per table.
- Autonomy 9: no listen; a spoken "no" is never heard; only a queued skip counts (97). `Run(review_anki)`. Consistent with the table ("always").

**A named choice that cannot be built.**
- Autonomy 0/2: offer 1 `review_anki`; learner says "quiz" (in `m`) → `wanted=quiz` (111). Iteration 2: `learner_spec(quiz)` rejected (generation fails), `a=review_anki`; 92 false → `wanted=None`, offers=2, same offer again. No `why_not` is said (112 runs only for kinds outside `m`), and `quiz` stays in `m`, so the 0–1 short list (`describe_choices(s, a, m, …)`) can list quiz again (M4).
- Autonomy 5: as above, then silence → line 114 starts `review_anki`: the learner asked for quiz, was not told it is unavailable, and the original proposal starts on silence (M4).
- Autonomy 9: not reachable (no listen).

**A skip during construction.** Skip posted while `first_constructible` generates quiz content. Line 89 epoch unchanged; line 90 excludes `quiz` (never spoken), drains, offers=1, continue. Bounded and safe at every band; it spends an offer on an unheard candidate (L1).

**`end` as the only menu item** (`menu = {end}`). `m={end}`; `default_chain` gives `end` (or `or end_activity(s)` if the household removed the step); line 91 returns `Run(end)` at every band. With a queued skip: line 90 does not exclude `end`, offers=1, next iteration returns `Run(end)`. Correct; F5 is fixed.

**Unusual thresholds.**
- `bands.ask = bands.argue = 4`: autonomy 2–3 fall to the short-list branch (104); the ask band is empty; the table row renders "4–3". Behaviour is consistent; display is not.
- `bands.argue = bands.announce = 8`: autonomy 4–7 now ask and need a yes. Consistent.
- `bands.ask = 6 > bands.argue = 4`: check order (95, 99, 101) makes 4–5 argue and 0–3 short-list; the ask band is unreachable. Deterministic, but no validation rejects it.
- `bands.announce = 0` or `bands.argue = 0`: no consent at autonomy 0, contradicting the prose at line 131 ("At autonomy 0–3 an activity starts only on the learner's yes"), which hard-codes the default bands.
- `negotiation.max_offers = 0`: line 84 returns `wait_or_end` before any offer, every boundary — the session waits once and then ends without ever proposing anything. `negotiation.ask_s = 0`: every listen is silence, so 4–7 start everything unheard and 0–3 always wait then end (M2).

### High

- **H1 — ADR-0017 §§1–2 (lines 23, 34–61): a child exception cancels the body before the latch is set.** Scenario: trace above — console reader raises during `read_listen`; `tg.cancel_scope` cancels the body with `s.terminal = None`; `run_activity` maps cancellation to an undefined status and returns; line 56 does not break; line 43's `checkpoint` does not raise; the deadline watcher is already cancelled; `except*` (line 60) cannot run until the body returns. The increment moved the handler outside the task group (fixing F2's skipped `finalize`) but did not give child failures a path through `terminate`. Fix direction: spawn every child through a wrapper that calls `terminate(s, internal_error)` before re-raising, so the latch is set before the group cancels; and make the one mapping function treat a cancellation with `s.terminal is None` as `internal_error` (calling `terminate`). Add a test: a child raises during an activity → activity row `internal_error`, `finalize` reached, lease released.

### Medium

- **M1 — ADR-0017 §2.1 (lines 82, 115–116, 122, 126): `negotiation.silence_reasks` has no effect.** The pseudocode (the rule) uses a boolean `silence_reasked`, so it re-asks exactly once whatever the setting. Scenario: owner sets `silence_reasks = 0` → the table promises no re-ask; at autonomy 2 Leafi still re-asks once. With `2`, it still waits after the second silence. Replace the boolean with a counter compared to the setting.
- **M2 — ADR-0017 §2.1 (lines 122–131): the new settings have no ranges or save-time validation, and the prose hard-codes the defaults.** Scenarios: `max_offers = 0` (every boundary waits then ends without an offer), `ask_s = 0` (silence always; at 4–7 every proposal starts unheard), `choices = 0` (an empty list is asked), `bands.ask > bands.argue` (a band the table shows as "6–3"). Line 131 says "at autonomy 0–3 … at most three offers", which is false once the thresholds or `max_offers` change. Give each setting a range and an ordering constraint (`0 ≤ ask ≤ argue ≤ announce ≤ 11`, `max_offers ≥ 1`, `ask_s ≥` some floor), reject at save like `policy.default_order`, and phrase line 131 in terms of the settings.
- **M3 — ADR-0017 §2.1 (lines 87, 91 vs the table at 126–127 and prose at 131): at 0–3, refusing the chain ends the session immediately, not "offered again … then Leafi waits".** Scenario: autonomy 2, default arm, first boundary: `review_anki` → "no"; `read_listen` → "no"; next `a = end` (the default chain's `always` step) → line 91 `Run(end)`, closing line, session over after two refusals and no wait. `break` and `read_aloud`, both in the menu, are never offered because they are not in the default order. Either say in the table that refusing every candidate ends the session, or route an exhausted chain at < `bands.argue` through `wait_or_end` and let `describe_choices` draw from the menu.
- **M4 — ADR-0017 §2.1 (lines 87, 92–93, 110–113): the learner's named choice.** (a) A kind the learner refused earlier in the same negotiation and then names is answered with `why_not` (it is no longer in `m`), so the learner is told an available activity is unavailable and cannot change their mind. Scenario: autonomy 2, "no" to reading, then "let's read after all" → `why_not(read_listen)`. Exclusion should bind Leafi's proposals, not the learner's own choice. (b) A named kind in the menu that fails construction gets no explanation, stays in `m` (so the short list can offer it again and the learner can pick it again, re-running the failed generation), and at 4–7 the replacement starts on silence (trace above). Say `why_not` when `wanted` was not constructed, and exclude it from `describe_choices` for this negotiation.
- **M5 — ADR-0018 §2 (line 188) and caller table (line 205): in `library` mode, whether `prepare` still runs on each line before the library gets it is unstated.** The text says `egress` writes an attempt row and opens a grant; it does not say the provenance filter and pseudonymisation run on the line. Scenario: a `system` line "Well done, Mia!" (household term) is spoken through edge-tts; `tests/test_privacy.py` asserts no real name in any **cloud-destination** body, and edge-tts is one, so either the pipeline runs (and the line is spoken with a placeholder, which needs a rule), or the test and the repository boundary ("MUST NOT send … the learner's name") fail. This asks for a statement, not a change of decision (a).

### Low

- **L1 — ADR-0017 §2.1 (lines 90, 97, 108): skip handling is uneven.** Line 90 drains, 97 and 108 do not: two quick skips at autonomy 9 skip the announced candidate and then, at line 90, also exclude the next candidate unheard. A stray skip pressed as the previous activity ended, or one left queued when line 89 returned `Reobserve`, excludes the first candidate of the next negotiation and spends an offer.
- **L2 — ADR-0017 §2.1: `Reobserve` resets `excluded`, `offers` and `silence_reasked`.** Scenario: autonomy 2, "no" to reading, the learner turns a page (epoch bump) → the new negotiation proposes reading again; repeated epoch changes also evade the `max_offers` bound. State whether exclusions survive a re-observe within one boundary.
- **L3 — ADR-0018 §1 (line 57): the early-terminal row normalises to `unconfirmed` unconditionally.** If `set_guest(s, "declined")` commits and the cancel lands before `identify` returns (any await in between), `finalize` overwrites `declined` and keeps the guest for `guest.keep_days`. Qualify the row as the crash row is: "a guest with neither reason nor expiry".
- **L4 — ADR-0018 Confirmation (line 214): `tests/test_netguard.py` no longer lists the `edge_tts` library** in refusals or positive controls, though `library` is the default; only the Leafi adapter is tested at the socket level. Keep both (aiohttp's resolver choice decides whether the patched `getaddrinfo` sees it at all).
- **L5 — ADR-0018 §5 (line 196): `tts.edge_mode` is not marked †.** Switching `mediated` → `library` widens unchecked egress without the typed confirmation the other egress-widening keys need.
- **L6 — ADR-0018 §2 (line 188): the mediated frame check is underspecified.** The outgoing frame is an SSML message with headers (request id, timestamp, voice), not the bare chunk; say that the HMAC is computed over the text extracted from the fixed SSML template (after XML escaping is undone or applied consistently).
- **L7 — ADR-0017 §2 (line 62): "always reached once the session exists"** is not true for `BaseException` (`KeyboardInterrupt`, `SystemExit`, an outer cancellation at supervisor shutdown); `except* Exception` does not catch them. Startup recovery covers it; the comment should say so.
