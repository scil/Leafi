# Codex design review, round 1 (gpt-6-astra, reasoning high, read-only sandbox)

Run 2026-10-19 against commit 8204ac1 with the prompt in the plan's Decision log. Resolutions: ADR-0009, ADR-0010, ADR-0011 and the revised architecture docs in the same day's commit.

The design needs several decisions before S1 begins. The most consequential are how to distinguish recognition uncertainty from learner miscues, how corrections preserve page identity and history, and how to reconcile the privacy rules with actual network behavior.

This review used the requested documents, existing habit code, installed SDK signatures, and upstream documentation. No files were changed, models downloaded, or hardware/audio tests run.

## A. What will be hard to get right—and keep going wrong

1. **High — Recognition disagreement is being treated as pronunciation evidence.**  
   **Location:** ADR-0007, “Decision outcome”; `data-model.md`, “Enums”; plan S3 acceptance.  
   A different ASR word can reflect recognition error, substitution, or mispronunciation, but the design assigns it `mispronounced` before acoustic verification. Conversely, expected-word biasing and fuzzy matching can conceal an actual misreading, so both false corrections and missed difficulties will recur.  
   **Suggested change:** Separate alignment observations from pronunciation judgements; classify transcript disagreement as a candidate miscue, preserve uncertainty, and reserve pronunciation feedback for independently supported acoustic evidence.

2. **High — Incremental alignment lacks a commitment rule.**  
   **Location:** [ADR-0007](/E:/GitHub/scil/Leafi/docs/adr/0007-reading-verification-by-alignment.md), “Decision outcome”; `reading-session.md`, “Sequence for one sentence”.  
   Aligning each utterance against the remaining page can label unread suffixes as skipped, while repeated words and sentence restarts can move the cursor incorrectly. VAD boundaries are not sentence boundaries, so ordinary hesitation will repeatedly expose this ambiguity.  
   **Suggested change:** Specify bounded, semi-global alignment with provisional results, an explicit committed cursor, a small rereading window, and a rule that never marks an unattempted suffix skipped.

3. **High — Page fingerprints cannot reliably protect corrections.**  
   **Location:** [Data model](/E:/GitHub/scil/Leafi/docs/architecture/data-model.md), `pages`; plan S2.  
   Hashing the first 12 OCR words makes identity change when recognition changes and collide when pages share an opening. A mistaken match can apply another page’s corrected text, while a missed match creates a duplicate that bypasses corrections.  
   **Suggested change:** Give each physical page a stable internal ID; use book edition, printed number, and multiple text/layout observations to propose matches, requiring confirmation when ambiguous.

4. **High — Corrections cannot be located or audited reliably.**  
   **Location:** `data-model.md`, `corrections`, `miscues`, and “Invariants”; [reading flow](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md), “Handling a correction”.  
   Correction offsets have no defined units or source revision, and miscues have no utterance reference or expected-token position. Repeated words and length-changing corrections therefore make it impossible to identify which historical observation should be invalidated.  
   **Suggested change:** Add immutable page-text revisions, revision-relative character spans, utterance/token references, and transactional correction application; invalidate superseded assessments with a reason instead of deleting their provenance.

5. **High — Playback completion and listening ownership are undefined.**  
   **Location:** [Device-routing flow](/E:/GitHub/scil/Leafi/docs/architecture/flows/device-routing.md); plan S0 ports; `agent/speaker.py::say`.  
   The current speaker implementation waits for an HTTP request, but that alone does not establish when sound stops at the camera. Without playback cancellation, capture-buffer flushing, and a single owner of the listening gate, Leafi can transcribe its own coaching or lose the learner’s first words.  
   **Suggested change:** Define playback completion semantics and cancellation, serialize speech per session, and resume capture only after playback and an adapter-specific drain interval.

6. **High — The latency budgets do not compose.**  
   **Location:** [Performance budgets](/E:/GitHub/scil/Leafi/docs/architecture/quality-attributes/performance.md); `tools/go2rtc/PATCHES.md`, “配套的喇叭链路参数”; reading-flow sequence.  
   The listed ASR and uncached TTS allowances already total 1.6 seconds, before VAD endpointing, Brain inference, transport, and the camera’s documented 0.9-second leading silence. The sequential Brain fallback and 20–30-second timeouts also permit long stalls despite the 1.5-second spoken-feedback target.  
   **Suggested change:** Define separate budgets for visible acknowledgement, useful local feedback, and generated explanation; measure end-to-audible-speech p50/p95 per output device and keep Brain calls off the immediate correction path.

