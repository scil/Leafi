# M5 egress design — codex (round 1)

Reviewer: codex `gpt-6-astra`, effort high, read-only sandbox, on `reviews/prompts/m5-design.md`, 2026-10-23 (159k tokens). Independent of the code-plan-review and fresh-Claude rounds. Verbatim below.

**I would not implement this design unchanged.** The two-seam architecture is sound, but several details undermine its guarantees or leave existing callers without a workable migration path. References below use the decision IDs in the [design](E:/GitHub/scil/Leafi/docs/plans/active/2026-10-23-m5-egress-design.md). This was a read-only review; small in-memory probes confirmed the context propagation and schema failures. No files were edited.

1. **High — D2: exiting `with grant(...)` does not revoke inherited grants.**  
   A task created inside the grant retains its copied context after the parent resets its `ContextVar`. For example, start a child task inside the grant, let the parent finish, then release the child: it still holds the grant and can connect until expiry. A cancelled `to_thread` operation can likewise continue running. D2’s statement that “nothing outside the `with` sees it” is false; the in-memory probe reproduced this. Context copying is documented by [Python](https://docs.python.org/3/library/asyncio-task.html).

   **Fix:** put a revocable grant identifier in the context and check shared active state as well as expiry. Revoke it in `finally`, including cancellation and failed transmission paths. Scope grants to the underlying transmission, not the whole SDK operation. Test delayed children, cancellation, nested grants and surviving worker threads.

2. **High — D2/D14/D15: a connect guard cannot establish the claimed “any byte” boundary.**  
   [netguard.py](E:/GitHub/scil/Leafi/leafi/core/netguard.py) intercepts connection creation and name resolution, not unconnected UDP sends or writes on existing sockets. A socket opened under a grant can send after that grant ends. A bare client using an ordinary loopback proxy also avoids the protected-address check; the installed edge-tts library explicitly creates an aiohttp session with `trust_env=True`. CLI-only installation additionally leaves direct service/probe entry points outside the guard.

   **Fix:** explicitly cover datagram sends, prohibit unmanaged proxies, inventory non-CLI entry points, and ensure pooled connections remain exclusively behind per-request mediation. Test an unprepared second request on an existing connection, not only a fresh connect. Native-library sockets and subprocess sockets remain outside this Python backstop: **the subprocess audit-only policy is accepted by ADR-0018**, but it must not be presented as prevention. Include ffmpeg/go2rtc children in that inventory, alongside Docker, netsh and PowerShell.

3. **High — D3: `lan` is an address-wide exemption derived from insufficiently constrained configuration.**  
   Configure `GATUS_URL` to a public address and D3 makes that address grant-free. Configure a LAN camera and Ollama using different hostnames resolving to the same address, and the hostname exclusion can miss the overlap. Allowing every port on the camera address then permits an unmediated connection to the model port.

   **Fix:** validate LAN classification, use explicit service/address/port tuples, and compare resolved addresses against protected model destinations—not just hostname strings. Protected gateway rules must override LAN exemptions, and `LEAFI_NO_NETWORK` must override both. Ordinary camera, Frigate and MQTT access is an authorised exception; arbitrary traffic to every port of their host is not. Enforce AnkiConnect’s loopback assumption separately.

4. **High — D6: canonical equivalence does not bind all bytes actually transmitted.**  
   Prepare `{"text":"safe"}`, then submit `{"text":"private learner words","text":"safe"}`. A conventional JSON parser keeps the last duplicate key, so the canonical HMAC matches while the raw body still transmits the private words. Headers are outside the binding entirely. `(host,H)` also omits scheme and port, although those distinguish recipients.

   **Fix:** reject duplicate keys and ambiguous encodings; either transmit the canonical serialization that was checked or bind an immutable final wire representation. Bind the complete recipient and constrain headers to approved credential/protocol fields. Preserve query/form multiplicity and define ordering semantics. Including paths and queries is **sound and necessary**, particularly for Bark, but their text must also undergo filtering—not merely hashing.

5. **High — D6/D7/D9/D17: token lookup and consumption do not yet enforce one submission plus one retry.**  
   Two learners preparing identical requests produce the same `(host,H)` lookup key. One token can overwrite or be mistaken for the other, affecting ownership, budgets and reverse mappings. Separately, decrementing `transmissions_left=2` leaves a second submission possible after a successful first transmission unless there is an additional claim state.

   The existing [Claude adapter](E:/GitHub/scil/Leafi/leafi/services/brain/claude.py:44) also owns a two-attempt loop and retries broad exceptions. Adding a mediator retry without removing that loop can produce four transmissions if each adapter attempt prepares anew.

   **Fix:** carry an opaque token ID through non-wire request metadata; atomically claim it on the first submission and remove it from external lookup. Only the claiming mediator may use its private retry allowance. Remove the adapter retry in M5, retain SDK `max_retries=0`, and test concurrent identical requests, successful-first-send replay, cancellation and budget refusal. Convert guard failures to 403 at HTTP boundaries; raw sockets and aiohttp cannot themselves return an `httpx.Response`. Do not feed synthetic policy refusals into edge-tts’s own 403 retry path.

6. **High — D16/D14: redirect handling can change the privacy purpose and misses WebSocket handshakes.**  
   D16 assigns a fresh **`ops` token to every redirect**, including a study request. A redirected study POST would either fail the fixed ops schema or lose learner ownership and pipeline checks. A host check alone also leaves scheme, port, credentials, method rewriting and body forwarding unspecified.

   Moreover, `follow_redirects=False` on httpx does not affect aiohttp. The installed aiohttp WebSocket handshake calls its ordinary request method with redirects enabled; a redirect to ordinary loopback can escape the socket guard without a new grant.

   **Fix:** deny study redirects unless explicitly required, or preserve their purpose, learner, prepared body and recipient authorisation through a defined hop policy. Handle WebSocket handshake redirects explicitly. Specify allowed origins, credential stripping, method/body rules, maximum hops and an overall deadline; do not reset an unlimited chain to 120 seconds per hop. Per-hop grants are otherwise sound.

7. **High — D15: RapidOCR’s connection-level exception contradicts the ADR.**  
   The installed RapidOCR downloader uses `requests.get(..., stream=True)` with normal Requests redirects. Under the proposed broad grant, it performs requests without `prepare`, fixed ops-schema validation, attempt-token consumption or mediated redirect checks. The httpx2 alias does not affect Requests.

   ADR-0018 expressly authorises this weaker treatment for **edge-tts library mode**, not model downloads.

   **Fix:** provision RapidOCR’s fixed model files through the mediated downloader and configure local paths, or adapt its downloader at the request boundary. If the broad grant is retained, it needs an explicit owner-approved ADR exception; it is not an implementation detail already authorised by §7.3.

8. **Medium — D15/D16: Hugging Face factory injection is necessary but insufficient.**  
   `snapshot_download` makes its own metadata and file requests, uses worker threads and implements retries. Merely returning `egress.client(...)` leaves those requests without prepared tokens. Automatically granting every request would instead bypass the fixed download schema.

   There are two further integration traps in the installed code: Hugging Face expects some HEAD redirects to remain visible so it can read repository metadata, and its default client’s request hook enforces offline mode. Replacing that factory without equivalent enforcement removes that hook.

   **Fix:** define a synchronous and asynchronous download adapter that validates fixed repositories, revisions, paths, methods and headers before preparing each request. Create grants in the actual worker executing the transmission. Preserve HEAD metadata semantics, control library retries, and enforce a `doctor --download` capability independently of environment flags. The factory APIs are supported, as documented by [Hugging Face](https://huggingface.co/docs/huggingface_hub/main/package_reference/utilities); the missing part is the request policy around them.

9. **High — D13: defaulting arbitrary spoken text to `system` loses existing learner provenance.**  
   Two current paths demonstrate the failure:
   - [Identification](E:/GitHub/scil/Leafi/leafi/study/harness/identify.py:124) says “Shall I remember you as …?” before the new name is enrolled. The default `system` label bypasses D11’s learner-text detector, and the name is absent from the lists.
   - [Anki review](E:/GitHub/scil/Leafi/leafi/study/harness/activities.py:448) interpolates `card.front` into `review_prompt_eases`. A card containing learner-derived text becomes `system` and can reach edge-tts even with `cloud.text=off`.

   **Fix:** make provenance mandatory for dynamic text. Permit a system default only through a static-phrase API. Propagate provenance through `Inputs.line`, `ListeningGate`, `Hub`, the synthesizer protocol and TTS backends. Identification must remain local until adoption. Restore stored provenance for Anki cards; conservatively handle external cards with unknown provenance. Apply the same rule to Brain rationales and locally restored replies. The AnkiWeb notice does **not** authorise retransmitting card text to Microsoft.

10. **High — D14: preparing after chunking can expose protected multiword terms.**  
    In mediated mode, a page line containing `Quillfield Academy` can be split into chunks ending in `Quillfield` and starting with `Academy`. Neither chunk matches the household term; page text does not run through D11. Both pieces then leave in valid, individually authorised frames.

    **Fix:** filter and pseudonymise the complete logical line before chunking. Bind tokens to chunks of that already-prepared result, preserving its provenance and transformation mapping. Test protected terms straddling byte limits, XML escaping and Unicode boundaries. Library mode already has the correct ordering—prepare the line, then let the library chunk it—and its lack of frame inspection is an **explicitly accepted exception**.

11. **Medium — D10/D11: the surrogate mapping is neither reliably stable nor invertible.**  
    Hashing terms modulo 200 permits two people to receive the same surrogate. Hashing a person’s name and alias separately gives them different identities. Skipping words occurring in the payload makes the surrogate change between requests. Two schools both become “the school”; multiple detected people become `[name]`. Those mappings cannot be reversed uniquely. A generated occurrence of an ordinary surrogate name can also be mistaken for a reference to the learner.

    **Fix:** allocate collision-checked, stable per-entity surrogates, associate aliases with the same entity, and define exhaustion and later household-name conflicts. Reverse only unambiguous references; never globally restore generic placeholders. Preserve provenance after restoration. Ensure the detector does not replace newly generated surrogate names again. Realistic surrogates are authorised by the ADR; **this particular allocation/reversal mechanism needs correction**, rather than separate owner approval merely for choosing a name list.

12. **High — D10/D11/D17: name, school and exact-age coverage is incomplete.**  
    Whole-word matching correctly avoids replacing `Ann` inside `annual`, but a naïve Unicode word-boundary rule misses a protected Chinese name inside an unspaced Chinese sentence. Possessive handling needs straight and curly apostrophes, plural possessives and normalization.

    More concretely, the existing enrolment writer does not populate `alias_age_band` or collect school/no-school confirmation. D10 assumes those facts already exist. Changing the system prompt also does nothing to `I am 10 years old` in permitted learner text: none of D11’s three entity classes handles age. Forgotten aliases are another gap: the current forgetting writer preserves `display_name`, not every identifying alias.

    **Fix:** specify multilingual span matching and possessive tests; add enrolment/backfill and forgotten-alias handling to M5. Define how learner exact ages are transformed wherever they enter payloads. If “exact age never leaves” is intended to cover only structured profile fields, that is a narrowing of the accepted table and needs the owner.

13. **High — D11: a missing model silently turns an enabled privacy setting off.**  
    On a fresh installation, `privacy.name_detector=on` but the model is absent. D11 then permits an unlisted friend or school to leave unchanged, with only a `doctor` diagnostic. That changes the effective default without the typed confirmation required by §5.

    The offline construction also needs more precision: the pinned Presidio implementation can call `spacy.cli.download` for a missing model, and an empty recognizer registry triggers loading predefined recognizers. See its [NLP engine](https://raw.githubusercontent.com/microsoft/presidio/2.2.364/presidio-analyzer/presidio_analyzer/nlp_engine/spacy_nlp_engine.py) and [analyzer constructor](https://raw.githubusercontent.com/microsoft/presidio/2.2.364/presidio-analyzer/presidio_analyzer/analyzer_engine.py).

    **Fix:** when enabled but unavailable, keep affected text local or refuse its cloud transmission. A fail-open alternative needs the owner. Supply a populated restricted registry and an explicitly offline model loader; test absent/corrupt models and empty caches with attempted networking recorded. Avoiding the default URL/email recognizers is sound; [tldextract](https://github.com/john-kurkowski/tldextract) also supports explicitly disabling suffix-list fetching.

14. **High — D12: the claimed existing typed confirmation does not exist.**  
    The [settings page](E:/GitHub/scil/Leafi/agent/webui/index.html:532) renders a **checkbox**, then computes the hash of the pending value in JavaScript. [envedit](E:/GitHub/scil/Leafi/leafi/envedit.py:587) verifies that value-bound hash. This prevents accidentally confirming a different value, but it does not require typing anything. Extending `PRIVACY_FLOOR` therefore does not implement ADR-0018’s stated interaction.

    **Fix:** implement the typed interaction explicitly, or obtain an owner decision that the existing checkbox mechanism satisfies the intended requirement. Bind CLI confirmation to the exact learner ID, operation and value; update the setting, version and `cloud_text` consent atomically. **CLI-first editing is a reasonable proposal, but it is the explicit scope deferral already listed for owner decision—not compliance with the promised settings-page support.**

15. **High — D12/M5c: the `REDACT_TERMS` migration fails against the existing schema and can remove protection prematurely.**  
    `household_terms.kind` accepts only `name`, `school` and `other`. D12’s `kind='term'` raises a CHECK violation; the in-memory probe confirmed it. Meanwhile, removing the manifest entry before updating `Settings.redact_list`, edge TTS, doctor, checks, `setup --redact`, `PRIVACY_FLOOR` and editor-agreement tests breaks those consumers. A stale `.env` entry becomes an unknown removable key even if its import failed.

    **Fix:** use an existing valid kind or provide an explicit schema migration. Import idempotently and transactionally, recording completion only after success. Retain old protection until every consumer uses the new store; handle environment overrides deliberately. Update the setup command, alert catalogue, manifest, protection floor and tests together.

16. **High — D7/D12: the design does not connect settings changes to already-prepared transmissions.**  
    Prepare learner-derived text while every source allows cloud text; another process switches one source off; the queued request or retry still holds a live token. D7 stores neither the source set nor relevant settings versions. Household settings are process-loaded `.env` values, while the ADR requires current source settings at send time and household version tracking.

    **Fix:** define the authorisation point immediately before each transmission. Revalidate source existence, source permissions and relevant household versions, including retries and pooled requests; refuse or reprepare stale tokens. An unknown/deleted source must not become an empty source set that passes vacuously. Keep shared privacy-setting access below `study` so D1’s import direction remains valid.

17. **Medium — D5/D8: `notify` needs a schema change and explicit learner context through the callers.**  
    The current `egress_log.purpose` CHECK rejects `notify`, also confirmed by the probe. D8 explicitly says to use migration 5’s existing columns/schema. Additionally, `Notifier.notify(title, body)` and `Catalog.title_for_isbn(isbn)` carry no learner/session context, although their study attempts require a learner. Guest finalisation can delete the guest before the notification runs, leaving a stale ID.

    **Fix:** if the owner accepts `notify`, supply a migration for existing databases and thread explicit attempt context through Hub/notifier and catalog calls. Define post-finalisation ownership. Keep the counts-only notification enforced by construction/schema, not a general string API merely labelled `system`. The `notify` name is a reasonable addition; the current counts-only notification already exists, so this need not introduce a new parent feature.

18. **Medium — D4/D13/D17: backend routing and operational purposes need explicit contracts.**  
    The supervisor’s `/api/tags` probe now hits a protected Ollama port, but D4 does not explicitly authorise its fixed `ops` request. It can consequently report a healthy service as failed. The Ollama adapter still uses `/api/chat`, whereas ADR-0018 specifies its OpenAI-compatible endpoint. D13’s “everything else” going to edge-tts also reads as overriding the existing per-language Kokoro/edge selection.

    **Fix:** add fixed schemas for model-health probes and preserve existing TTS backend selection before applying privacy routing. Validate the actual transmitted model/provider against locality rules; do not trust the endpoint or a registry-wide locality flag alone. Keep Ollama’s measurement gate and explicit rejection of cloud-hosted model names. Resolve the endpoint discrepancy explicitly. Keeping the restricted v1 Brain request until M7 is otherwise a sound staged narrowing.

19. **Medium — D8/D13: key creation, attempt completion and TTS retention have missing failure semantics.**  
    `O_EXCL` prevents two creators, but another process can observe the newly created key before its 32 bytes are fully written; a crash can leave a partial file. Cancellation or a crash after transmission can leave an attempt permanently `sending` or with an understated count. D13 also omits the TTS source sidecars required by §3; current cache hits return immediately without recording additional source learners.

    **Fix:** serialize key initialization, validate its exact length and fail closed on corruption. Define durable transmission accounting, cancellation handling and startup recovery to `unknown`. Add source-union sidecars on cache hits and misses, plus deletion coverage for forgetting. Per-install keyed HMACs, body-free egress logs and the proposed ops retention schedule are sound choices.

20. **High — M5a–M5f: the proposed commit sequence cannot deliver its stated green, continuously enforced rollout.**  
    M5a enables denial before callers obtain grants in M5d. M5a also promises positive mediated-client controls before those clients exist. M5c removes old redaction before consumer migration. M5d enables cloud adapters before M5e supplies end-to-end provenance and settings. M5f postpones canary tests and boundary documents until after the enforcement changes they are supposed to accompany.

    **Fix:** land inactive primitives and schema support first while preserving current enforcement. Complete pseudonymisation, settings and provenance plumbing before enabling new egress paths. Switch callers and always-on enforcement atomically, or migrate independently complete paths with their tests and documentation in the same commit. Keep all media refused until M9 implements consent checking—not merely requests lacking a consent ID.

    The acceptance tests must run **beneath** the mediator: today’s privacy recorder patches `Client.send`, bypassing transport enforcement. Add real-client positive and negative controls, duplicate-key payloads, concurrent identical tokens, retained sockets, WebSocket redirects and the actual Hugging Face/RapidOCR paths. Expand architecture checks to client construction and approved exceptions; the existing internet-named test only restricts `anthropic` imports. D1’s package placement and D4’s declarative registry are sound, but neither substitutes for these behavioural checks.
