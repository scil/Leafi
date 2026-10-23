# M5 egress design rev 2 — codex increment review

Reviewer: codex `gpt-6-astra`, reasoning high, read-only, on `reviews/prompts/m5-design-rev2.md`, 2026-10-23. Verbatim final answer.

**Revision 2 improves the design substantially, but I would not implement it unchanged.** The remaining blockers are token replay, retained sockets, incomplete settings revalidation, guest ownership, and rollout ordering. This was a read-only review; no files were edited.

Items 1–22 assess each round-1 theme. For closed themes, severity retains the original theme’s significance.

1. **High — T1: partly — D5, attempt ownership.**  
   Adding `notify` and supplying learner/session IDs fixes the immediate CHECK failures. Guest lifecycle remains unresolved: [adopt()](/E:/GitHub/scil/Leafi/leafi/study/harness/identify.py:53) deletes the original guest without transferring its `egress_log` rows, so a pre-identification attempt can cause a foreign-key failure. Conversely, finalisation can delete a guest before closing TTS and notification delivery.

   **Fix:** define transactional attempt ownership during adoption and guest disposal, invalidate outstanding guest tokens, and resolve post-finalisation ownership before preparing delivery. Keep accounting ownership separate from the original provenance sources.

2. **High — T2: partly — D18, M5a–M5e.**  
   Moving callers and enforcement together is sound, but essential dependencies still arrive afterward. M5b promises revalidation and stale-settings tests; `privacy/settings.py` arrives in M5d. M5c switches callers to lists that exclude `REDACT_TERMS`; importing those terms is postponed to M5d. Merely retaining `redact()` does not protect a caller that has stopped using it.

   **Fix:** land settings/version storage and readers before M5b; import legacy terms before switching callers, or require temporary dual-reading. Install confirmed writers and privacy floors by M5c. Keep old enforcement effective until its replacement has both the code **and the data**.

3. **High — T3: partly — D10, script-aware matching.**  
   CJK substring matching, possessives and hyphen handling address the stated examples. “Latin terms by word boundary” still permits the original failure for mixed scripts: ordinary Unicode `\bAnn\b` does not match `我叫Ann今天读书`. I confirmed this with the repository’s Python 3.12. Normalisation is also unspecified.

   **Fix:** define boundaries at script transitions and a consistent Unicode normalisation policy for terms and input. Add mixed-script Latin-name and composed/decomposed-name cases alongside the Chinese-name canary.

4. **High — T4: partly — D10/D11, stored surrogates.**  
   Per-entity allocation and restricted reverse mapping are sound improvements. However, a stored surrogate can later become a real household name: allocate “Nola” to learner A, then enrol someone named Nola. Returning A’s existing mapping now emits a protected name. Concurrent allocation, pool exhaustion and identity continuity after forgetting are also undefined. Running the detector after substitution may replace the newly inserted surrogate with `[name]`.

   **Fix:** allocate transactionally with uniqueness constraints; recheck mappings against current protected terms; define exhaustion and forgotten-entity handling. Preserve replacement spans through detection. Explicitly reconcile per-request alternate names with the parent’s ability to recognise notification surrogates.

5. **High — T5: partly — D6/D7, token handoff and claim.**  
   Opaque IDs fix identical-body collisions, and removing adapter retries fixes the four-transmission path. Two defects remain:

   - Clearing a `ContextVar` in a child task does not clear the parent’s copy; ordinary executor workers do not inherit it. Local probes confirmed both. The current Claude same-task path can work, but this is not a general request-handoff contract.
   - `claimed_by=request` rejects a *different* request, but permits re-entry with the same request object and retained extension. After one successful transmission, its unused retry allowance must not authorise another submission.

   **Fix:** attach the ID to the specific constructed request, with adapter-side `finally` cleanup wherever ambient context is needed. Atomically remove the token from public lookup on first entry; give only that transport invocation a private retry capability. Burn it on every exit.

