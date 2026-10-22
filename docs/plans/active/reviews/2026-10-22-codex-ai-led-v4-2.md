# Codex design review of ADR-0017/0018 v4, round 2 of 2

Reviewer: codex-cli 0.155.0, model gpt-6-astra, reasoning high, read-only sandbox, 2026-10-22. Prompt: [prompts/ai-led-v4-codex-2.md](prompts/ai-led-v4-codex-2.md).

ine | **Resolved** — the watcher calls `terminate(time_up_session)` before cancelling the scope. |
| 3 — Medium: exception-safe finalization | **Partly** — body exceptions and delivery failures are covered; exceptions raised at task-group exit still bypass finalization (F2). |
| 4 — Medium: extraction context | **Resolved** — `brain_call` now reads the explicit context’s deadline, ledger and latch policy. |
| 5 — Medium: refused kind reselected | **Partly** — exclusions reach construction and fallback, but disappear when negotiation resumes after the initial `settle` (F3). |
| 6 — Medium: low-autonomy consent | **Partly** — silence and two out-of-menu choices now wait/end; refusal and an unconstructible in-menu choice still execute unaccepted alternatives (F4). |
| 7 — Medium: soft deadline | **Partly** — delayed confirmation cannot start a boundary activity; grace continuations are explicitly permitted but still contradict the blanket prohibition on new activities (C1). |
| 8 — Medium: unconstructible END | **Resolved** for the reported content-owner/budget failure — static END needs no generation; exclusion of END introduces a separate failure (F5). |
| 9 — Medium: assignment before identification | **Resolved** — assignment follows identification and uses the adopted learner. |
| 10 — Medium: edge-tts seam | **Partly** — a connector is named, but it does not mediate WebSocket message bodies, and retained client retries conflict with token consumption (F1/F6). |
| 11 — Medium: local fallback loses answer | **Resolved** — an allow-listed local model skips filtering and receives the answer. |
| 12 — Medium: zero-day guest retention | **Partly** — ordinary unconfirmed guests are deleted and extraction skips guests; termination before identification still follows an expiry-only row (F8). |
| 13 — Medium: first failed retrieval | **Resolved** — first retrieval establishes a due date; success advances spacing, failure resets it, unavailable leaves it unchanged. |
| 14 — Medium: cross-learner forget race | **Partly** — writes are fenced while `forgetting=true`, but become permissible again after the learner row disappears (F7). |

For the five round-1 contradiction rows, in their original order:

| Row | Assessment |
|---|---|
| Encounters: teaching versus recall | **Resolved** — §§3.4 and 8.6 both name teaching and recall. |
| `idle_session` absent from latch | **Resolved** — it is now a latch value, and idle explicitly calls `terminate`. |
| Extraction scope versus `brain_call` | **Resolved** — the explicit post-session context removes the conflicting session reads. |
| Grace versus new activities | **Partly** — late boundary starts are blocked; the continuation exception still conflicts with §§1/6.3 (C1). |
| Local eligibility versus filtering | **Resolved** operationally — locality bypasses the filter; the unqualified privacy assertions/tests need updating (C3). |

The new defects and residual failures are ranked below.

1. **F1 — High, introduced by the WebSocket fix: connection authorization does not authorize the text subsequently sent.** [ADR-0018 §2](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:70)

   Trace: prepare filtered text A and obtain token T; pass `aiohttp_connector(destination, T)` to `Communicate` containing text B. The connector checks T when opening the WebSocket. The library subsequently sends B in an SSML frame. The connector receives neither that text nor a specified message-level interception hook, so it cannot recompute and compare its HMAC.

   The installed library calls [`websocket.send_str(...)`](/E:/GitHub/scil/Leafi/.venv/Lib/site-packages/edge_tts/communicate.py:444) after opening the connection. Checking that it honours `connector=` does not test payload mediation. The proposed replacement “built on the same connector” also needs an explicit message-level gate. Otherwise unfiltered text can leave through a correctly authorized connection.

2. **F2 — Medium, incomplete exception fix: the handler is inside the task group, but child exceptions emerge outside it.** [ADR-0017 §2](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:34)

   An input/control child raises `ValueError`. The task group cancels its siblings and raises an `ExceptionGroup` from `__aexit__`, after the inner `except`/`finally` has finished. Execution skips `finalize`, delivery and extraction; only lease release runs. A child translating cancellation into `Terminal` can produce the same escape.

   The probes distinguished this from the repaired paths: deadline cancellation and a body `ValueError` reached finalization; child failures did not. Finalization must surround task-group exit, with terminal groups handled there.

3. **F3 — Medium, incomplete exclusion fix: refusal history is lost between calls to `settle`.** [ADR-0017 §2.1](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:80)

   At autonomy 2, a queued skip rejects proposed reading during the initial `settle`. Its recursive call excludes reading and returns quiz. The learner then refuses quiz. `refused_of(act)` receives its default empty exclusion set, excludes only quiz, and selects the original reading proposal.

   At autonomy 8, the same failure occurs if another skip arrives while quiz is announced and is consumed by the final check. Keep exclusions as negotiation state across every branch.

4. **F4 — Medium, residual: low-autonomy approval applies only to the final fall-through path.** [ADR-0017 §2.1](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:104)

   These traces fail at **each of autonomy 0, 1, 2 and 3**:

   - Reading is offered; the learner says “no”; `refused_of` immediately returns a constructible quiz. Quiz starts without acceptance.
   - The learner names quiz, which is in the menu, but its generation fails. `settle([quiz, act.spec])` returns the original reading activity, again without acceptance.

   Both early returns bypass `if not agreed`. Approval must attach to the activity actually returned, rather than merely to having taken a named-choice branch.

