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
4. Evaluation, public data first (owner decision 2026-10-22; `docs/research/2026-10-22-reading-eval-data.md`):
   a. `doctor --download` gains speechocean762 (OpenSLR SLR101, CC BY 4.0, 520 MB, into `data/evals/speechocean762/`); `scripts/evals/reading_eval.py --set speechocean762 [--max-age 12]` runs Parakeet and `align` per sentence and prints the false-alarm rate (a candidate on a word the experts scored ≥ 7), the miss rate (a word scored 0–3 not flagged; 4–6 excluded) and the threshold distributions; result in Surprises, attribution in the output.
   b. The Storiza Corpus (Rose et al., CoNLL 2026) is not obtainable yet (its LDC deposit is announced, the OSF link holds only the guidelines); re-checked in M10.
   c. Last, the owner's labelled set under `data/evals/reading/` (fixture pages with deliberate errors; silent, PC microphone) as the check on Leafi's own devices.

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
- [x] 2026-10-22 ADR-0013 v2 rev 3 accepted by the owner.
- [x] 2026-10-22 M0.2 word list (`docs/research/2026-10-22-word-list.md`), M0.3 lemma source (`docs/research/2026-10-22-lemma-source.md`), M0.4 DP prototype (Surprises), M0.5 speaker model (`docs/research/2026-10-22-speaker-model.md`); choices in the Decision log.
- [x] 2026-10-22 M0 closed: the owner answered the M0 decisions (Decision log).
- [ ] M1 TD-1
- [ ] M2 harness prototype
- [ ] M3 learners and migration 5
- [x] 2026-10-22 M4 steps 1–3 (pure core): `norm` v2 (`TOKENIZER_VERSION = 2`, `num2words` readings in canonical form), the `WordInfo` port (`leafi/core/wordinfo.py`: Null = v1 crediting, Table for tests) and its local backend (`leafi/services/wordinfo.py`: word lists when installed, else lemminflect's dictionary; espeak-ng phones with the homograph table; lemminflect lemmas with the five overrides), `study/function_words.py`, `align` v2 (both passes, every rule 1–10, packed tie-break keys, greedy lexicographic reconstruction), `supply`, `opened` (the pure part of `open_page_read`), `pause_completes` v2, `retry_result`. Tests: `test_alignment.py` (walkthroughs (a)–(i), (m)–(s), (t), (u), (w) and the v1 scenarios still valid), `test_alignment_oracle.py` (the DP equals a brute-force enumeration op for op on 2,200 cases in both pass bounds, every op kind exercised), `test_norm.py`, `test_wordinfo.py`, `test_alignment_perf.py` (hardware-marked; 400 tokens, 25 words: p50 14.8 ms, p95 18.4 ms). The v1 session runs on v2 alignment (unaligned utterances, the first-words prompt, confidences passed, `LocalWordInfo` from the runner); 620 passed, 8 skipped.
- [ ] M4 remaining: the DB-backed `open_page_read` and `close_cycle` (need M3's tables and M6's cycles; the pure parts are in), the v2 Correction interaction (`unread` behind the frontier, re-tokenising every open page read, tokens found by `miscue_id`), `doctor --download` for SCOWL, CYP-LEX and the optional YLE PDF, TD-28 (the false-alarm levers, each measured separately with `reading_eval.py`), then the owner's labelled set (owner present, silent).
- [x] 2026-10-22 M4.4a: `doctor --download --only speechocean762` (opt-in, never in a plain `--download`; egress table row added), `leafi/study/evaluation.py` (pure scoring, `tests/test_evaluation.py`), `scripts/evals/reading_eval.py`; first full run recorded in Surprises and TD-28.
- [ ] M5 egress and privacy
- [ ] M6 session loop on the default policy
- [ ] M7 the Brain leads
- [ ] M8 recognition
- [ ] M9 remote teacher
- [ ] M10 measurements, console, closing docs

## Surprises & discoveries

- 2026-10-23 (TD-28) Unaligned utterances diagnosed (`reading_eval.py --diagnose`, research §5.2): 518 of 562 have no anchor because Parakeet transcribed accented learner sentences as unrelated words (204 of them were scored correct throughout by the experts), 16 exceed the ceiling, 17 were heard as nothing. Each acceptance lever alone (ceiling 7 → 10 / off, rule 4(b) share 0.5 → 0.34, rule 4(c) up to 3 words) recovers 16–32 utterances with +0–7 hits and +3–6 false alarms: the defaults stay, and the unaligned share is an ASR limit, not a rule to loosen. The ASR output is now cached once, so a lever run takes ~4 s; rule 4(b)'s share and 4(c)'s length are named constants (`ANCHOR_MATCH_SHARE`, `LONE_ANCHOR_MAX_M`) with unchanged values.

- 2026-10-23 (TD-28) `reading_eval.py` rerun with `LOW_CONF` 0.9, every other threshold unchanged: false alarms on correct content words 7.4 % → 2.6 % (children ≤ 12: 9.9 % → 2.9 %), within ADR-0013's ≤ 5 %; errors caught 393 → 127 (children 60 → 20); unaligned utterances unchanged at 11.2 % (children 14.7 %). The threshold removed false alarms and real errors in the same proportion, so the share of candidates that are real errors stayed 29 % → 27 %: confidence does not separate the two on this set. Details: `docs/research/2026-10-22-reading-eval-data.md` §5.1. The result file now records the thresholds of each run.

- 2026-10-22 (M4.4a) First reading evaluation on speechocean762 (5,000 utterances, 646 s): false alarms 7.4 % of correct content words (children ≤ 12: 9.9 %) against ADR-0013's ≤ 5 % budget → TD-28; unaligned utterances 11 % (children 15 %); miss rate ~80 %, which on this set mostly measures pronunciation errors the ASR still hears as the target word. False-alarm words have median ASR confidence 0.82 against 0.998 for correct words. Details: `docs/research/2026-10-22-reading-eval-data.md` §5; raw results in `data/evals/results/`.
- 2026-10-22 (M0.4) `scripts/prototypes/dp_v2_proto.py`: the ADR-0013 v2 page-pass DP (pair costs, affine deletions, insertions, back jumps in both pass bounds, entry, boundary per visit) as numpy arrays over tokens with a loop over heard words, the per-visit count kept as two arrays (one or ≥ 2 aligned tokens), so no state needs more than a prefix or suffix minimum per sentence. It equals a brute-force enumeration of every path on 3,000 + 400 random small cases (pages ≤ 6 tokens, ≤ 4 words, both back-jump bounds): 0 mismatches. On this PC, a 400-token page with 25 heard words, `rapidfuzz.process.cdist` pair costs included: p50 2.5 ms, p95 4.4 ms (page bound), p50 3.5 ms, p95 5.1 ms (with the fast-pass bound into the previous sentence). Not in the prototype: `number join`, the phones / inflection classes (precomputed per word), the packed tie-break keys and path reconstruction; none changes the complexity class, so the 100 ms bound has about 20× headroom and the design stays as accepted. The prototype is deleted when M4 lands its own oracle test.

## Decision log

- 2026-10-22 ADR-0013 v2 is written into the existing file (`0013-reading-algorithm-v1.md`) instead of a new ADR number, so that ADR-0013 stays the single owner AGENTS.md and ADR-0017 point to and no link breaks; v1 stays in git history.
- 2026-10-22 ADR-0018 §7.5's documents change in M5 together with the egress code, not at acceptance: changing AGENTS.md's boundary and `security.md`'s egress table before the mediator and the socket grants exist would state an enforcement that does not run. Until M5, code keeps to the v1 egress rule.
- 2026-10-22 ADR-0013 v2 rev 1 choices: function-word and (default) inflection misses produce no miscue row, only a categorised observation (kept in rev 2; neither reviewer found a loss the summary or the evaluation needs); `/back` never crosses a page (kept); within one cycle a page has one page read (kept, now moved to a new revision in place by a correction).
- 2026-10-22 ADR-0013 v2 rev 2, author's calls on review findings the owner may override (listed in the round-1 comparison): `unsure(interrupted)` and `unsure(unclear)` contribute 0 to Difficulties (rev 1 kept v1's 0.3 for `interrupted`); a supplied function word is a candidate; a spoken lone function word never anchors, a typed one does (ADR-0017 §8 amended to "when spoken"); the internal-cost ceiling rejects heavily misread short utterances instead of producing candidates.
- 2026-10-22 Codex quota ran out at the start of M0.1; the `codex-review` skill's fallback (a fresh session of another agent on the same prompt file) ran instead. The owner then chose not to wait for codex and had a fresh Claude session run the increment round too, so no codex model has reviewed ADR-0013 v2; all three of its reviews share one model's blind spots.
- 2026-10-22 ADR-0013 v2 rev 3 calls: a hint on a token already a candidate turns that miscue's origin into `supplied` rather than adding a row; a correction behind the frontier marks the touched tokens `unread` instead of sending the cursors back; `close_cycle` gives a candidate with practice attempts the practice final status, so a recorded `fail` is not lost to `not_practised`; one- and two-word skips at an utterance's end remain a named limit (two false candidates) rather than a cost change, until the labelled set shows how often they occur.
- 2026-10-22 Milestone order: M5 (egress) before M7 because M7 is the first code that would send learner text to the Brain; M6 runs on the default policy and needs no Brain.