6. **High — T6: partly — D6, canonical request binding.**  
   Rejecting duplicate keys and binding scheme, port and constrained headers closes important holes. The canonical-body requirement is sound. But hashing Bark’s encoded path does not establish that its notification text was pseudonymised: the current notifier applies `quote()` before transmission.

   **Fix:** specify field-aware filtering before URL encoding, including Bark’s title/body path components and textual query/form fields. Test the final transmitted URL as well as bodies. Require the transport to send the checked canonical representation, not merely accept a canonically equivalent representation.

7. **High — T7: closed for the original grant-lifetime/thread-placement issue — D2.**  
   A shared active set makes copied grant IDs revocable, and opening grants inside synchronous/asynchronous transports addresses the worker’s connection context. Both changes are sound. They do **not** solve retained sockets or supply workers with attempt tokens; those remain in items 8 and 13.

8. **High — T8: partly — D2, existing connections and import scope.**  
   UDP coverage, proxy controls and broader installation help. However, a task can connect while its copied grant is active, retain the socket, and call `send`/`sendall` after revocation. None of the listed checks intercepts that write. Passing `sock=` through a checked API does not cover direct reuse. Legitimate pooled HTTP requests remain safe only while every request stays behind mediation.

   Installation from `leafi/__init__.py` also affects the habit track: [agent/speaker.py](/E:/GitHub/scil/Leafi/agent/speaker.py:18) imports Leafi’s lease before synthesising speech. Its existing cloud callers have no M5 grants.

   **Fix:** specify connection ownership and enforcement for writes/reuse, with a retained-socket negative test and a mediated-pool positive test. Define process bootstrap boundaries explicitly; do not silently install Leafi-only policy into habit processes.

9. **High — T9: closed — D2/D3, LAN exemptions.**  
   Resolved address/port tuples, private-address validation, gateway precedence and no-network precedence address the theme. The restart requirement after address changes is explicit. Preserve tests where different configured hostnames resolve to the same gateway/device address.

10. **High — T10: closed at design level — D13, TTS provenance.**  
    Required provenance, static-only phrase access, conservative external-card handling, pre-adoption learner classification and sidecars on cache hits/misses address the identified failures. This is sound. Implementation must carry the complete provenance—including source IDs—through `ListeningGate`, `Hub` and `Synthesizer`.

11. **Medium — T11: closed — D13, surrogate speech under local routing.**  
    Checking list terms regardless of text class, then applying privacy routing after language/backend selection, addresses the issue. With `privacy.tts_learner_lines=cloud`, surrogate speech remains explicitly allowed by ADR-0018; the “never speaks a surrogate” statement must remain scoped to `local`.

12. **High — T12: closed — D14, chunk boundaries.**  
    Preparing the complete line before chunking closes the split-term leak. Per-chunk tokens and fixed-frame checking are sound. Preserve the original line’s sources and transformation mapping when deriving chunk tokens.

13. **High — T13: partly — D14–D16, redirects and Hugging Face.**  
    Refusing study redirects and disabling mediated WebSocket redirects are sound. Hugging Face remains underspecified: a factory returning a mediated client does not prepare its internally generated requests. Opening grants in worker transports does not provide missing tokens. Passing redirects back and checking the next host also loses the chain’s hop count, deadline and credential policy unless that state is explicitly carried.

    The installed library makes metadata `HEAD` requests and follows relative redirects itself; this conflicts with a universal mediator-owned, GET-only description.

    **Fix:** define an HF-specific request adapter with fixed download schemas, per-request preparation, explicit HEAD semantics and shared redirect-chain state. Strip credentials on origin changes. Give it an explicit download capability rather than relying solely on environment flags.

