# M5 egress design rev 3 — codex increment review

Reviewer: codex `gpt-6-astra`, reasoning high, read-only, on `reviews/prompts/m5-design-rev3.md`, 2026-10-23. Verbatim final answer.

**Revision 3 is substantially better, but High issues remain. I would not start implementation against it unchanged.** The main blockers are policy-version consistency, transmission authorization, connection ownership, incomplete bootstrap coverage, SDK serialization, and rollout gaps.

The two enforcement seams, destination registry, atomic token removal, field-level filtering before encoding, provenance propagation, prepare-before-chunking, and unconditional M5 media refusal are sound.

Items 1–28 assess the previous review. For **closed** items, severity records the original issue’s significance; it does not indicate a remaining blocker. Items 29–33 detail additional revision-3 defects.

1. **High — R1: partly — D5, guest ownership.**  
   Transactional re-keying during adoption and delaying guest disposal until delivery finishes address the original failures. However, delaying disposal in `run_session` does not exclude other deleters. [`finalize()` sets `ended_at` before delivery](/E:/GitHub/scil/Leafi/leafi/study/harness/loop.py:197); the guest sweeper treats such sessions as disposable, and `forget` uses the same open-session distinction. An attempt or its owner can disappear during delivery.

   **Fix:** make delivery’s ownership reservation visible to every deletion/recovery path, or define a durable transfer before finalization. Test deletion racing with post-session delivery.

2. **High — R2: partly — D12/D18/D19, legacy-term handover.**  
   Earlier settings primitives, migration-time import and temporary dual-reading are sound. But a single import in M5a does not cover terms added to `REDACT_TERMS` afterward. Fresh v6 databases also bypass migration 6. Those terms work during dual-reading and can disappear from protection when M5d ends it.

   **Fix:** reconcile the effective legacy list immediately before retiring it, including fresh databases and changes since migration. Test both paths.

3. **High — R3: closed — D10, mixed-script matching.**  
   NFC normalization and Latin-script boundaries explicitly address the original mixed-script failure. Preserve the Chinese/Latin, composed/decomposed, possessive and hyphen tests.

4. **High — R4: closed for allocation and replacement — D10/D11.**  
   Transactional uniqueness, collision rechecks, exhaustion fallback, request-specific alternates and detection before substitution answer the allocation concerns. Forgotten-alias identity remains separately under item 24.

5. **High — R5: closed — D6/D7, token handoff and replay.**  
   Request-specific handoff and atomic removal from public lookup fix both ambient-context ambiguity and same-request replay. A private capability belonging only to the first transport invocation is sound.

   The `x-leafi-token` header is a workable internal carrier: my offline SDK probe confirmed that `extra_headers` reaches the transport. Keep unconditional removal before delegation, rejection of ambiguous duplicate token headers, and tests covering refusal and retry paths.

6. **High — R6: partly — D6, exact request binding.**  
   Filtering Bark’s text fields before URL quoting closes the encoded-path problem. Binding the final URL, constrained headers and body is also sound. However, the SDK does not currently produce the canonical representation D6 requires; see item 29.

   **Fix:** specify the serialization handoff that actually puts the prepared bytes on the wire.

7. **High — R7: closed — D2, grant revocation and placement.**  
   The shared active set revokes copied grant IDs, and opening grants inside the synchronous/asynchronous transport supplies the connecting context. Preserve both thread and child-task tests.

8. **High — R8: partly — D2, retained sockets and process scope.**  
   Moving installation out of `leafi/__init__` correctly avoids imposing study policy on habit processes. However, the replacement entry-point coverage is incomplete, and disabling idle keep-alive does not establish the claimed socket ownership. See items 30–31.

9. **High — R9: closed — D2/D3, LAN exemptions.**  
   Address/port tuples, private-address validation, gateway precedence and no-network precedence remain sound. The DHCP restart limitation is explicit.

10. **High — R10: closed — D13, TTS provenance.**  
    Required provenance, source IDs through the complete call chain, conservative external-card handling, identification classification and cache sidecars address the issue.

11. **Medium — R11: closed — D13, surrogate speech.**  
    The “never speaks a surrogate” guarantee is now correctly scoped to local routing. Language/backend selection precedes privacy routing, and protected terms are checked regardless of text class.

12. **High — R12: closed — D14, chunk boundaries.**  
    Preparing the complete line before chunking, with sources and mappings inherited by chunk tokens, closes the split-term leak. Fixed-frame verification is sound.