7. **Medium — Habit migration is more than replacing three adapters.**  
   **Location:** Plan S5; `agent/session.py::_verify_pose_dwell`, `_verify_vlm_burst`; `agent/presence.py`; `agent/storage.py`.  
   Sessions depend on global settings, raw Frigate events, direct snapshot acquisition, and verifier imports, while the proposed Presence protocol has no methods. The legacy database also lacks stable record IDs, so “one config; one SQLite” requires a separate migration policy rather than a mechanical move.  
   **Suggested change:** Define normalized presence events, subscription lifecycle, and verifier inputs before S5; migrate device access first and leave database consolidation to an independently verified migration.

## B. Important decisions an implementer would otherwise invent

1. **High — Construction and dependency injection have no owner.**  
   **Location:** [Architecture overview](/E:/GitHub/scil/Leafi/docs/architecture/overview.md), “Boundaries and rules”; plan S0 `Hub.from_yaml`, `Hub.listener`.  
   Core cannot import devices or services, yet the Hub is responsible for loading adapters, invoking TTS, and composing an Ear with ASR. Without a construction boundary, an implementer must either violate the dependency rule or invent an implicit global registry.  
   **Suggested change:** Make `cli.py` the composition root; inject adapter factories, a synthesizer, and constructed Listeners into core through core-owned protocols.

2. **High — Audio ownership is missing from the interfaces.**  
   **Location:** Plan S0 port sketch, S3; ADR-0007, “Consequences”; `data-model.md`, `utterances`.  
   Pronunciation scoring needs audio, but the described Utterance contains only text, words, and timestamps, with persistence normally disabled. AudioChunk and AudioClip also lack clock, format, lifetime, and cancellation semantics.  
   **Suggested change:** Define a bounded in-memory audio reference carried by voice Utterances, sample-relative timing, explicit format metadata, and release after assessment; typed Utterances carry no acoustic evidence and cannot receive a pronunciation score.

3. **High — Input selection and runtime fallback are unspecified.**  
   **Location:** [Configuration](/E:/GitHub/scil/Leafi/docs/architecture/config.md), device schema; plan S0 `Hub.listener`; device-routing rules.  
   Multiple Eyes, Ears, and console input can exist, but there is no selection policy or behavior for a selected device disappearing. An adapter’s `aec: true` also cannot establish cancellation of sound from another Mouth selected by `voice_policy: all`.  
   **Suggested change:** Configure one study Eye and one reading Listener explicitly, retain console controls independently, and keep all v1 reading half-duplex regardless of adapter AEC claims.

4. **High — The state machine omits ordinary control and failure transitions.**  
   **Location:** [Reading flow](/E:/GitHub/scil/Leafi/docs/architecture/flows/reading-session.md), state diagram; plan S1 intents; reliability table.  
   Stop, page turn, correction, and timeout are not defined across all states, and phrases printed in the book can be mistaken for control commands. Keeping the last page after camera failure is unsafe when the learner may already have turned it, because subsequent reading can be scored against stale text.  
   **Suggested change:** Add global stop/cancel transitions, explicit command mode or a control prefix, page-confirmation states, and a rule that uncertain page identity suspends assessment.

5. **High — Anki synchronization and grading have no transaction model.**  
   **Location:** [ADR-0004](/E:/GitHub/scil/Leafi/docs/adr/0004-sqlite-system-of-record-anki-as-scheduler.md); `data-model.md`, Anki invariant; reading-flow “Wrap”.  
   If Anki creates a note but the response is lost, retrying a null `anki_note_id` can duplicate it, while already-linked updates have no dirty-state mechanism. The design also omits rating selection, multiple cards per note, parent edits, deleted notes, and repeated `answerCards` after uncertain responses.  
   **Suggested change:** Introduce a stable Leafi item key and local synchronization outbox, define field ownership and reconciliation, track card IDs separately, and require learner-selected review ratings in v1.