14. **High — T14: partly — D11, missing detector model.**  
    Explicit local model loading and a populated restricted registry address the accidental-download mechanism. **List-only fallback is now an owner decision, not an unresolved permission question.** Nevertheless, ADR-0018 §3 and Confirmation still promise replacement of an unlisted school/friend when the detector is on. Fresh installations without the model cannot satisfy that test.

    **Fix:** amend the governing contract and acceptance tests to distinguish detector-available and list-only operation. Display effective availability separately from the configured “on” value. Do not report the fallback as satisfying the existing detector guarantee.

15. **High — T15: closed — D15, RapidOCR.**  
    Provisioning models through Leafi’s mediated downloader and configuring local paths removes the unjustified broad grant. The test forbidding its Requests downloader is appropriate.

16. **High — T16: closed on the owner-approved direction — D12, confirmation.**  
    The checkbox plus value hash is explicitly accepted, and revision 2 acknowledges that it changes the ADR. An atomic setting/version/consent write is sound. Update ADR §6’s remaining “typed confirmation” wording too. CLI confirmation should identify the resolved learner, operation and exact value before that transaction.

17. **High — T17: partly — D12, revalidation.**  
    Revalidating every transmission is the correct direction, but the token records only source learners’ `privacy_version`s and the terms version. It omits `household_settings_version`, so changes to parent-text permission, detector mode, TTS policy or locality can leave a token authorised under old policy. Restarting services after saving is not an atomic revocation mechanism and does not necessarily reach manually launched processes.

    The design also does not explicitly reject `forgetting=true`, or invalidate all affected payloads when another learner’s name/alias is added.

    **Fix:** version the complete relevant policy and protected-name set; check current source existence, kind, forgetting state and permissions. Define the authorisation point relative to concurrent policy writes, including retries and queued pooled sends.

18. **Medium — T18: partly — D8, key and attempt recovery.**  
    Temporary-file publication via exclusive link, exact-length checking and backup inclusion are sound. Startup recovery now introduces a multiprocess ambiguity: how does one process distinguish another live process’s `sending` row from a crashed process’s row? Existing schema has no attempt-owner identity.

    **Fix:** define ownership/liveness or perform recovery under exclusion that proves no sender is active. Preserve durable transmission counts on cancellation and uncertainty.

19. **High — T19: partly — D10, schools and ages.**  
    Computing the band from `birth_year` and preserving aliases on forget address two gaps. School/no-school enrolment and existing-learner backfill remain absent; [learner_store.create()](/E:/GitHub/scil/Leafi/leafi/core/learner_store.py:81) does not collect them. A school appearing in page text bypasses the learner-text detector.

    The structured-age-only decision also contradicts ADR §2’s “exact ages … never” and its cloud-body canary requirement.

    **Fix:** add the enrolment/backfill work before enforcement changes, and amend the age guarantee and tests to the owner’s explicitly narrower policy.

20. **Medium — T20: closed — D4/D13/D17, probes and backend routing.**  
    Named probe destinations, fixed ops schemas, the OpenAI-compatible Ollama endpoint and preservation of language-specific TTS selection address the theme. Keeping restricted v1 Brain requests until M7 is a sound staged choice. Preserve the existing Ollama measurement gate.

21. **Medium — T21: partly — D9, refusal handling.**  
    Handling `NetworkDenied` at the TTS boundary fixes the original Faces fallback. HTTP guard failures remain outside D9’s stated pipeline/token-to-403 conversion. They can become generic connection failures and enter D7’s connect-error retry path.

    **Fix:** translate guard policy denials at the mediated HTTP boundary before generic retry classification. Keep the explicit exception-to-Faces path for aiohttp/raw-socket callers.

22. **Medium — T22: partly — D2/D15/M5d, bootstrap details.**  
    Console work, `ThreadedResolver` and an environment-read exemption are now named. The HF child bootstrap is still ambiguous: removing `HF_HUB_OFFLINE` from its launch environment is insufficient if importing Leafi immediately sets it again. Replacing HF’s default client factory also removes its default offline request hook unless deliberately preserved.

    **Fix:** specify the child’s bootstrap order and download capability, retain equivalent offline enforcement in custom clients, and test a real worker-driven download path. Scope architecture-test exemptions to every actual environment-owning module.