13. **High — R13: partly — D15/D16, Hugging Face request adaptation.**  
    Per-request preparation, HEAD support and explicit redirect-chain state are substantial improvements. But the fixed schema permits only repository `/resolve/…` and model-revision API paths while refusing everything else. Download continuation can use a CDN URL whose path has neither shape. The installed library explicitly takes the metadata response’s `Location` as the subsequent download URL.

    **Fix:** distinguish initial requests from continuations authorized by a previously validated redirect. Bind continuation capabilities to the exact target, file, method, deadline and hop count; specify HEAD-to-GET handling and range/resume requests. The fake-hub test must include relative redirects, an absolute CDN target and concurrent files.

14. **Medium — R14: partly — D11/M5c–M5d, detector fallback visibility.**  
    The owner-approved fallback is now reconciled with the ADR and canaries. That closes the contract mismatch. Effective-state reporting, however, lands in M5d after fallback becomes operational in M5c; the owner also requested a log warning.

    **Fix:** ship the missing-model warning and effective-state reporting with activation in M5c.

15. **High — R15: closed — D15, RapidOCR.**  
    Mediated provisioning followed by explicit local model paths removes the broad grant. The test forbidding its Requests downloader is appropriate.

16. **High — R16: closed at design level — D12, confirmation.**  
    Both ADR wording changes are named, and CLI confirmation identifies the learner, operation and exact value. Atomic value/version/consent writes are sound. Ensure the CLI is connected to that writer before it becomes available.

17. **High — R17: partly — D12, revalidation.**  
    The version vector now includes household policy, protected names, source privacy versions, missing sources and forgetting. Those additions are correct. It still lacks a reliable binding between the version and effective settings, and a defined authorization boundary relative to concurrent writers. See items 32–33.

18. **Medium — R18: partly — D8, crash accounting.**  
    PID plus process start time resolves the original live-process/reused-PID ambiguity. D8 only specifies updating transmission counts in `finally`, though; process termination bypasses `finally`. Recovery can mark an attempt unknown without knowing that a transmission had already started.

    **Fix:** durably record each transmission reservation before sending, then record its outcome afterward. Distinguish an authorized/started attempt from proven delivery, and test abrupt termination between these writes.

19. **High — R19: partly — D10, school enrollment.**  
    Age-band derivation and the scheduled age-policy amendment answer the age concern. The new **“skippable”** school question contradicts ADR-0018 §3, which requires a school name or an explicit “no school.” An unanswered school can subsequently appear in page text, where the detector does not run.

    **Fix:** require the school/no-school answer as specified, with backfill for existing learners. An “unknown/skip” state would need an explicit contract change; the recorded owner decisions do not authorize it.

20. **Medium — R20: closed — D4/D13/D17, routing and probes.**  
    Named probe schemas, the OpenAI-compatible Ollama endpoint, preserved measurement gating and language-specific TTS selection remain sound.

21. **Medium — R21: closed — D7/D9, refusal classification.**  
    Translating guard denials to synthetic 403 before retry classification fixes the HTTP gap. The separate exception-to-Faces path is appropriate for library-mode edge-tts.

22. **Medium — R22: partly — D2/D15, HF child bootstrap.**  
    The child process is a sound isolation boundary, but “leaves `HF_HUB_OFFLINE` unset” must explicitly mean **remove the inherited value**. The parent sets it to `1`; merely omitting an assignment in the child leaves it enabled. The installed library also recognizes `TRANSFORMERS_OFFLINE`. HF reads these settings at import time. [HF environment documentation](https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables).

    **Fix:** specify the child’s sanitized launch environment and bootstrap-before-import order, including inherited offline aliases. Test from an actually bootstrapped parent, not only a clean test environment.

23. **High — R23: closed for the missing schema state — D19.**  
    Migration 6 now enumerates the required state and explicitly avoids rerunning first-learner creation. Preserving ownership and comparing migrated/fresh schemas are sound.

    Carry the change through migration dispatch: the [current CLI requires a learner name and interprets `learner_id=None` as “already current”](/E:/GitHub/scil/Leafi/leafi/cli.py:173). Test v5→v6 without creating a learner, legacy upgrades, rollback and restoration. The legacy-term import limitation is item 2.

24. **Medium — R24: partly — D10, forgotten aliases.**  
    Moving a mapping to retained household-term identity answers the deletion-contract question. But one learner can have several retained names/aliases. Moving its single mapping to one `term:<id>` does not specify how the other alias terms retain that same identity; removing the chosen anchor may delete the mapping while aliases remain.

    **Fix:** define one retained person identity shared by all those terms, and delete its mapping only when that identity has no retained terms. Test name/alias continuity and removal of the anchor term.

25. **Medium — R25: closed — D5, notifications.**  
    Construction from a fixed template, surrogate plus integer counts, the “a reader” variant, and the explicit ADR exception answer the concern. This is a sound constrained notification interface.