6. **Medium — Knowledge identity and learning status are too coarse.**  
   **Location:** `data-model.md`, `knowledge_items`, `difficulties`, and “Enums”.  
   Uniqueness on `(kind, key)` can merge different meanings of a word or unrelated facts, while one context field loses their separate evidence. Difficulty weights, retry effects, and transitions back from `known` after a lapse are unspecified, so the stored learning history can drift from actual performance.  
   **Suggested change:** Use language-and-sense-aware item keys with separate encounter records; define a simple versioned weighting rule and reversible status mapping from Anki outcomes.

7. **Medium — “Degrades” lacks task-specific semantics.**  
   **Location:** [Reliability](/E:/GitHub/scil/Leafi/docs/architecture/quality-attributes/reliability.md); reading-flow explanation and comprehension sections.  
   Static phrases can keep conversation moving but cannot supply an unknown definition or evaluate comprehension honestly. The design does not distinguish unavailable assessment from an incorrect answer, nor specify handling of late results after a page or session changes.  
   **Suggested change:** Define typed outcomes such as unavailable, uncertain, and completed; skip unsupported assessment without recording a learner difficulty, and reject asynchronous results whose session/page revision is stale.

## C. What is over-built for v1

1. **Medium — Device breadth and habit consolidation are separate releases.**  
   **Location:** Plan S4–S5; product H5/T2; ADR-0008.  
   ESP32, Wyoming, Tapo, and habit database consolidation do not establish whether the physical-book tutoring loop works. Including them in the same delivery sequence adds protocol and migration obligations before the core learning interaction is validated.  
   **Suggested change:** Define v1 as console plus PC mic/speaker plus Xiaomi Eye/Mouth, preserving the capability interfaces and zero-Mouth behavior; move S4/S5 to separate plans.

2. **High — Automated phoneme judgement is premature.**  
   **Location:** ADR-0003 pronunciation choice; plan S3; research §2.2 and §4.  
   The plan makes pronunciation assessment a default dependency before its child-speech false-positive rate is measured. A functioning scorer could therefore satisfy implementation acceptance while delivering discouraging or incorrect feedback.  
   **Suggested change:** Ship model-and-repeat practice with an “I may have misheard” outcome first; gate automatic pronunciation judgements on a separately approved evaluation threshold.

3. **Medium — Two heavyweight fallback roles complicate the first usable slice.**  
   **Location:** ADR-0003; plan S1/S2; performance memory budget.  
   Local Brain fallback and vision-based OCR fallback introduce model installation, residency, and failure coordination before the main paths are proven. S1 additionally includes real TTS despite its primary acceptance being typed interaction.  
   **Suggested change:** Make S1 use static/mock speech with optional cloud explanations, and let OCR failure request manual text or recapture; retain service ports while deferring heavyweight fallbacks until measurements justify them.

4. **Medium — Automatic text “improvement” should initially be advisory.**  
   **Location:** ADR-0006, “Lexicon → models”; product B10.  
   One-edit OCR snapping can silently replace a legitimate word, and ASR hotword bias can preferentially recognize the word the learner was supposed to say. This creates a feedback loop that may improve apparent accuracy while reducing assessment validity.  
   **Suggested change:** Preserve raw observations, offer lexical correction candidates without automatic commitment, and enable ASR bias only after biased-versus-unbiased miscue evaluation.

## D. Contradictions between documents

1. **High — The privacy boundary has incompatible definitions.**  
   **Location:** AGENTS “Boundaries”; product principles; overview rule 3; C4 context; security “Third parties”; plan S0/S2.  
   Images are prohibited from leaving the LAN, but the architecture and Notifier protocol explicitly allow cloud snapshots, while edge-tts and Open Library also violate the stated two-module internet allow-list. Calling a snapshot parent-addressed does not prevent Telegram from receiving it.  
   **Suggested change:** Make notifications text-only, remove the frame parameter from the public Notifier contract, and enumerate any permitted text-only external services through an explicit egress policy.

2. **High — Correction history is both immutable and deletable.**  
   **Location:** `data-model.md`, “Invariants”; reading-flow correction step 3; ADR-0006.  
   The data model says later corrections do not rewrite miscue history, but the flow deletes OCR-caused miscues after realignment. ADR-0006 also says a corrected page is never OCR-trusted again, although one corrected span does not validate the untouched remainder.  
   **Suggested change:** Preserve historical observations, supersede invalid assessments, and distinguish user-corrected spans from unverified OCR spans within each page revision.