5. **F5 — Medium, introduced by exclusion propagation: refusing END removes the only guaranteed fallback.** [ADR-0017 §§2.1, 3.3](/E:/GitHub/scil/Leafi/docs/adr/0017-ai-led-study-session.md:89)

   During grace, `menu = {end}`. At autonomy 0–3, END is offered and the learner says “no”. `refused_of(end)` produces an empty restricted menu. Both the default chain and appended END are checked against that empty menu, so `first_constructible` has no valid result.

   Making END’s content code-owned fixes budget failure, but does not fix this new exclusion failure. END must remain an unconditional terminal outcome outside ordinary kind exclusion.

6. **F6 — Medium, introduced integration mismatch: edge-tts retains retries and chunking outside the mediator.** [ADR-0018 §2](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:70)

   The installed `Communicate` constructor has no `max_retries` parameter. Its [`stream()` implementation](/E:/GitHub/scil/Leafi/.venv/Lib/site-packages/edge_tts/communicate.py:585) retries a 403 itself and opens streams for successive text chunks.

   After the connector consumes T on the first connection, a library retry presents spent T and is refused. Allowing that retry would instead violate the mediator-only exception. Text exceeding the library’s chunk size also needs multiple transmissions, although the ADR binds one token to the whole text. Specify message/chunk authorization and remove or replace the library-owned retry; connector support alone is insufficient.

7. **F7 — Medium, incomplete forget fix: deleting the learner deletes the fence.** [ADR-0018 §1](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:24)

   B has an in-flight result sourced from `[A, B]`. Forgetting A marks A, purges copies, performs the final rescan and deletes A’s row. B’s result then arrives. Its transaction finds **no source with `forgetting=true`**, because A no longer exists, and writes the copy.

   The in-memory SQL trace rejected the write during purge and accepted it after deletion. Require every source to **exist and not be forgetting**, or retain a durable tombstone. The cloud-off rule for deleted sources does not prevent local retention.

8. **F8 — Medium, incomplete zero-retention fix: early termination does not reach the new purge branch.** [ADR-0018 §1 guest end-state table](/E:/GitHub/scil/Leafi/docs/adr/0018-learners-and-privacy-v2.md:49)

   Set `guest.keep_days=0`, then stop before `identify` returns. The applicable terminal row assigns `unconfirmed` and an already-expired timestamp; it does not delete the guest. No second application of the table or post-finalization sweep is specified.

   Normalize the early-terminal outcome first, then apply zero-retention deletion in the same finalization. Skipping guest extraction correctly prevents notes from recreating the ordinary purged guest’s history.

These contradictions also remain inside the ADRs:

| Severity | Sections | Concrete conflict |
|---|---|---|
| **Medium — C1** | ADR-0017 §§1/6.3 versus §2 and Confirmation | Reading page A ends during grace with `page_turned`; `continuation_allowed` permits a new page-B activity and its test requires that behavior. §§1/6.3 still prohibit **all** new activity starts. State the continuation exception consistently, including its relationship to construction against `{end}`. |
| **Medium — C2** | ADR-0017 §§1–2 versus §3.1 | A reading activity raises an unexpected exception. The new handler requires its final status to be `internal_error`, but that status is absent from both the universal and kind-specific allowed statuses. The mandated exhaustive status test must reject the required result. |
| **Medium — C3** | ADR-0018 §2 locality versus its table, §3 and Confirmation | An allow-listed local judge receives learner text with `cloud.text=off`, including real names because pseudonymisation is skipped. Confirmation simultaneously requires no learner canary with cloud text off and no real name in **any body**. Qualify those assertions by cloud destination. |
| **Low — C4** | ADR-0017 §1 versus §2 | A confirmation arrives after the soft deadline; the new bare `break` ends the session without `terminate` or a terminal latch value. Ordinary END also exits directly. “Setting the latch is the only way to stop the session” needs an explicit normal-completion exception or a common ending path. |
| **Low — C5** | ADR-0018 §1 identification dialogue versus §5 | With retention set to 0 or 30 days, identification still promises “kept for a week”. The spoken retention promise contradicts the configured behavior. |
| **Low — C6** | ADR-0018 §2 versus Confirmation | The new edge-tts adapter must use `egress.aiohttp_connector`; the architecture test still requires SDK clients **only through `egress.client`**. The permitted factory list needs the new seam. |

The remaining requested hand-executions have coherent paths:

- **Watcher/`terminate`:** expiry sets `time_up_session`, then cancels; a prior `stop` remains the first terminal reason.
- **Post-session context:** after stop, deadline or exhausted session budget, extraction uses its fresh deadline and allowance without consulting the session latch. Delivery failure no longer skips extraction.
- **Wait/end:** at autonomy 0–3, two silences or two out-of-menu choices return the internal wait even at the cycle cap; another unaccepted boundary after that wait returns END. At autonomy 8, negotiation does not listen and reaches its final checkpoint/skip check.
- **HTTP attempt token:** altered body or recipient is refused; concurrent adapter submissions admit only the first; media has no retry; the mediator’s one text retry retains the same request/body and reserves another transmission charge.
- **Locality:** an eligible local `item_used` judge retains the answer with cloud text off. The defect here is the contradictory assertions, not the operational path.
- **Recall:** first failure on day 0 makes recall due on day 1; success then advances to two days later; a subsequent failure resets to one day later; unavailable leaves the due date unchanged.
