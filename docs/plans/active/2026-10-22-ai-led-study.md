# Plan: the AI-led study session, learners and privacy v2, reading algorithm v2

Status: active, started 2026-10-22. Implements ADR-0017 (accepted 2026-10-22), ADR-0018 (accepted 2026-10-22) and ADR-0013 v2 (proposed; M0 settles it). Predecessor: [`2026-10-19-leafi-book-study.md`](2026-10-19-leafi-book-study.md) (S0–S3 built the v1 loop this plan replaces). The ADRs own every rule; this plan owns only order, scope per step and acceptance. When the code and an ADR disagree, the ADR wins or the Decision log records why not.

## Purpose / big picture

Today `leafi/study/session.py` is a fixed state machine (READ → PRACTICE at each sentence end → CHECK) for one unnamed child, and the Brain may see page text only. After this plan:

- A session is a sequence of activities. The Brain, or a configurable default policy, picks each one from a menu the harness computes; the harness constructs, runs, times, limits and records it (ADR-0017).
- Reading is never interrupted by correction. Errors are practised afterwards from the cycle's candidates; alignment tracks lost starts and rereads, ignores speech it cannot align, and stops crediting real-word misreadings (ADR-0013 v2).
- Several learners share one Leafi with separate records, recognised locally; learner text may reach the cloud per the learner's setting, pseudonymised, through one egress layer with a socket guard behind it (ADR-0018).

Who sees the result: the learner (a session that reads first and practises after, and that follows their choices at their autonomy level), the owner (settings for policy, session length, autonomy, privacy; an arm report), agents (one loop, typed records, tests per ADR Confirmation).

## Context and orientation

- Rules: [ADR-0017](../../adr/0017-ai-led-study-session.md), [ADR-0018](../../adr/0018-learners-and-privacy-v2.md), [ADR-0013](../../adr/0013-reading-algorithm-v1.md) (v2 text). Libraries and prototypes: [`../../research/2026-10-22-harness-libraries.md`](../../research/2026-10-22-harness-libraries.md) §2, §6, §7. Prior art: [`../../research/2026-10-22-domain-prior-art.md`](../../research/2026-10-22-domain-prior-art.md).
- Code that changes most: `leafi/study/session.py` (replaced by the loop), `leafi/study/alignment.py`, `leafi/core/text.py` (`norm` v2), `leafi/core/storage.py` (migration 5), `leafi/services/brain/` (purpose schemas, no retry loop), `leafi/services/tts/edge.py`, `leafi/core/netguard.py`, `leafi/study/{knowledge,anki,records,corrections}.py`. New: `leafi/core/learner_store.py`, `leafi/privacy/` (`egress`, `pseudonym`, `media`), `leafi/study/{loop,menu,construct,negotiate,observe,ledger,routing,item_status,function_words}.py`, `leafi/study/activities/`.
- Constraints that do not move: AGENTS.md boundaries (no camera speech in tests, `--mock` or `SPEAKER_BACKEND=local`), the full pytest suite green before each commit, a regression test for every change to alignment, corrections or storage, no `.env`/`data/` commits.
- Until M5 lands, the egress rule in AGENTS.md and `security.md` is the v1 one (text only, no learner text to the cloud), and code must keep to it: M6–M7 run with `cloud.text` treated as off.

## Plan of work (milestones)

Each milestone ends with the full suite green, its ADR Confirmation tests present, a commit (or a few), and a Progress line here. Milestones M1, M2 and M4 do not depend on each other and may run in parallel sessions on separate files.

### M0 — Design gates (no code)