3. **Medium — Verdict cardinality cannot represent insertions consistently.**  
   **Location:** GLOSSARY “Alignment”, “Verdict”, “Miscue”; product B3; `data-model.md`, “Enums”.  
   A Verdict is defined per expected word, but an insertion has no expected word, and assigning it to the following word cannot represent trailing insertions. The APIs also differ between a verdict list and an `AlignResult` containing cursor movement.  
   **Suggested change:** Standardize on an alignment result containing matched/substituted/deleted token spans plus insertion events anchored between tokens, together with explicit cursor and commitment information.

4. **Medium — Text-mode parity includes an impossible acoustic promise.**  
   **Location:** Product B4/B11; plan S1/S3.  
   B11 requires B3–B8 to work in text mode, which includes pronunciation rescoring in B4. Typed text can exercise practice control flow but cannot demonstrate that a word was pronounced correctly.  
   **Suggested change:** Define text-mode parity as functional interaction and persistence, with pronunciation explicitly unavailable and no acoustic success recorded.

5. **Medium — One-process ownership conflicts with the transition deployment.**  
   **Location:** ADR-0001 “Decision drivers”; C4 container; deployment process table; plan S5.  
   The architecture describes shared devices in one process, while deployment starts study and legacy habits separately until migration. During that interval, scheduled habit speech can overlap reading or compete for the same camera without Hub arbitration.  
   **Suggested change:** Document the transitional two-process topology and enforce an exclusive study lease that suppresses habit audio, or explicitly require mutually exclusive operation until S5.

## E. Windows / RTX 50-series stack risks and prototype order