26. **High — R26: closed for the named policy changes — D11/D18.**  
    M5c now explicitly amends age coverage, detector fallback, confirmation, notifications, the egress table and AGENTS.md with enforcement. The already-recorded owner choices do not need fresh approval merely to document them.

27. **High — R27: closed — D20, media.**  
    Unconditional refusal of every media transmission, including requests presenting consent IDs, cleanly separates M5 from M9.

28. **High — R28: partly — D18, independently viable commits.**  
    The dependency order is much improved, but M5a installs `bootstrap`, which also installs D15’s environment. Setting HF offline then breaks the [existing in-process doctor downloader](/E:/GitHub/scil/Leafi/leafi/doctor.py:194), before the child adapter exists or callers switch. “Log-only” describes guard refusals; it does not neutralize environment changes.

    **Fix:** keep bootstrap’s behavioral side effects inactive until their callers switch, or move the corresponding caller adaptation into the same step. Explicitly schedule the household policy writer integration by M5c, move fallback notices there, and perform item 2’s final term reconciliation before cleanup.

29. **High — new — D6, canonical bytes versus SDK serialization.**  
    Revision 3 requires sorted canonical JSON and rejects any byte difference. An offline probe using the installed `anthropic==1.17.0` showed that its final body differs from that canonical encoding. Its serializer preserves dictionary order, including nested objects. Supplying prepared fields and `extra_headers` does not supply prepared body bytes. SDK-generated headers also need an explicit binding policy.

    **Fix:** define a concrete adapter/client serialization seam that validates the SDK-built request against the prepared representation and sends the exact authorized bytes, or bind the exact SDK-built representation after field filtering. Do not resolve this by accepting equivalent input but transmitting unchecked bytes. Make the real SDK positive-control test a prerequisite to finalizing D6.

30. **High — new — D2, bootstrap coverage excludes existing callers.**  
    Enumerating `__main__` blocks only under `leafi/` misses scripts that construct Leafi services directly. For example, [the duplex probe calls `app.build()` and the TTS service](/E:/GitHub/scil/Leafi/scripts/probes/p27_duplex.py:86) without running a Leafi module entry point. Those processes would lack both the guard and environment preparation.

    **Fix:** retain the explicit bootstrap boundary, extend coverage to supported scripts/launchers, and require initialized runtime state before constructing network/model services. Keep importing `leafi.core.lease` harmless for the habit track. Test bootstrap **order**, not merely the presence of a call.

31. **High — new — D2/D7/D16, “no pool” does not establish connection lifetime.**  
    `max_keepalive_connections=0` limits idle connections; it does not eliminate the pool or close an active response stream. [HTTPX resource limits](https://www.python-httpx.org/advanced/resource-limits/). Closing the underlying connection when `handle_request` returns would break streaming downloads; revoking the grant then while leaving the response open contradicts the retained-socket assertion.

    Separately, closing the transport’s own connection does not close another socket opened by a child task under its copied, still-active grant. The original retained-socket failure survives that path.

    **Fix:** define ownership through response-stream completion/closure, including cancellation and discarded retry responses. If connections must be exclusive, enforce that explicitly. Track and close every socket admitted under a grant, or explicitly narrow the claimed backstop guarantee. Test an independently retained socket, not only the normal client connection.

32. **High — new — D12/D19, policy versions are not bound to effective policy.**  
    Writing `.env` and the database version “in the same request” is not atomic. A crash between them can leave a changed policy with an unchanged version, or an advanced version paired with old settings. A restarted process can also load an older environment override and stamp it with the current database counter; [`envedit` already recognizes that overrides can defeat file values](/E:/GitHub/scil/Leafi/leafi/envedit.py:637).

    **Fix:** define a recoverable publication protocol or one authoritative policy store. Bind the version to the effective policy snapshot, including overrides, and fail closed on mismatches. Specify supported non-page writers. Test crashes on either side of publication and restart with stale overrides.

33. **High — remaining concurrency gap — D12, preparation and transmission authorization.**  
    The token lock protects the in-process token store; it does not serialize policy updates in another process. Nor does D12 specify how `prepare` reads content and versions consistently. A payload can be filtered using old terms and then stamped with newer versions, or pass revalidation before waiting for a connection while policy changes.

    **Fix:** read preparation inputs and their version vector from one consistent snapshot. Define a durable transmission-admission point ordered against policy writers, including every retry. State whether already-admitted transmissions may finish after a change; if stricter revocation is required, coordinate cancellation. Do not hold a `threading.Lock` across network awaits.

No files were edited. Verification included source inspection and an offline SDK transport probe; I did not run hardware or network-send tests.