1. Review ADR-0013 v2: codex (`gpt-6-astra`) and `code-plan-review` on the same prompt file, independently, then compared (AGENTS.md → Verification: it adds mechanisms). Round 1 done 2026-10-22 (codex fallback: a fresh Claude session); rev 2 written. Next: one increment round by codex on the rev-2 diff, then the owner accepts → `status: accepted`.
2. Licence check of the word list `WordInfo.is_word` uses (the frequency list ADR-0017 §6.2 ranks with, SUBTLEX-UK children's or an alternative); record the choice and licence in the Decision log. `num2words` is LGPL-2.1, used unmodified as a library.
3. The lemma source for `WordInfo.lemmas` (ADR-0013 → Pair classes `inflection`): `tiered-research` → `gather-code-references` over lemminflect, spaCy's lemmatizer (already a dependency of ADR-0018's Presidio), a table from the word list; licence, size, accuracy on child-book inflections; the choice in the Decision log.
4. A timed prototype of the v2 DP (vectorised, packed tie-break keys) on a 400-token page with 25 heard words, checked against a brute-force reference on small inputs; the p95 recorded in Surprises. Over 100 ms → the design changes (e.g. a page pass restricted to sentence starts) before acceptance, not after.
5. Decide the speaker-embedding model for ADR-0018 §1 (sherpa-onnx speaker identification; model, licence, version) — recorded here before M8.

Acceptance: ADR-0013 `status: accepted`; Decision log rows for 2, 3 and 5; the prototype figure for 4.

### M1 — TD-1: `anthropic` ≥ 1.x on `httpx2` (ADR-0017 §10 precondition)

Upgrade `anthropic`, build every SDK client with `max_retries=0` and a per-request timeout, call `httpx2.alias_httpx()` first in `leafi.cli`, move Leafi-built clients to `httpx2`, drop the Claude backend's own retry loop and `BRAIN_DEADLINE_S` only when M7's `brain_call` replaces them (until then keep one retry). Probes P-B1 and P-B6 (libraries §2) as tests. Acceptance: suite green; `tests/test_privacy.py` no-network run green; `leafi doctor` clean.

### M2 — Harness prototype (libraries §7)

Combination 1 ("thin, own the loop") against Combination 2 ("library-backed") on the six scripted steps of libraries §7 with the mock Brain, `--mock` audio and `--page-text` pages, nothing speaking on the camera. Measures: code size, latency per decision, cancellation, resume after `TerminateProcess` at the three kill points, privacy canary, migration under lock. P-A1–P-A7 as tests. Acceptance: the choice per mechanism in the Decision log by libraries §7's exit criterion; the winning tests become the first entries of ADR-0017's Confirmation. Prototype code lives under `scripts/prototypes/` and is deleted after the decision.

### M3 — Learners and migration 5 (ADR-0018 §1 data, §7.1–§7.2; ADR-0017 §7.2 tables; ADR-0013 v2 columns)

1. Open-database three states and the shared `portalocker` lock on `data/leafi.db.users`.
2. Migration 5 in one transaction (`rebuild()` helper or the M2 choice), every table of `data-model.md` → Migration 5, `python -m leafi migrate --learner "<name>"` with backup, `foreign_key_check`, schema-equals-fresh test.
3. `leafi/core/learner_store.py` and every writer of ADR-0018 §7.1 learner-scoped; a test inserts through every writer under two learners.
4. `forget --learner` (ADR-0018 §1) and `forget --session|--book` reaching the new tables.

Acceptance: `tests/test_open_db.py`, `tests/test_migration_5.py`, `tests/test_forget.py` (local stores), `tests/test_storage.py` green; the owner runs `leafi migrate` once on the real `data/leafi.db` (console button, then removed) after a `leafi backup`.

### M4 — Reading algorithm v2 (ADR-0013 v2; after M0.1)

1. `norm` v2: `num2words` readings in canonical form, `TOKENIZER_VERSION = 2`; token boundaries equal v1's on every fixture page (`tests/test_norm.py`).
2. `WordInfo` port: espeak-ng phones through the existing `phonemizer` + `espeakng-loader` with the homograph table, the word list from M0.2, the lemma source from M0.3, answers precomputed per revision and per utterance, versions into `page_reads.alignment_versions`; a table fake for tests; `study/function_words.py`.
3. `align` v2 from the M0.4 prototype: pair classes, `number join`, fast pass and page pass, back jumps, affine deletions, the entry and sentence-skip costs, boundary per visit, acceptance 4(a)–(d) and the ceiling, `unaligned`, rule 5 marks, rules 6–10; `supply`; `open_page_read`; every walkthrough (a)–(w) as a test; `tests/test_alignment_oracle.py`; `tests/test_alignment_perf.py` (hardware-marked, 100 ms p95, 400 tokens, 25 words).
4. `scripts/evals/reading_eval.py` and the labelled set under `data/evals/reading/` (the owner reads fixture pages with deliberate errors; silent, PC microphone): false-alarm and miss rates printed; result in Surprises.