The following are additional revision-2 defects or contract conflicts that merit separate tracking:

23. **High — D5/D10/D12, migration 6 does not cover the new state.**  
    [The existing schema](/E:/GitHub/scil/Leafi/leafi/core/storage.py:157) has `settings_version`, but no specified `privacy_version`, household terms version or household settings version. Migration 6 lists only `notify` and `pseudonyms`. Their storage and atomic update rules cannot be left implicit.

    Also, the current migration function always inserts a first learner; it must not simply be reused unchanged for a v5→v6 upgrade.

    **Fix:** enumerate the complete schema/JSON state and writers. Provide a genuine v5→v6 path that preserves learner ownership, plus rollback and fresh-schema-equivalence tests.

24. **Medium — D10/D13, stored surrogate mappings need an explicit deletion contract.**  
    `pseudonyms(entity, surrogate)` introduces durable identity-linked data without defining its relationship to `forget`. A learner foreign key can block deletion; cascading deletion can break stable substitution in retained corrections; retaining arbitrary entity data can exceed the intended exception for protected names.

    **Fix:** define exactly what survives forgetting, keyed through the retained household-term identity, and test both deletion and continued pseudonymisation of shared page text.

25. **Medium — D5, surrogate notifications are authorised, but their governing description is incomplete.**  
    A surrogate is not the learner’s real name, so the owner’s choice does **not inherently violate AGENTS.md’s name prohibition**. However, ADR §6 says study parent notifications are deferred, while the code already sends counts-only notifications. D5 changes that existing feature without reconciling the contradiction. Classifying the entire message as `derived_from_learner` also means guest/`cloud.text=off` notifications may disappear.

    **Fix:** document the existing notification exception, its exact schema and permission behaviour. Enforce surrogate-plus-counts by construction rather than accepting arbitrary strings under a `notify` label.

26. **High — D10/D11/D18, owner choices do not automatically amend the active boundary.**  
    Structured-age-only handling permits “I am 10” to leave in learner free text; that conflicts with the currently supplied AGENTS.md prohibition on sending the learner’s own words. List-only fallback can also allow unlisted identifying text that the ADR currently says will be replaced.

    Revision 2 explicitly schedules the AGENTS.md replacement, so the broad transition is acknowledged. It does **not** similarly schedule the specific ADR amendments for fallback and age coverage; only checkbox wording is named.

    **Fix:** record those already-authorised policy changes in ADR §§2–3 and Confirmation, and align `security.md` and tests in the enforcement commit. No new owner approval is needed merely to document decisions already made.

27. **High — M5/M9 boundary, media refusal is too narrow.**  
    “No consent → refused” leaves unspecified what happens when a request supplies a consent ID before M9 implements matching, masking and atomic consumption. A consent-shaped value must not activate an incomplete media path.

    **Fix:** make M5 reject **all** `media` transmissions unconditionally. M9 replaces that gate only when the complete consent pipeline and tests land.

28. **High — D18, the proposed commits cannot yet be certified independently green.**  
    **M5a** is viable only if “inactive” preserves current enforcement and migration compatibility; its full mediated-client positive controls depend on later work. **M5b** needs the missing settings/version primitives. **M5c** is blocked by the issues above and cannot precede legacy-term import or confirmed settings enforcement. **M5d** can then be UI/CLI completion and cleanup, rather than supplying prerequisites retrospectively. **M5e** can hold non-normative documentation, but ADR §7.5 and the parent plan require operative privacy-contract changes with enforcement.

    **Fix:** reorder those dependencies explicitly. Retain D1’s layering, the two enforcement seams, destination registry, canonical binding, prepare-before-chunking and below-mediator canaries: those are sound foundations.