1. **High — P-1 must validate the actual ASR output contract. Prototype first.**  
   **Location:** Plan P-1/S3; ADR-0007; `utterances.words`.  
   The design assumes word start/end times and calibrated confidence, but P-1 only asks whether tokens and timestamps exist. Upstream examples expose subword tokens, and hotwords require `modified_beam_search`, so generic transducer support does not establish the selected artifact’s complete contract. ([Sherpa documentation](https://k2-fsa.github.io/sherpa/onnx/hotwords/index.html))  
   **Suggested change:** Probe the exact pinned Parakeet export for token-to-word reconstruction, timing granularity, confidence availability, silence behavior, and hotword effectiveness; represent unavailable confidence as unknown.

2. **High — P-3 needs to validate the camera-to-page pipeline. Prototype alongside P-1.**  
   **Location:** Plan P-3/S2; OCR failure behavior; research §2.5.  
   RapidOCR returns text boxes and recognition scores, but those do not by themselves define page reading order, missing-text detection, or an appropriate fallback threshold. ([RapidOCR output contract](https://rapidai.github.io/RapidOCRDocs/main/install_usage/rapidocr/usage/)) A high average score can coexist with an omitted line, wrong spread ordering, or an illustration caption inserted into the passage.  
   **Suggested change:** Test actual desk images with hands, curvature, glare, spreads, and repeated captures; require explicit crop/order selection and report missing-line and page-identity errors separately from word accuracy.

3. **High — OpenPronounce has both evaluation and dependency risks. Prototype before accepting B4.**  
   **Location:** ADR-0003 pronunciation row; plan S3; research §2.2.  
   Upstream reports that roughly one in five flagged words matched human mispronunciation labels on its cited evaluation, despite a more favorable aggregate correlation. It also requires espeak-ng, ffmpeg, and two approximately 1.2-GB checkpoints, none of which a resolvable Python wheel proves usable on Windows. ([OpenPronounce](https://github.com/Halleck45/OpenPronounce))  
   **Suggested change:** Run a Windows inference smoke test and a held-out child-speech evaluation focused on false corrections, short words, and accepted accent variants; keep automatic feedback disabled unless it passes.

4. **High — Torch installation does not establish ONNX GPU compatibility.**  
   **Location:** ADR-0003 Windows rationale; plan dependency step; performance memory budget.  
   The local environment has `torch 2.11.0+cu128`, but the plan leaves inference packages and execution providers unpinned. Current ONNX Runtime documentation distinguishes CUDA builds and incompatible cuDNN majors, so adding an arbitrary GPU wheel can fail independently of working Torch. ([ONNX Runtime CUDA requirements](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html))  
   **Suggested change:** Pin CPU-first versions and model hashes, then separately validate any GPU combination with real inference, provider reporting, peak memory, and concurrent OCR/ASR/pronunciation load.

5. **High — Kokoro and go2rtc need one end-to-end playback prototype.**  
   **Location:** Plan S2/S3; device-routing flow; `agent/tts.py`; `tools/go2rtc/PATCHES.md`.  
   Kokoro’s documented simple API returns synthesized samples, which does not establish first-chunk latency for the proposed complete-file playback path. ([Kokoro example](https://raw.githubusercontent.com/thewh1teagle/kokoro-onnx/main/examples/save.py)) The camera additionally requires codec-specific conversion and head/tail padding, so synthesis timing alone cannot validate feedback latency or absence of clipping.  
   **Suggested change:** Benchmark short words and full lines through the patched camera, recording audible start/end and truncation; put camera padding in adapter-specific audio preparation and include voice, speed, model version, and preparation settings in cache keys.

6. **High — `sounddevice` needs a capture-lifecycle prototype, not just a microphone test.**  
   **Location:** Plan S3 `local_pc`; S0 Ear contract.  
   Windows device selection, supported rates, unplugging, and overflow need defined recovery behavior before capture can reliably yield 16-kHz chunks. PortAudio callback failures do not propagate to the main thread, and callbacks must avoid blocking work, so naive asyncio integration can silently stop listening. ([sounddevice stream documentation](https://python-sounddevice.readthedocs.io/en/latest/api/streams.html))  
   **Suggested change:** Prototype bounded callback-to-worker transfer, resampling, overflow signaling, disconnect/reconnect, and pause/resume under model load; surface capture failure distinctly from learner silence.

7. **Medium — The SDK upgrade condition is partly disproved locally.**  
   **Location:** ADR-0003 “Consequences”; research §4 item 5; installed `anthropic/types/output_config_param.py`.  
   Installed `anthropic 0.120.2` already exposes `output_config.format`, but its inspected `AsyncMessages.create` signature has no explicit `fallbacks` parameter. That leaves model availability and fallback API compatibility unverified rather than proving a mandatory upgrade to 1.x.  
   **Suggested change:** Pin the working SDK, validate the intended request with synthetic text, implement application-owned fallback, and set an overall request deadline plus explicit retry limits before choosing any upgrade.

## F. Test-plan weaknesses

1. **High — Synthetic speech tests establish plumbing, not tutoring accuracy.**  
   **Location:** [Testing strategy](/E:/GitHub/scil/Leafi/docs/engineering/testing.md), “Fixtures to create”; plan S3 acceptance.  
   Kokoro reading a substituted word tests transcription/alignment but does not test a child mispronouncing the intended word. Requiring every correctly synthesized word to become `read` also leaves accent, hesitation, partial words, and noisy recognition uncertainty unmeasured.  
   **Suggested change:** Keep synthetic fixtures for reproducibility, but add a separate human-labelled evaluation measuring false corrections and missed miscues on child speech, with a held-out set.

2. **High — The main alignment seam lacks sequence-level tests.**  
   **Location:** ADR-0007 “Confirmation”; plan S1 acceptance.  
   The listed tests cover isolated substitutions, skips, and insertions but not decisions accumulated across utterances. They can all pass while pauses, rereading, repeated tokens, trailing insertions, or corrections cause permanent cursor drift.  
   **Suggested change:** Add multi-utterance scenarios and invariants: unread suffixes remain unassessed, confirmed progress is explainable, rereading creates no duplicate penalties, and correction replay is deterministic.

3. **High — Failure tests do not exercise durable side effects.**  
   **Location:** ADR-0004 confirmation; reliability table; testing “Never mocked”.  
   “Anki unreachable” does not cover remote success followed by response loss, and “close stale sessions” does not cover a crash midway through correction application. The current cases therefore miss the failures most likely to duplicate cards or corrupt learning history.  
   **Suggested change:** Inject failures at transaction and acknowledgement boundaries using real temporary SQLite and a stateful Anki fake; test duplicate delivery, rollback, migration, parent edits, and reconciliation.

4. **High — Audio fakes need temporal behavior.**  
   **Location:** Plan S0 Hub acceptance; testing adapter layer; reliability TTS row.  
   A fake Mouth that immediately returns cannot expose overlap, continued playback after timeout, or capture of Leafi’s own voice. The reliability table’s TTS-failure case points to a zero-Mouth test, which does not test synthesis failure at all.  
   **Suggested change:** Use controllable clocks and blocking/cancellable fakes to test TTS failure, hung Faces, slow Mouths, timeout cleanup, concurrent `say()`, and capture reopening.

5. **High — Privacy and migration tests are aimed above the actual seams.**  
   **Location:** Security enforcement statements; overview boundary rules; `tests/test_session.py`; plan S5 acceptance.  
   Import allow-lists and prompt-field schemas cannot detect network use inside dependencies or names embedded in ordinary strings. Existing habit session tests replace speech, notifications, and presence, so keeping them green does not prove migrated device behavior.  
   **Suggested change:** Add outbound-request capture with synthetic sensitive canaries and denied-network subprocess tests, plus contract tests for MQTT events, shutdown, snapshots, and speaker routing; explicitly include these in slice acceptance.

## G. Child-safety and privacy findings

1. **High — The cloud-snapshot exception is an existing behavior, not just a diagram error.**  
   **Location:** `agent/session.py`, notification calls; [agent/notify.py](/E:/GitHub/scil/Leafi/agent/notify.py), `send`; security red line 1.  
   The legacy code can upload a snapshot to Telegram when configured, and the new design preserves that capability despite the absolute image boundary. Leaving habits “unchanged” therefore leaves a path that violates the stated household policy.  
   **Suggested change:** Make removal or disabling of external snapshot delivery a prerequisite to operating either track under the new privacy policy.

2. **High — Text-only schemas do not prevent identity disclosure.**  
   **Location:** Overview rule 4; security red line 3; reading-flow intent classification, explanation, and wrap.  
   A learner can say their name or school inside an ordinary question, and OCR can capture a handwritten ownership label. Those values can reach a cloud prompt, notification, or generated summary without any field named `identity`.  
   **Suggested change:** Construct cloud payloads from explicitly selected book content and minimized intent data, redact configured identifiers locally, and route potentially personal free-form content locally or request a nonpersonal restatement.

3. **High — “Local pronunciation” has a hidden network default.**  
   **Location:** Plan S3 pronunciation dependency; security third-party inventory; research §2.2.  
   OpenPronounce defaults to gTTS for reference synthesis and downloads model checkpoints on first use. Its documented default can therefore send expected text externally and initiate network access outside the allowed modules, even though learner audio remains local. ([OpenPronounce configuration](https://github.com/Halleck45/OpenPronounce))  
   **Suggested change:** Force an offline reference voice or use only the required phoneme functions, provision models separately, and require inference to pass with external networking denied.

4. **High — Child control and coaching limits are not enforceable requirements.**  
   **Location:** Product principles/non-goals; reading-flow Practice and CHECK; security “Child-transparent”.  
   There is no retry cap, “skip this word,” reliable stop behavior during playback, or rule preventing uncertain assessment from becoming a persistent Difficulty. Structured Brain output also does not guarantee age-appropriate, non-shaming feedback or protect against instructions embedded in page text.  
   **Suggested change:** Set a small practice cap, offer skip/stop in every state, require corroboration before persistent penalties, validate allowed Brain actions locally, and test content boundaries and prompt injection using fixed scenarios.

5. **Medium — Retention and access controls cover only part of the data.**  
   **Location:** ADR-0006 evaluation transcripts; data-model lifecycles; security retention/network sections; `docker-compose.yml`; `tools/go2rtc/go2rtc-host.yaml`.  
   Images and optional audio have retention rules, but transcripts, evaluation logs, TTS caches, backups, and long-lived learning records do not have a coherent deletion policy. Frigate/MQTT host mappings and the RTSP listener also expose services beyond the loopback-only picture described for Leafi servers.  
   **Suggested change:** Define retention and parent-controlled deletion across every store, avoid raw-content logging by default, and document/test interface bindings, authentication, and firewall scope for each supporting service.

## Top 5 to fix before coding

1. **Resolve the privacy contradictions:** text-only notifications, explicit outbound-service policy, and offline pronunciation defaults.
2. **Define assessment semantics:** incremental alignment, uncertainty, cursor commitment, and when a pronunciation claim is justified.
3. **Version page text and its evidence:** stable page IDs, correction spans, utterance links, and auditable invalidation.
4. **Complete the runtime contracts:** composition root, audio ownership, playback completion, cancellation, and all-state controls.
5. **Move decisive prototypes ahead of S1:** exact Parakeet outputs, real camera OCR, child-speech false corrections, and actual end-to-audible feedback latency.