The v1 session keeps working on v2 alignment (its PRACTICE calls the v2 retry test) until M6 replaces it. Acceptance: the tests above; the false-alarm rate recorded (a breach is a TD row, not a blocker for M6, because `practise_errors` frames every candidate as practice).

### M5 — Egress and privacy (ADR-0018 §2–§5, §7.3–§7.5)

1. `leafi.privacy.egress`: `prepare`, attempt tokens bound to the body's HMAC, the mediated `httpx2` transport (single-use tokens, one text retry, per-transmission budget hook), synthetic 403, `egress_log` with the per-install HMAC secret.
2. `netguard` grants: protected targets including the gateway ports, grants per transmission, the patched async `getaddrinfo`, the `lan` class, `LEAFI_NO_NETWORK` refusing grants too.
3. Provenance columns filled by every writer; the filter; pseudonymisation lists, `household_terms`, surrogate names, the age band in the system prompt; Presidio + spaCy `en` behind `privacy.name_detector`.
4. Every network caller of ADR-0018 §7.3 through `egress`; `tts.edge_mode` both modes; TTS routing by provenance (`privacy.tts_learner_lines`).
5. Privacy settings of §5 on the settings page with the † typed confirmation; the Anki notice.
6. The documents of ADR-0018 §7.5, in the same change as the enforcement: AGENTS.md's first MUST NOT → §8's line, `security.md` (egress table, privacy settings, retention), `product.md` principles 1–2 and the non-goal, `GLOSSARY.md` (Brain, Eye, Learner; learner kind, guest, provenance, remote teacher, grant, surrogate name, gateway port), `overview.md`, C4 docs, `deployment.md`, `config.md`, `code-locator.md`, `testing.md`, `repo-map.md`, ADR-0003, ADR-0011 (`superseded-in-part-by: 0018`), ADR-0016.

Design review: none needed for the ADR's own mechanisms; any mechanism the code needs beyond them gets the three-reviewer round (it touches privacy and egress). Acceptance: `tests/test_netguard.py`, `tests/test_egress.py`, `tests/test_privacy.py` (rewritten), `tests/test_pseudonym.py`, `tests/test_architecture.py` green; a measured recall of the name detector on the household's transcripts recorded before anyone claims completeness.

### M6 — The session loop on the default policy (ADR-0017 §1–§3, §6, §7.2–§7.3, §8; after M2, M3, M4)

1. The loop of §2 with the latch, `terminate`, the cancel scope without deadline, the deadline watcher, `spawn`, `checkpoint`, `take_skip`, the mapping function, `finalize` / `deliver` / `extract_notes` (a no-op until M7), lease handling.
2. `allowed(s)`, `construct`, the default policy with its `when` vocabulary and `policy_version`, `negotiate` with every autonomy setting and its save-time ranges, `wait` and `end` activities.
3. Activities whose content owner can be `code`: `read_listen` (cycles, continuations, page turns, ADR-0017 §6.1 speech), `practise_errors`, `review_anki` (eases 1–4), `read_aloud`, `add_cards` (one path into Anki, card checks), `break`, `end`.
4. Ledger, soft and hard deadlines, `session.end_mode`, session-length settings for learners, guests and unknown ages; busy-store handling of §7.3.
5. Identification minimal form: console pick or "who's reading" by name in text and voice, guests and their end states, the sweep (ADR-0018 §1, without recognition).
6. Remove the v1 state machine, `sentence_done`, the per-sentence practice, `_cancel_inputs`'s raw `task.cancel()`, `_queue_update_if_pushed`.