- 2026-10-22 M0.2 `WordInfo.is_word`: the household lexicon ∪ SCOWL size-60 `en_GB-ise` + `en_US` (rel-2026.02.25; MIT-like, its notice ships with the files; 111,066 forms, inflections and both spellings included, no typos) ∪ CYP-LEX word forms for ages 7–9 and 10–12 (Korochkina et al. 2024, CC BY 4.0) above a minimum count set in M4 on the fixture books. Rejected: `wordfreq` (CC BY-SA data with typos such as "teh", frozen since 2024), SUBTLEX-UK/US (licences unstated or NC), Oxford Children's Corpus (permission), CPWD, Kuperman norms (no licence).
- 2026-10-22 M0.2 level band (ADR-0017 §6.2): Cambridge YLE level when a lemma matches a YLE headword, else CYP-LEX Zipf frequency (7–9, then 10–12). YLE has no stated licence, so it is never bundled: `doctor --download` fetches the official PDF for local parsing, and banding falls back to CYP-LEX alone when it is missing. Changes ADR-0017 §6.2's "SUBTLEX-UK children's frequency" to CYP-LEX — open for the owner (below).
- 2026-10-22 M0.3 `WordInfo.lemmas`: lemminflect 0.2.3, dictionary only (`{w} ∪ getAllLemmas(w)` over parts of speech, OOV rules off) plus a versioned Leafi override table cutting look-alike links (number/numb, liver/live, fee/feed, gamer/game, stranger/strange); `alignment_versions` = `lemminflect-0.2.3+overrides-N`. Measured on 71 inflection, 50 look-alike and 15 derivation pairs: recall 1.000, precision 0.986, no derivation false positive, 2.7 µs per word. MIT code; NIH SPECIALIST Lexicon data (credit required only if Leafi redistributes the data). Upstream dormant since 2023: the fallback is a table exported for the word list. Imported lazily (with spaCy present it imports spaCy too). Runner-up: AGID strict table (agent nouns read as comparatives: own/owner).
- 2026-10-22 M0.4: the accepted DP stands (2.5–5.1 ms p95 class against 100 ms; Surprises).
- 2026-10-22 M0.5 speaker embedding (ADR-0018 §1): 3D-Speaker CAM++ zh+en, `3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx` (28.3 MB, 192-dim, sha256 `aa3cfc16…0ceba2`, sherpa-onnx release tag `speaker-recongition-models`), Apache-2.0 on the ModelScope checkpoint, through sherpa-onnx 1.13.8 (installed, latest release) on CPU, one thread. Challenger in the household probe: ERes2NetV2 zh-cn (Apache-2.0, 71 MB, Chinese-only, ~7× compute). Rejected: WeSpeaker weights (licence disputed: dataset-bound vs tags), TitaNet-L (English-only, CC-BY-4.0). Published EERs are adult (VoxCeleb1-O 1.16 %); two studies put adult-trained ECAPA at 24–31 % EER on children, so voice stays a guess the child confirms, as ADR-0018's `identify` already does. Implementation notes: 1.13.8's `search()` returns no score, so `best` and `second` come from `score()` per candidate; `add(name, list)` sums raw embeddings, so clips are normalised first; assert the embedding length (fixed upstream after 1.13.8, #4048). Probe: 8 enrolment clips per child (compared at 3/5/8), ≥ 20 real answers per child on another day, ≥ 20 guest trials; `RECOG_ACCEPT[ear]` from guest false accepts, `RECOG_MARGIN[ear]` from sibling confusions.
- 2026-10-22 **Owner's answers (M0):** (1) CYP-LEX replaces SUBTLEX-UK (ADR-0017 §6.2 amended); (2) Cambridge YLE is an optional download; (3) the CYP-LEX extract is downloaded by `doctor`, not bundled; (5) probe recordings under `data/probes/`, deleted once the thresholds are recorded and at most after 30 days (ADR-0018 §1 amended). (4) was not asked: the five lemma overrides stand as recommended. The questions as first written:
- 2026-10-22 Open for the owner (M0), answered above: (1) CYP-LEX in place of SUBTLEX-UK in ADR-0017 §6.2 (recommended: yes, its licence is clear and it is children's print); (2) Cambridge YLE as an optional download, or CYP-LEX alone (recommended: optional download); (3) CYP-LEX extract bundled in the repository with CC BY attribution, or downloaded by `doctor` (recommended: download, as for models); (4) the five lemma overrides, especially stranger/strange, a real comparative (recommended: keep all five; a missed inflection is observed, never practised, so cutting one costs little); (5) how long the speaker-probe recordings are kept, since ADR-0018 says identification utterances are never stored (recommended: an explicit probe-only exception, recordings under `data/probes/` deleted when the thresholds are recorded, at most 30 days).

- 2026-10-22 M4 implementation choices: (1) `FUNCTION_WORDS` leaves out the directional particles up, down, out, off, over, under, which carry meaning in children's text ("the sun went down") — the fixture scenario's "dawn" for "down" stays a candidate; (2) a supplied token carries `Tok.supplied` in the reading state (persisted as an index list) so rule 7 can exempt it without a database lookup; (3) the v1 session keeps its page-settlement on a page turn until M6 replaces it with cycles (ADR-0013 v2's "a page turn completes nothing" needs the cycle to own the candidates); (4) `unaligned` observations are not written by the v1 session, since schema 4's CHECK has no such kind (migration 5 adds it); (5) without installed word lists, `LocalWordInfo.is_word` falls back to lemminflect's dictionary, so the runner gets real-word substitutions before `doctor --download` exists for the lists; (6) v1 tests whose expectations v2 changes were rewritten to v2 (a function word "had" no longer a candidate, the pause rule, the resume clamp to a sentence start, three substitutions in four words now unaligned), and the lease test waits for the session's line to finish instead of racing it.

- 2026-10-22 Owner decision: the reading evaluation (M4.4) runs on public data first — speechocean762 now (Mandarin-L1 learners, half children, expert word scores, CC BY 4.0), the Storiza Corpus when it can be obtained — and the owner's recordings only as a later check on Leafi's own devices. speechocean762 is one sentence per utterance and mostly pronunciation errors, so it measures false alarms well and misses weakly, and it never exercises the page pass; those are what the owner's set adds.

- 2026-10-22 Owner decision: `LOW_CONF` 0.5 → 0.9 now, evaluated later (TD-28). A substitution heard below 0.9 confidence is an observation, not a candidate. Chosen from the first speechocean762 run (false-alarm words median confidence 0.82, correct words 0.998); its cost in caught misreadings is unmeasured.

## Outcomes & retrospective

(at completion)
