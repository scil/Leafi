# Codex review of the ADR-0017/0018 v4 increment c467aa7..abcbc5f (single round)

Reviewer: codex-cli 0.155.0, model gpt-6-astra, reasoning high, read-only sandbox, 2026-10-22. Prompt: [prompts/ai-led-v4-codex-increment-2.md](prompts/ai-led-v4-codex-increment-2.md).

tokens used
58,395
**No High findings.** H1 is resolved. The remaining problems are in negotiation ordering, exclusions, and re-asking. This was a single-round review of the increment; no files were edited.

| Fallback finding | Assessment |
|---|---|
| H1 | **Resolved** — `spawn()` sets the terminal latch before propagating a child error. |
| M1 | **Resolved** — the counter now honours `silence_reasks`; rebuilding the offer introduces a separate defect below. |
| M2 | **Resolved** — save-time ranges, ordered thresholds, hidden empty bands, and setting-relative prose are specified. |
| M3 | **Partly** — low-autonomy exhaustion no longer immediately executes `end`, but the default chain’s `end` still precedes and shadows `other_allowed`. |
| M4 | **Partly** — later naming removes an exclusion, and construction failure gets an explanation; the offer cap can still discard a named choice, and the current short-list menu still contains the failed kind. |
| M5 | **Resolved** — library-mode lines explicitly pass through `prepare`, including pseudonymisation. |
| L1 | **Resolved** — pending skips are drained before an offer without excluding an unheard candidate or spending an offer. |
| L2 | **Resolved** — `b` preserves exclusions and counters across `Reobserve`. |
| L3 | **Resolved** — early-terminal normalisation applies only when the guest has no reason; `declined` survives. |
| L4 | **Partly** — library-mode refusal coverage is restored; a positive control using the actual library inside a grant is still not explicitly specified. |
| L5 | **Resolved** — `tts.edge_mode` is marked †. |
| L6 | **Resolved** — the mediator extracts spoken text for the HMAC and separately checks the SSML wrapper and headers. |
| L7 | **Resolved** — the comment now leaves escaping `BaseException` cases to startup recovery. |
| C1 | **Resolved** — §6.3 explicitly permits grace-period continuations and exempts their construction from the menu. |
| C3 | **Resolved** — the data-class table is explicitly scoped to cloud destinations. |

The increment introduces these defects in [ADR-0017 §2.1](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:78):

1. **Medium — `end` can now be excluded** (lines 97, 105). Removing the early `end` return makes both refusal branches reachable with `a.kind == "end"`, yet both add it to `b.excluded`. Concrete case: at the cycle cap, the menu is `{read_listen, read_aloud, end}`; reading aloud cannot construct. With `max_offers = 5`, refuse reading, then refuse `end`. The next construction returns `None` and produces a wait, with `end` in the persistent exclusion set. At autonomy 9, skips during the announcements produce the same result. This directly contradicts “end is never excluded.”

2. **Medium — a silence re-ask rebuilds the activity instead of repeating it** (lines 86, 114). At autonomy 2, set `max_offers = 1`, `silence_reasks = 3`, and put a Brain-owned quiz first. The first quiz consumes the remaining generation allowance; silence decrements `b.offers` to zero. The next iteration reconstructs: quiz generation can no longer run, so reading is offered instead. That different offer is charged as offer 1 again. Thus the new decrement can hide additional distinct offers beyond `max_offers`, and even successful regeneration can change the quiz being “re-asked.” Preserve the constructed offer for a re-ask, or count a replacement as a new offer.

3. **Low — excluding an unbuildable named kind does not update the current short list** (lines 84, 93, 101). At autonomy 0, the learner names `quiz`; construction fails and reading is selected. The code says quiz is unavailable and adds it to `b.excluded`, but `m` was already computed. `describe_choices(..., m, ...)` can immediately offer quiz again in the same prompt. Refresh `m` before describing choices.

4. **Low — `other_allowed` requires an unspecified ordering** (line 118). It promises “menu order,” but §3.2 defines `allowed(s)` as a set. With a policy containing only an unavailable reading step, both `break` and `read_aloud` can remain constructible; their fallback precedence is undefined. Specify a stable order independently of the set.

Two incomplete repairs also matter when executing the changed loop:

- **Medium, M3 — appended alternatives remain behind the default `end`.** With defaults, refuse `review_anki`, then `read_listen`. Candidate 3 is `end`, because §3.3 places it in `default_chain` before the appended `other_allowed`. At autonomy 0/2, silence eventually waits; at autonomy 5, silence ends the session. Available `break` and `read_aloud` are never reached. Making `"end"` last inside `other_allowed` does not move the earlier copy.
- **Medium, M4 — the offer-limit check precedes fulfilling a named choice.** With `max_offers = 1`, the first prompt receives “read aloud.” The loop stores `b.wanted`, then immediately returns `wait_or_end()` at the top of the next iteration without trying it. Likewise, a later named choice overriding a refusal works only if it arrives before the final permitted offer. This ordering predates the increment, but remains a limitation of its M4 repair.

The hand-execution results are:

| Case | Autonomy 0 | Autonomy 2 | Autonomy 5 | Autonomy 9 |
|---|---|---|---|---|
| Default bands; refuse first candidate, then silence | Short list; replacement re-asked, then wait | Asked proposal; replacement re-asked, then wait | Replacement starts after silence | No listen; queued skips move to the next announcement |
| Refuse A on offer 1, name A on offer 2; default cap 3 | Exclusion removed; A constructs and starts | Same | Same | Named response is not read |
| Name an unbuildable kind, with room below cap | Explanation, then short list using stale `m` | Explanation, then asks about replacement | Explanation, then replacement starts on silence | Not reachable through the announcement branch |
| `first_constructible` returns `None` | Wait, or end following a previous wait | Same | Same | Same |

With the specified always-constructible `end` still in `m`, `first_constructible` cannot ordinarily return `None`. The newly introduced exclusion of `end` makes that branch reachable. If `b.wanted` is pending when construction returns `None`, the return also bypasses its promised failure explanation.

For silence counting below `bands.argue`, start with `b.offers = b.silences = 0`:

- `silence_reasks = 0`: first silence sets `b.silences = 1`; immediately waits.
- `silence_reasks = 2`: the first two silences decrement `b.offers`; the third waits.
- At the limits `max_offers = 1`, `silence_reasks = 3`: four silent prompts occur before waiting. This correctly implements three re-asks **only if the candidate stays the same**.
- `Reobserve` retains these counters and exclusions. Starting the wait activity clears the boundary state; exhaustion at the following boundary returns `end`.

Threshold limits execute consistently:

| `(ask, argue, announce)` | Autonomy 0 | Autonomy 2 | Autonomy 5 | Autonomy 9 |
|---|---|---|---|---|
| `(4, 4, 11)` | Short list | Short list | Argue/listen | Argue/listen |
| `(1, 1, 1)` | Short list | Announce | Announce | Announce |
| `(11, 11, 11)` | Short list | Short list | Short list | Short list |

Equal thresholds create empty bands, now explicitly hidden. `announce = 11` disables announcement for every valid autonomy. The valid ask/wait duration endpoints change timing, not these branches.

Finally, the child-failure trace in [ADR-0017 §§1–2](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:23) now succeeds: while the body awaits a listen, a child raises; its wrapper calls `terminate(s, internal_error)` before re-raising; the cancelled activity maps to `internal_error`, which belongs to `TERMINAL`; the body exits, the exception-group handler runs, `finalize` is reached, and the outer `finally` releases the lease. The previous unset-latch loop is removed.