Acceptance: ADR-0017's Confirmation tests that do not need a Brain (`test_session_start`, `test_cancellation`, `test_spawn`, `test_soft_deadline`, `test_end`, `test_session_menu`, `test_construct` (code-owner cases), `test_default_policy`, `test_negotiate*`, `test_controls`, `test_session_length`, `test_cycle_candidates`, `test_epoch`, `test_reading_settings`, `test_activity_status`, `test_settings_reload`, `test_anki_single_path`, `test_card_checks`, `test_busy`, `test_difficulties`), ADR-0018's `test_learners.py` identification and guest cases; the `cache/voice-diag.wav` replay with `interrupt=never` says nothing inside reading; `python -m leafi study --text --mock` runs a whole session on the default policy.

### M7 — The Brain leads (ADR-0017 §4–§5, §6.2, §7.1, §9; after M1, M5, M6)

1. `observe`, the `decide` schema, `brain_call` with contexts, tiers, `route()`, `difficulty()`, the cascade with `degraded`, output reserve, filler at 0.8 s.
2. `generate` kinds and their schemas: `teach_items`, `quiz` (answerability, CROWD types), `learner_questions`, Brain-owned content for the other kinds; `judge` with few-shot examples; answer scores of §3.4.
3. Items: ranking, `item_status.apply`, retrieval events, both mastery modes, `recall_items` spacing.
4. Records: `apply_records`, `extract_notes` with citations; arms, propensity, the arm report; the decision replay set under `data/evals/decisions/`.

Acceptance: the remaining ADR-0017 Confirmation tests (`test_arms`, `test_brain_call`, `test_routing`, `test_answer_scores`, `test_mastery`, `test_recall_schedule`, `test_item_status`, `test_construct` Brain cases); `tests/test_prompt_injection.py` on the new schemas; a mock-Brain session and a real-Claude text session (`--text`, the owner present) both complete.

### M8 — Recognition (ADR-0018 §1; owner present for probes)

Voice: enrolment by averaged clips, per-Ear thresholds from this household's probe, `recognition.voice` setting; face: YuNet + SFace only after the hit rate is measured at the study camera position. Console buttons for enrolment and the probe. Acceptance: `tests/test_learners.py` recognition cases; probe results in `docs/hardware/`.

### M9 — Remote teacher (ADR-0018 §4; last)

`media` purpose, the `prepare` checks for images and audio, the consent table's per-item `remote_teacher` consent, magpie as a provider with its structured-output probe. Acceptance: `tests/test_consent.py`, `tests/test_media_prepare.py`.

### M10 — Measurements, console and closing docs

Perceived-moment budgets and the output reserve measured per Mouth (PC and camera, ADR-0017 §5.2; the camera only with the owner present and audible); Ollama memory and latency next to the other models (research D10) to lift `GATE_FLOOR`; console buttons of ADR-0017 §10, ADR-0018 §7.6 and ADR-0013's reading evaluation, checked with `check-console.js`; `docs/ownership-map.md`, `code-locator.md`, `testing.md` updated; ADR-0017 `revised` note listing where the code differs.

## Validation and acceptance

- Every milestone: `.venv\Scripts\python -m pytest -q` green, ruff clean on touched files, ADR Confirmation tests of that milestone present and named as in the ADR.
- End to end (after M7): `python -m leafi study --text --mock` and a voice session with `--mouth pc` run a full session — identification, review, reading with a page turn, practice, a quiz, wrap — with no line inside reading beyond ADR-0017 §6.1, and the export shows activities, arms and overrides.
- Privacy (after M5): the rewritten canary test and the no-network run green; no cloud-destination body holds a real name, exact age or school.

## Idempotence and recovery

- Migration 5 runs in one transaction with a backup first; a failure leaves version 4 intact and the command re-runnable.
- Each milestone is a set of commits that leave the suite green; reverting a milestone's commits restores the previous behaviour, except M3 after the owner migrated the real database (restore the backup).
- Probes that need the owner (M4.4, M8, M10) are written so that they run silently or on the PC Mouth, and the plan records when they ran.

## Progress

- [x] 2026-10-22 ADR-0017 and ADR-0018 accepted by the owner; ADR-0013 v2 written (proposed); `flows/reading-session.md`, `product.md` B3/B4/B7, `GLOSSARY.md`, `data-model.md` (migration 5), `reliability.md`, `security.md` (prompt-safety allow-list) updated; this plan written.
- [x] 2026-10-22 M0.1 round 1 on ADR-0013 v2: `code-plan-review` (3 High) and a fresh Claude session for codex, whose quota had run out (2 High); 5 of 6 themes found by both; compared in `reviews/2026-10-22-adr-0013-v2-round-1-comparison.md`; rev 2 resolves every finding (ADR-0017 pointers, `data-model.md`, glossary updated with it).
- [x] 2026-10-22 M0.1 round 2 (increment on rev 2) by a fresh Claude session at the owner's request instead of waiting for codex: 2 High, 6 Medium, 10 Low (`reviews/2026-10-22-adr-0013-v2-round-2-claude.md`); rev 3 resolves all but M5, which was a false positive (`miscues.observation_id` is already nullable).
- [ ] M0 design gates (remaining: M0.2–M0.5, owner acceptance of ADR-0013 v2)
- [ ] M1 TD-1
- [ ] M2 harness prototype
- [ ] M3 learners and migration 5
- [ ] M4 reading algorithm v2
- [ ] M5 egress and privacy
- [ ] M6 session loop on the default policy
- [ ] M7 the Brain leads
- [ ] M8 recognition
- [ ] M9 remote teacher
- [ ] M10 measurements, console, closing docs

## Surprises & discoveries

(none yet)

## Decision log

- 2026-10-22 ADR-0013 v2 is written into the existing file (`0013-reading-algorithm-v1.md`) instead of a new ADR number, so that ADR-0013 stays the single owner AGENTS.md and ADR-0017 point to and no link breaks; v1 stays in git history.
- 2026-10-22 ADR-0018 §7.5's documents change in M5 together with the egress code, not at acceptance: changing AGENTS.md's boundary and `security.md`'s egress table before the mediator and the socket grants exist would state an enforcement that does not run. Until M5, code keeps to the v1 egress rule.
- 2026-10-22 ADR-0013 v2 rev 1 choices: function-word and (default) inflection misses produce no miscue row, only a categorised observation (kept in rev 2; neither reviewer found a loss the summary or the evaluation needs); `/back` never crosses a page (kept); within one cycle a page has one page read (kept, now moved to a new revision in place by a correction).
- 2026-10-22 ADR-0013 v2 rev 2, author's calls on review findings the owner may override (listed in the round-1 comparison): `unsure(interrupted)` and `unsure(unclear)` contribute 0 to Difficulties (rev 1 kept v1's 0.3 for `interrupted`); a supplied function word is a candidate; a spoken lone function word never anchors, a typed one does (ADR-0017 §8 amended to "when spoken"); the internal-cost ceiling rejects heavily misread short utterances instead of producing candidates.
- 2026-10-22 Codex quota ran out at the start of M0.1; the `codex-review` skill's fallback (a fresh session of another agent on the same prompt file) ran instead. The owner then chose not to wait for codex and had a fresh Claude session run the increment round too, so no codex model has reviewed ADR-0013 v2; all three of its reviews share one model's blind spots.
- 2026-10-22 ADR-0013 v2 rev 3 calls: a hint on a token already a candidate turns that miscue's origin into `supplied` rather than adding a row; a correction behind the frontier marks the touched tokens `unread` instead of sending the cursors back; `close_cycle` gives a candidate with practice attempts the practice final status, so a recorded `fail` is not lost to `not_practised`; one- and two-word skips at an utterance's end remain a named limit (two false candidates) rather than a cost change, until the labelled set shows how often they occur.
- 2026-10-22 Milestone order: M5 (egress) before M7 because M7 is the first code that would send learner text to the Brain; M6 runs on the default policy and needs no Brain.

## Outcomes & retrospective

(at completion)
