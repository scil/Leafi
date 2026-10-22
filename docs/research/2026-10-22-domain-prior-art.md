# Domain prior art: provenance of every mechanism in ADR-0013, ADR-0017 and ADR-0018 (reference collection)

Checked: 2026-10-22. Method: `tiered-research` (T1 = the owner's own docs, standards, regulators, PyPI, the project's repository; T2 = empirical studies, with scope; T3 = exemplar code read directly, or a local measurement; T4 = secondary, "reported" only). Three parallel searches (reading algorithm, AI-led session, learners and privacy) and one in-repo trace. Every claim traces to a row of §6. Rows marked *(reported)* or *(not verified)* were not confirmed against a primary source.

Companion: `2026-10-22-harness-libraries.md`. It covers the generic machinery (migrations, deadlines, retries, orchestration, LLM calls, egress); this file covers domain mechanisms only.

Decision it serves: the owner asked for code-plan-review H7 (ai-skills `skills/code-plan-review/SKILL.md`, commit 2c3490b) to be applied to the three ADRs:

- **H7.1:** every mechanism gets one provenance line:
  - *adopted*: taken as is, from where and at which version;
  - *adapted*: what changed and why;
  - *original*: what was searched, and why nothing fit.
- **H7.2:** every finding of the earlier research traces to a decision that uses or rejects it.

Columns used in every table:

- **current**: the provenance the ADR and the research files record today. "none recorded" means the ADR cites nothing.
- **recommendation**: *adopt*, *adapt* or *keep*. *keep* means keep the current mechanism, sometimes with a note to add.

## 0. Summary

| ADR | mechanisms | current: adopted / adapted / original | recommended: adopt / adapt / keep |
|---|---|---|---|
| ADR-0013 reading algorithm (and the reading parts of 0017) | 29 | 2 / 5 / 22 | 3 / 9 / 17 |
| ADR-0017 AI-led session | 34 | 5 / 15 / 14 | 0 / 10 / 24 |
| ADR-0018 learners and privacy | 24 | 2 / 1 / 21 | 2 / 8 / 14 |
| **Total** | **87** | **9 / 21 / 57** | **5 / 27 / 55** |

What this says:

- **About two thirds of the mechanisms are original.** Most of them stay original for a good reason: Leafi-specific state, controls, a physical book, the owner's own decisions.
- **ADR-0013 records almost no provenance.** It names only `rapidfuzz`. Its DP descends from Needleman–Wunsch and Project LISTEN through ADR-0007, but no cost value has a source.
- **ADR-0018 cites only owner decisions.** The research files contain no prior art for pseudonymisation, speaker or face recognition, or consent.
- **ADR-0017 is the best sourced.** Its weak spots are the autonomy thresholds, the §9 evaluation, `judge` and quiz scoring, and a dozen numeric defaults with no basis.

H7.2 trace (§4) of the two research files, 227 findings:

| file | findings | used | rejected with reason | contradicted silently | mentioned by no decision |
|---|---|---|---|---|---|
| `2026-10-19-prior-art-book-study.md` | 55 | 41 | 8 | 0 | 6 |
| `2026-10-21-ai-led-study.md` | 172 | 109 | 14 | **8** | **41** |

### Top recommended changes to the ADRs

Ranked by impact. Each item names the row it comes from in §1–§3.

1. **ADR-0013: stop crediting real-word misreadings as correct** (§1 #9, #13).
   - With the 0.80 fuzzy threshold, house/horse 0.80, there/three 0.80, though/through 0.92 and walked/walk 0.80 all count as matched (RA23). These are classic graphic miscues (RA14).
   - Project LISTEN costs a mismatch by phonemic as well as spelling distance (RA1).
   - Change: a real-word pair at sim ≥ 0.80 becomes a substitute. Keep fuzzy credit for non-words and for equal g2p phones. The practice retry passes only on an exact match, a homophone or the same phones.
2. **ADR-0013: model rereads and jumps inside the DP, and add an off-task outcome** (§1 #2, #3, #5, #12).
   - LISTEN's MultiMatch treats regressions as reading and charges a jump penalty on any non-sequential transition (RA1).
   - 17.6 % of child speech to the tutor was off-task (RA2).
   - Change: one page-wide pass with internal jumps and affine deletions replaces the bounded window, the "> 3 deletions" rule and the two-strike Reposition. This is the most likely fix for the session-11 defect.
   - It equals research 10-21 D5, which ADR-0017 §8 deferred with no tech-debt row or trigger (§4.3).
3. **ADR-0013 and ADR-0017: exclude function words from practice** (§1 #5, #13, #19, #26).
   - LISTEN halved its false alarms by ignoring miscues on 36 function words (RA3).
   - Keep them as observations. Never let a lone function word anchor rule 3(b).
4. **ADR-0017 §9: evaluate before trusting, and measure outcomes** (§2 #27; §4 D9 contradicted).
   - The research said to evaluate the Brain against the code default before trusting it (10-21 D9). ADR-0017 makes the Brain primary from the first session and reviews afterwards.
   - Logging `default_spec` beside each decision cannot show the outcome of the move not taken.
   - Change: either run the default as primary until replay shows the Brain at least as good, or run the default on a small randomised share of boundaries and log the propensity, so outcomes compare without bias (SS22). Both need an owner decision.
5. **ADR-0018: a biometric template is a parent act** (§3 #2, #9; conflicts C1–C3).
   - Today a child creates a voiceprint with one spoken yes, and recognition is on by default.
   - Every guidance source read treats biometric identification as needing explicit, and for children parental, consent: GDPR Art. 9 (LP35); COPPA voiceprints (LP39); Canada's privacy commissioner (OPC) (LP43). Google and Amazon have the parent set up a child's voice model (LP23, LP24).
   - Change: enrolment needs the parent PIN and writes a consent record. "On by default once enrolled" can stay as the owner decided. The conflict is stated in §3.3, not resolved.
6. **ADR-0018: a second name detector and realistic surrogates** (§3 #15, #16).
   - Keep list-based replacement first.
   - Add Presidio 2.2.364 with spaCy `en` PERSON on learner-class text (LP1, LP2), and use surrogate names rather than tokens (LP9, one study).
   - Claim nothing until recall is measured on Leafi's own child transcripts. Detectors degrade on informal text (LP8, one study), and Presidio gives no completeness guarantee (LP2).
7. **ADR-0018: name licence-clean face models now** (§3 #5, #19).
   - Use YuNet for detection (MIT) and SFace for recognition (Apache-2.0) (LP20, LP21). YuNet also does the media face check.
   - Rule out InsightFace pretrained weights, which are non-commercial (LP19), and face_recognition, which its own README calls poor on children (LP22).
8. **ADR-0017: quiz and `judge`** (§2 #19, #20; §4 C26/N20).
   - Check at construction that each answer is supported by the page; the research's answerability check was dropped.
   - Add CROWD question types (SS30, *reported*).
   - Score open answers with `judge` on the `standard` tier with few-shot examples until a labelled set of the child's answers justifies `fast`. The only evidence is GPT-4 few-shot: κ 0.70 vs human 0.75 (SS20), QWK 0.92 (SS21).
9. **ADR-0017: fix contradictions with the research that are not explained.**
   - **When a word counts as known.** "≥ 2 successes on different days" vs the research default "≥ 6 retrievals over ≥ 3 days" (§2 #17, §4 C30/P14). Also store full retrieval timestamps so half-life regression (SS6) or FSRS (SS37) can be fitted later.
   - **Rereading a familiar page.** `read_listen` accepts only `page: current|next`, so Reading Recovery's familiar-page reread cannot be chosen (§4 C35/P27).
   - **Age-scaled ceiling.** The research's age-scaled session ceiling was dropped (§2 #8b).
10. **ADR-0018: one consent table and one retention schedule** (§3 #18, #21, #22).
    - Name consent columns after ISO/IEC TS 27560 / DPV (purpose, recipient, status, validity, indicated by) (LP47).
    - Use the same table for media items, `cloud.text` and biometric enrolment.
    - Write a retention table per data class (LP41, LP43).
    - Replace the bare sha256 in `egress_log` with an HMAC keyed by a per-install secret: an unsalted hash of a short child answer can be confirmed by guessing (LP3).

Smaller adaptations are in each section's table:

- **ADR-0013:**
  - Write down the running-record conventions (self-correction and repetition are not errors; a told word is) and record a self-correction count (RA14).
  - Strike the per-sentence practice cap, which 0017 superseded.
  - Handle numbers in `norm()` with num2words (RA13).
- **ADR-0017:**
  - Anchor the autonomy bands to the levels-of-automation scale (SS23, SS25).
  - Replace the free `note` with Bridge's evidence, strategy and intention slots (SS18).
  - Move memory writing to a post-session extraction call (SS5).
  - Add a third card-check outcome, `flag`, beside pass and reject (SS12).
  - Label the untuned defaults as such.

Documentation gaps found by the trace (§4.3):

- ADR-0017's header claims fewer pool items than it implements.
- The plan's Decision log stops at 2026-10-20.
- `tech-debt.md` has no entries from the 2026-10-21 research.

## 1. ADR-0013 reading algorithm (and the reading parts of ADR-0017)

| # | mechanism | ADR § | what the ADR does now | current provenance | prior art | recommendation |
|---|---|---|---|---|---|---|
| 1 | Token statuses, `ReadingState` | 0013 Definitions | 6 statuses; frontier `pcur`, commit `ccur` | original; none recorded | RA6, RA7, RA14 | **keep**. These are tutoring state, not an assessment taxonomy. Map them to RA6/RA14 categories in reports. |
| 2 | `align()` window | align 1 | bounded window around the cursors | original; research 10-21 §3.3 ties it to session 11 | RA1 (current-sentence model + jumps), RA16 (band around a forward path) | **adapt**: bounded fast path, then one page-wide jump-scored pass (#12) |
| 3 | DP costs (0 / 0.3 / 1.0 / 0.8 / 1.2 / jump 0.1·dist / boundary 0.5) | align 2 | global alignment; jump only on the first aligned index | adapted: Needleman–Wunsch per ADR-0007 option 3; every value original | RA1 MultiMatch (orthographic + phonemic mismatch; jump on any non-sequential transition; regressions are reading), RA17 (affine gaps) | **adapt**: (a) internal jump-back transitions; (b) add phonemic distance (g2p-en) to the mismatch cost; (c) affine deletions instead of the "> 3" special case |
| 4 | Tie-break | align 2 | cost → nearest `pcur` → fewest inserts → lexicographic | original | none needed | **keep** |
| 5 | Acceptance rule | align 3 | run ≥ 2, or one match within `pcur ± 2` | original; research 10-21 §3.3: run ≥ 2 accepted a forced path in session 11 | RA2: in off-task speech, sentence words seldom occur two in sequence; function words do occur | **adapt**: (b) only for a content word or confident ASR; add an explicit `off_task` outcome |
| 6 | `line_skipped` (> 3 deletions → `unread`) | align 4 | no candidates | original | RA1 (skip ≤ 1); RA14 (a running record counts each word of a skipped line) | **keep**: lenient on purpose; report `tokens_unread` next to accuracy |
| 7 | Candidate lifecycle; withdrawn by self-correction or reread | align 5 | later match withdraws | original; none recorded | RA14 (after Clay 1993: self-correction and repetition are not errors); RA6; RA1 | **adopt** the running-record convention explicitly; record a self-correction count |
| 8 | `unsure` reasons; `confirmed` only with acoustic evidence | Practice; 0017 §8.6 | never confirmed in text mode | adapted from LISTEN's bias to acceptance (10-21 B9) and OpenPronounce (10-19 §2.2) | RA1: false alarms 4 % → < 1 % while detecting 23 % of substitutions; "tracking trips up scoring"; RA3 | **keep**: the evidence supports under-rejection. State a false-alarm budget and measure it. |
| 9 | `sim` = `fuzz.ratio/100`, fuzzy at ≥ 0.80 | Definitions | 0.3 cost, counted as matched | adopted: rapidfuzz 3.14.6 (RA8); threshold original | RA8, RA23 (computed pairs), RA1 (phonemic distance), RA3 (dropped endings are the most frequent decoding errors) | **adapt**: real-word pairs → substitute; fuzzy credit for non-words or equal g2p phones; decide dropped inflections explicitly (dialect, RA1) |
| 10 | Commit scan | align 6 | `ccur` past attempted tokens | original | RA1 ("chase the kid" to track, "blame the kid" to credit) | **keep**; cite RA1 |
| 11 | Sentence completion, 1.2 s pause | Sentence completion | first of reached / pause / control | original | RA1 (wait if content words remain); RA2 (0.2 s lag: 58 → 70 % exact tracking) | **keep**; measure 1.2 s on recordings |
| 12 | Reposition | Reposition | two unanchored → page-wide run ≥ 3 → ask for the first words | original; research 10-21 D5 asks for a redesign | RA1, RA2, RA16 | **adapt**: page-wide jump DP + `off_task` replaces the two-strike counter; keep "first words" as the last fallback |
| 13 | Practice: model, ≤ 2 retries, `sim ≥ 0.80`, skip, 10 s idle | Practice; 0017 `practise_errors` | retry test | adapted from Reading Coach Word Practice (10-19 reading-coach-faq; 10-21 B1–B4); counts original | RA5 (no count or mastery rule documented); RA3 | **adapt**: pass on exact / homophone / same phones only; no practice for function words |
| 14 | ≤ 2 candidates per sentence | Sentence completion | others → `unsure(not_practised)` | original; superseded in effect by 0017 §6.3 (`max_errors` 5, from 10-21 B4) | 10-21 B4 | **adopt** 0017's cap; strike the per-sentence rule (0017 §8.1 removed practice at sentence end) |
| 15 | `/back N` | /back | reopen N sentences | original | RA1 (reread a non-fluent sentence); 10-21 B4 | **keep** (an interface control) |
| 16 | Control precedence | Control precedence | stop > next page > back > skip | original (engineering) | none | **keep** |
| 17 | Interrupted-session resume | Interrupted session; 0017 §8.5 | `unsure(interrupted)`; "continue from page N?" | original | SS35 (e-reader furthest page, *reported*) | **keep** |
| 18 | Correction interaction | Correction interaction; ADR-0010 | edit maps, invalidation | original | none found | **keep** |
| 19 | Difficulties (words) | Difficulties | Σ v·0.5^(days/30); 1.0 / 0.3; watch after 3 sessions | original; none recorded | RA10 (half-life regression learns half-lives; Anki/FSRS owns memory per ADR-0004) | **keep**: a priority score, not a recall model. Mark 30 / 0.3 / 3 as untuned; exclude function words. |
| 20 | Difficulties (knowledge items) | Difficulties | ≥ 2 sessions | original | — | **keep** |
| 21 | CHECK outcomes | CHECK | keyword set → correct; ≥ 2 content words → incorrect | original | RA11 (GPT-4 QWK 0.92, one study, Ghana); RA12 (keyword matching is the baseline) | **adapt**: `judge` when cloud text is allowed; keyword rule as local default and fallback |
| 22 | Async guard | Async guard | `(session, revision, turn_id)` | original (engineering) | SS34 (fencing token) | **keep** |
| 23 | `norm()` | Definitions; `leafi/core/text.py` | digits 0–999 → one word; contractions table | original | RA13 (num2words 0.5.14, LGPL), RA19 (NeMo WFST, heavy) | **adapt**: collapse heard number-word runs ("twenty one" ≠ `twentyone` today); num2words for ordinals, years, > 999; bump `TOKENIZER_VERSION` |
| 24 | Silence ladder in `read_listen` | 0017 §6.1 | 3 s cue, +3 s hint offer | adapted from LISTEN 2 s + 2 s (10-21 B9) and EPS (B8) | RA1 | **keep**; cite RA1 |
| 25 | Supplied word → candidate | 0017 §6.1 | told word counts | original | RA14 (told word = one error) | **adopt** the convention; cite RA14 |
| 26 | `practise_errors` order and cap | 0017 §3.1, §6.3 | top by Difficulty, ≤ 5 per cycle | adopted from Reading Coach (10-21 B1–B4) | RA5 | **keep**; add the function-word exclusion (RA3) |
| 27 | `reading.encourage` | 0017 §6.1 | ≤ 1 specific line per page | adapted from 10-21 P37/P38 | RA14 (self-correction is the behaviour worth naming) | **keep** |
| 28 | Hotwords toward the page text | 10-19 D9 (no ADR) | not used | prototype pending | RA9: sherpa-onnx NeMo transducer hotwords in `modified_beam_search` only; RA1 "distracters detract" | **adapt (prototype)**: bias only the practice retry toward its target, never page reading (it would hide miscues) |
| 29 | Forced aligners instead of the DP | ADR-0007 option 2 (rejected) | not used | original rejection, no source | RA15 aeneas, RA18 whisperX, RA20 MFA, RA21 Gentle (all assume audio matches text); RA4 ReadAlongs (MIT) | **keep the rejection** for checking reading; ReadAlongs only for `read_aloud` highlighting (10-21 B16) |

Pitfalls from the prior art that ADR-0013 does not address:

- **The cost of the trade-off.** LISTEN deliberately under-rejected (RA1). Leafi's miscue detection rate and false-alarm rate are unmeasured.
- **ASR insertion rate.** LISTEN's ASR inserted about 17 % (RA1). An insert cost of 1.2 must hold against that.
- **Dialect.** Dropped final consonants are not errors (RA1, RA14).
- **Children's ASR.** Miscue precision is poor even in research: 0.52 on Dutch children (10-21 B13). Whether Parakeet keeps repetitions verbatim is unmeasured (10-21 B15, §9.2).
- **Azure Pronunciation Assessment is no fallback.** Miscue detection does not run in continuous mode, and the service would send audio to the cloud (RA7, AGENTS.md).
- **An unverified rule.** Research 10-21 §3.3's off-task rule wording could not be traced to B9 or B11. It probably comes from Chen & Mostow 2011, which was not fetched; mark it unverified before encoding it.
- **No reusable code.** No open-source oral-reading-fluency code exists to reuse; only papers were found (RA22). The DP stays original, built on RA1's design.

## 2. ADR-0017 AI-led study session (domain mechanisms)

Generic machinery is excluded (see the companion file), and so is ADR-0013 alignment.

| # | mechanism | ADR-0017 § | what the ADR does now | current provenance | prior art | recommendation |
|---|---|---|---|---|---|---|
| 1 | Activity kinds (10) | §3.1 | fixed set | original (owner's task list, research §1, §7) | SS4 (Rasa CALM fixed commands), 10-21 A13, B1–B4 | **keep** |
| 2 | Final statuses, `interrupted` from recovery | §2, §3.1 | one enum, terminal set | original (codex reviews) | SS29 (cmi5: completed, passed/failed, abandoned, terminated, waived) | **adapt**: map to cmi5/xAPI verbs in the parent export |
| 3 | Reading cycle; no correction during reading | §1, §8.1 | practice after the cycle | adapted from Reading Coach (B1–B4), LISTEN (B9), P9, B12, B18 | SS38 (*reported*), P32 | **keep**; scope gap: no L2-child study (10-21 §9.1) |
| 4 | Continuation `read_listen` on page turn | §2, §8.2 | same cycle, no Brain call | original | none | **keep** (follows from a physical book) |
| 5 | Menu `allowed()` | §3.2 | Brain picks only from code's set | adapted from CALM (R6), Pipecat (A13); StratL (A10) | SS17 (LLM-chooses-intent variant scored worse), SS25 (system preselects, learner picks) | **keep**; cite SS25 |
| 6 | `construct()` validation | §3.3 | kind, ids, counts, lengths, no URLs | adapted from LiveKit `ToolError` (R9), R2 | SS12 | **keep**; add answerability (#19) |
| 7 | `default_spec` order | §3.3 | code-only policy and §9 baseline | original order; practice-after-reading from B4 | SS17 (a code graph plays the same role) | **keep**; say so |
| 8a | Limits with a basis: errors 5, new 3/8, quiz 4, session 20 | §6.3 | ledger | adapted (B4, P25, P3, P27, B3, P31) | N17 | **keep** |
| 8b | Hard ceiling 30 min for all ages | §6.3 | one ceiling | research §6 said ≈ 15 for ages 6–7; the age band was **dropped without a note** | P31 (one study) | **adapt**: restore an age-band default or record why it was dropped |
| 8c | Limits with no basis: activities_per_cycle 6, cards 10, brain_calls 40, break 120 s, Q&A 5 turns / 20 s | §3.1, §6.3 | defaults | none recorded | none found | **keep**, labelled "untuned default, no source" |
| 9 | Autonomy 0–10 bands (ask ≤ 3 / say + reason 4–7 / inform ≥ 8) | §2.1 | harness enforces the bands | owner decision; thresholds original (D13 "to design") | SS23 (10 levels of decision automation), SS25, SS26 (give a rationale) | **adapt**: anchor to SS23; add "choose from a short list" at 0–1; a rationale at every band |
| 10 | Learner reply grammar; silence is not a yes | §2.1 | yes/no/skip/named/none/unparsed | original; owner 2026-10-22 | SS4 (CALM: skip, cancel, clarify) | **keep** |
| 11 | Per-kind `anyOf` decision schema; echoed epoch | §5 | one schema per session | adopted (Anthropic structured outputs and caching, R2, R3) | — | **keep** |
| 12 | Decide, then speak | §5 | one call returns the decision and its wording | adapted from Bridge (A11), Khanmigo drafting (A3) | SS18 (+76 % preferred; random decisions −97 %), SS5 (a separate prep step) | **adapt**: Bridge slots `evidence` / `strategy` / `intention` instead of a free `note` |
| 13 | Routing by purpose × difficulty; escalation on invalid | §5.1 | rule table | owner request; rules original | SS1, SS2 (RouteLLM learned routers need own preference data), SS3 (FrugalGPT cascade with a scorer) | **keep** rules; record it as a FrugalGPT-style cascade; log (purpose, difficulty, tier, outcome, rating) for a later router |
| 14 | Tier weights 0.25 / 1 / 3 vs 40 calls | §5.1 | fixed | none recorded | SS3 | **keep**; state they are units, not prices |
| 15 | Observation as plain-text sections | §4 | `observe.py` | adopted from Khan Academy (A4) | SS16 (plain text over JSON; +3.4 %), SS5 | **keep** |
| 16 | Records the Brain may write | §7.1 | inside every `decide` | adapted from DeepTutor (A8), Bloom (A15); decay rule original | SS5 (facts extracted after the call, separately) | **adapt**: `learner_note` / `book_note` move to one post-session extraction call |
| 17 | Item status; known after ≥ 2 successes on different days | §6.2 | `item_status.apply` | adapted from Lute (N1/SS10), LingQ (N3/SS11), AnkiMorphs (N7/SS8); the ≥ 2 rule has no record (research §6: ≥ 6 over ≥ 3 days) | SS6 (HLR), SS37 (FSRS), SS36 (BKT) | **adapt**: reconcile or cite; store full timestamps; no BKT now |
| 18 | What is new and its rank | §6.2 | i+1 first, level band, frequency | adapted from AnkiMorphs (SS9), YLE (N19), SUBTLEX-UK (N21) | SS31 (running-record bands, *reported*), SS32 (98 % coverage, adults, *reported*), SS33 | **keep**; optional page-level known-share signal → prefer `read_aloud` |
| 19 | `quiz` with keyword answers | §3.1 | generated questions | adapted from WWC (P3); answerability flaw flagged (N20) but not handled | SS30 (CROWD/PEER, *reported*), SS20, SS21 | **adapt**: question-type slot; answerability check at construction; open answers by `judge` |
| 20 | `teach_items` scoring; `judge` on the fast tier | §3.1 | item_said / cloze (sim ≥ 0.80) / item_used | original; 0.80 none recorded | SS20 (GPT-4 few-shot κ 0.70 vs 0.75), SS21 | **adapt**: `standard` tier + few-shot until measured on the child's labelled answers; mark 0.80 untuned |
| 21 | `learner_questions` Q&A | §3.1, §5.1 | ≤ 5 turns | owner decision (D17) | SS15 (ground answers in human-made content) | **keep**; ground in the page and `book_notes` |
| 22 | Card generation and checks | §7.2 | pass or drop | adapted from anki-llm (N14), Kotoba (N15), SuperMemo (N16), N7, N13 | SS12, SS13 (pass / flag / reject) | **adapt**: `flag` → parent preview with its reason |
| 23 | Practice policy | §6.3, §8 | defaults + ledger | adapted (research §6) | — | **keep** |
| 24 | Silence and stuck handling; interrupt modes | §6.1 | settings | adapted (B9, B8) | SS28 (Rowe ≥ 3 s, *reported*) | **keep** |
| 25 | Praise rules | §6.1 | specific, never "smart" | adopted (P35, P37, P38) | SS27 | **keep**; note `frequent` contradicts P37/P38 |
| 26 | Goals | §6.3 | composable | adapted (N17, N18) | — | **keep** |
| 27 | Decision replay vs default | §9 | stored default; parent judges | adapted from D9 (A10, A12) | SS22 (offline policy evaluation with logged propensities) | **adapt**: randomised default share with propensity logging (owner decision) |
| 28 | Epoch and `Reobserve` | §1, §2.1 | checked before speak, execute, write | adapted from ADR-0013's guard | SS34 (fencing token) | **keep**; name the pattern |
| 29 | Crash resume prompt | §8.5 | "continue from page N?" | ADR-0013 (own) | SS35 (*reported*) | **keep** |
| 30 | Policy text vs enforcement | §6.3 | enforcement never relies on the text | adopted (A7, A5, A1) | SS19 | **keep** |
| 31 | `read_aloud` translate hard sentences, chosen by the Brain | §3.1 | Brain picks | original (D8: no rule exists) | SS9 (unknown count as hardness) | **keep**; pass each sentence's unknown-word count |
| 32 | Filler line at 0.8 s | §5 | static phrase | adopted (Pipecat `pre_actions`, R7) | — | **keep** |

## 3. ADR-0018 learners and privacy (domain mechanisms)

Generic egress plumbing is excluded.

### 3.1 Applicability

The guidance below is a **benchmark for the design, not a ruling on legal duty**:

- **GDPR household exemption.** A parent running Leafi at home most likely falls under it (Art. 2(2)(c)). It does not cover cloud providers who supply the means of processing (Recital 18) (LP36).
- **EU AI Act.** It exempts purely personal non-professional use (LP38).
- **ICO connected-devices standard.** It applies when data reaches the provider (LP31).
- **COPPA.** It binds operators of online services aimed at children (LP42).

### 3.2 Provenance

| # | mechanism | ADR-0018 § | what the ADR does now | current provenance | prior art | recommendation |
|---|---|---|---|---|---|---|
| 1 | Several learners; learner-scoped store | §1, §6.1 | learner / guest / anonymous | original (D14) | LP23, LP24, LP31 | **keep** |
| 2 | Recognition on by default for enrolled learners | §1 | voice on at enrolment | original (owner decision 2) | LP33, LP35 (Art. 9 explicit consent), LP27, LP30, LP28, LP43, LP44 (*reported*), LP39, LP23, LP24 | **adapt**: enrolment is a parent act with a consent record; on-by-default after that may stay |
| 3 | Voice model via sherpa-onnx | §1 | no model named | adopted (sherpa-onnx), model and version unrecorded | LP12 (average enrolment clips; `search(threshold)`, default 0.6), LP13 (per-model licences), LP14 (3D-Speaker), LP15, LP16 (ECAPA, adult EER 0.80 %), LP17 + LP18 (adult models degrade on children; two studies agree) | **adopt** the enrol-by-averaging pattern; record model, licence, version; treat published EERs as adult-only |
| 4 | Accept threshold + top-2 margin per Ear, sibling probe | §1 | measured per Ear | original | LP12 (one threshold, no margin), LP43 (test on own data, monitor drift), LP17, LP18, LP23 (re-train when not recognised) | **keep** (stricter than sherpa-onnx); re-probe on a schedule and after an Ear change; re-enrol when scores drift |
| 5 | Face only after measurement | §1 | no model named | original | LP19 (InsightFace weights non-commercial), LP20 (SFace, Apache-2.0), LP21 (YuNet, MIT), LP22 (face_recognition poor on children) | **adapt**: name YuNet + SFace; rule out InsightFace weights and face_recognition |
| 6 | Confirm when unsure; name path | §1 `identify()` | spoken yes; name ×2; guest | original | LP25 (fallback factor), LP23, LP43 (always a non-biometric path) | **keep** |
| 7 | Identification audio in memory only | §1 | no cloud until confirmed | original | LP40 (COPPA audio exception), LP31 | **keep** |
| 8 | Guests: one week, assignable | §1 | sweep | original (owner 2026-10-22) | LP28, LP31, LP41 | **keep**; put the week in a retention schedule (#21); conflict C5 |
| 9 | Who may consent; PIN to widen egress | §1 | learner or parent consents to media | original (owner decision 4) | LP40, LP34, LP29 | **adapt**: a standing parental opt-in per destination, then the child's per-item yes |
| 10 | `cloud.text` default on | §2 | pseudonymised text sent if all source learners allow | original (owner decision 4, D20) | LP27, LP26, LP40 | **keep** the owner decision, recorded as an explicit parent choice at enrolment; conflict C4 |
| 11 | Egress table by data class | §2 | page/system yes; learner text conditional; names never; media with consent | adapted from ADR-0011 | LP26, LP48 | **keep** |
| 12 | "Local" means an allow-listed model | §2 | `LOCAL_MODELS` | original (owner decision 8) | none | **keep** |
| 13 | magpie route, telemetry off | §2 | `DO_NOT_TRACK=1` | adopted from magpie docs (R16, R17) | LP49 | **keep** |
| 14 | Provenance tags, most-restrictive union, fail closed | §3 | at send time | original | LP47 (records only a data source) | **keep** (a form of taint tracking; no fitting library) |
| 15 | Pseudonymisation by list, stable aliases, age band | §3 | exact list replacement | original | LP1–LP4 (Presidio 2.2.364, MIT, Py 3.10–3.14; no completeness guarantee; only encrypt is reversible), LP5, LP6 (LLM-Guard Vault, English-only, last release 2025-05-19), LP9 (surrogates, 5× fewer utility errors, one study), LP10, LP33 (Art. 4(5)), LP45 (*reported*) | **adapt**: keep the list first; realistic surrogate names; alias table local only |
| 16 | Names in free text not on a list | §3 | accepted residual risk | original (risk acceptance) | LP2, LP6, LP8 (detectors degrade out of distribution, one study) | **adapt**: Presidio + spaCy `en` PERSON as a second detector; measure recall on child transcripts first; mixed Chinese/English names untested |
| 17 | Media local first → ask → remote teacher | §4 | per-item flow | original (owner decision 6) | LP40, LP28 | **keep**; the provider's own retention is outside Leafi's control (C6) |
| 18 | Consent bound to hash, destination, purpose; 5 min; single use | §4 | `consents` row | original | LP47 (ISO/IEC TS 27560 / DPV record, from Kantara) | **adapt**: 27560 field names; one table for media, `cloud.text` and enrolment; keep single use |
| 19 | Media identity check | §4 `prepare()` | no detector named | original | LP21 (YuNet), LP39 | **adopt** YuNet for faces; the person/body detector is still unnamed (gap) |
| 20 | Per-learner forget and export | §1, §3 | every local store | original + ADR-0010 | LP43 (delete derived data; ask third parties), LP23 | **keep**; tell the parent which destinations received the learner's text (from `egress_log`) |
| 21 | Retention | §1 (guests only) | no schedule | none recorded | LP41, LP43, LP28 | **adapt**: one retention table per data class |
| 22 | `egress_log` sha256 | §2 | size, sha256, status | original | LP3 (unsalted hashes can be matched) | **adapt**: HMAC with a per-install secret |
| 23 | Habit snapshot opt-in | ADR-0011 | default false | original (owner 2026-08) | LP27 | **keep** |
| 24 | No identity inferred in the cloud; embeddings stay local | §1 | red line 01 | original | LP43 (on-device templates), LP37 (AI Act bans emotion inference in education institutions) | **keep**; flag for ADR-0017 if encouragement ever reads affect |

### 3.3 Conflicts with guidance

These are stated, not resolved; each owner decision stands until the owner revisits it.

- **C1.** Recognition on by default (owner decision 2), versus:
  - explicit consent for biometric identification (LP35);
  - express consent and a preference for verification over identification (LP43);
  - Quebec's express consent plus advance declaration (LP44, *reported*);
  - ICO's high-privacy and profiling-off defaults (LP27, LP30).
- **C2.** A child can enrol their own voiceprint. Voiceprints are personal information under COPPA (LP39); Google and Alexa have the parent set it up (LP23, LP24).
- **C3.** A confirmed child can consent alone to sending media. COPPA requires separate parental consent for disclosure (LP40); GDPR Art. 8 needs parental consent below 13–16 (LP34).
- **C4.** `cloud.text` defaults to on (owner decision 4), versus ICO's high-privacy defaults and its view that children's data should not usually be shared (LP26, LP27), and COPPA's separate consent to disclose (LP40).
- **C5.** Unconfirmed guests' records are kept for one week, versus data minimisation and treating visiting children with the default service (LP28, LP31).
- **C6.** A child's voice clip goes to a cloud model whose retention Leafi cannot control, versus COPPA's audio exception: delete immediately, no other personal information (LP40).
- **C7.** Pseudonymised text is treated as safe to send, although it remains personal data and Presidio gives no completeness guarantee (LP33, LP45 *reported*, LP2).

## 4. H7.2 trace of the earlier research

Classes:

- **used:** a decision uses the finding; partly used counts here, with the gap noted.
- **rejected:** rejected or deferred with a stated reason.
- **contradicted:** a decision does otherwise without saying why.
- **none:** no decision mentions the finding.

Excluded as not findings: the 2026-10-19 file's §1 project facts, the 2026-10-21 file's §1 owner requirements, and its §9 item 7.

Identifiers in this section:

- **PA** = `2026-10-19-prior-art-book-study.md`; **AL** = `2026-10-21-ai-led-study.md`.
- A1, B12, N4, P27 and similar are each file's own source-row ids.
- **C1–C48** number AL's conclusions in §2–§7, in order. The **D** items are AL's pool D1–D20.

### 4.1 Contradicted silently (8, all in AL)

| finding | what the research found | what the decision does instead | suggestion |
|---|---|---|---|
| D9 | Evaluate the AI policy against the code default **before** trusting it | ADR-0017 §9: Brain primary from the start; the parent judges afterwards | adopt, or state in §9 why trust comes first (§0 item 4) |
| C30 / P14 | Known after ≥ 6 retrievals over ≥ 3 days (2 to > 20 encounters needed) | ADR-0017 §6.2: ≥ 2 successes on different days | adopt, or reject with the reason (e.g. the Anki interval takes over) |
| C35 / P27 | Start a session by rereading a familiar page; reread 2–3× | ADR-0017 §3.1 `read_listen page: current\|next`: an earlier page cannot be chosen | allow a recent page from memory, or reject in §3.1 with a reason |
| C15 / N4 | Implicit promotion from reading evidence | ADR-0017 §6.2 promotes only through retrieval or the Anki interval | reject with the reason the research itself gives (LISTEN caught 23 % of substitutions), or allow `new → learning` only |
| B12 | Explicit marking of which reading was wrong beats implicit (n = 525) | ADR-0009 §5 / ADR-0013 Practice never say which was wrong | reject with ADR-0009's reason (a false "wrong" costs more) in ADR-0017 §6.1 |

(The five rows hold the eight contradicted findings: D9, C30, P14, C35, P27, C15, N4, B12.)

### 4.2 Mentioned by no decision

- **PA (6):**
  - `child-asr-dutch-2026` (read before swapping ASR backends; TD-14 lacks this precondition);
  - `pronounce-assess` / `mimora` (alternatives; harmless);
  - `speechocean762` (replaced by a parent-labelled set without saying why);
  - `picovoice-tts-bench` (Kokoro first audio ≈ 2.9 s vs Piper 1.5 s; ADR-0017 §5.2 will measure anyway);
  - `page-dewarp`;
  - §4 gap 3 (RapidOCR vs qwen3-vl on real pages; never compared, TD-21 open).
- **AL source rows (26):**
  - A2, A3, A11 (decide then speak), A14;
  - B5 (sensitivity setting; insertion and repetition categories; WCPM), B15 (target-text prompting), B16 (ReadAlong highlighting), B19 (children lean on the Chinese; `translate` has no default or limit);
  - N2 (lemma inheritance), N10 (give explanations the error, target and goal), N11, N12 (EVP/EGP), N16 (SuperMemo rules), N18 (streaks, no nagging), N20 (answerability), N22 (95–98 % coverage);
  - P2 (never prompt guessing from pictures), P4, P6, P19 (block new words), P28 (short and frequent), P31 (attention plateaus at 8–9 min; no per-activity minute cap);
  - R4, R5 (`fallbacks` exists in `beta.messages`; AGENTS.md, ADR-0003 and TD-1 still say it does not), R8, R10.
- **AL conclusions and pool (15):**
  - C3 / D8 (no hard-sentence rule);
  - C10 / §9.2 (Parakeet verbatim behaviour; no tech-debt row or prototype);
  - C18 (learner self-marks items);
  - C24 (lemma-first card; recognition and recall from one note);
  - C25;
  - C26 (answerability check);
  - C33 (≥ 3 days a week);
  - C47 / D18 (magpie structured-output probe before relying on it; ADR-0017 §5 routes the decide schema to magpie anyway);
  - C48 / D12 (`fallbacks` doc fix);
  - §9.1 (no study of a Chinese-L1 child reading aloud; bears on P11);
  - §9.5;
  - §9.6 (AnkiConnect review-count actions unverified; the menu's `review_anki` depends on them).

Most important by impact:

1. D9 (§4.1).
2. C30 / P14.
3. C35 / P27.
4. C10 / C12 / D5 with no tech-debt row, while `practise_errors` keeps consuming false candidates from the session-11 defect.
5. C26 / N20 answerability.
6. C47 magpie probe.
7. P31 practice-block cap.
8. A11 decide-then-speak (adopt Bridge slots or reject with a latency reason).
9. §9.6 AnkiConnect probe.
10. R5 / D12 documentation fix.

### 4.3 Gaps in the decision records

- **ADR-0017 header vs body.** The header claims pool items D1–D5, D9, D11, D13 and D15–D19. The body also implements D6 (§6.2) and D7 (§7.2) without naming them. D8 and D12 are claimed by no ADR.
- **Plan Decision log.** `docs/plans/active/2026-10-19-leafi-book-study.md` stops at 2026-10-20, with no rows for ADR-0016, ADR-0017 or ADR-0018.
- **Tech debt.** `docs/plans/tech-debt.md` has no entries from the 2026-10-21 research: session-11 alignment, the D12 doc fix, the magpie probe.
- **Partly used findings worth finishing:**
  - A4: prerequisites and 24 h same-skill chat are not in the observation.
  - B4 / P1 / C2: no "read again" step in `default_spec`.
  - C32: no practice-block cap; no age scaling although `birth_year` exists.
  - D7: answerability check dropped.
  - D19: memory pushed in the observation instead of a `recall_learning` tool, with no note.
  - qwen3-vl: ADR-0018 §4 skips the local VLM second opinion before asking consent.

## 5. Open questions and gaps

**Not verified:**

- Chen & Mostow 2011 (the off-task rule wording).
- Rowe 1986 full text.
- The exact Pause-Prompt-Praise pause rule.
- The Sheridan–Verplank level wording (restatements differ; check SS23 before quoting).
- The WWC dialogic-reading PDF and the EDPB pseudonymisation guidelines' final text (neither machine-readable).
- Licences of the pyannote, DeepFace and individual sherpa-onnx speaker model assets.
- NeMo Curator PII (docs 404).

**Unmeasured, and needed before several recommendations can be accepted:**

- Leafi's miscue detection and false-alarm rates.
- Whether Parakeet keeps repetitions and fragments.
- The 1.2 s sentence pause.
- Speaker-embedding scores on the household's children.
- Presidio PERSON recall on child transcripts.
- Fast-tier `judge` agreement.

**Governance.** Every ADR change above is a design change and needs codex review before code (AGENTS.md → Verification). C1–C7 and the §9 randomised share need owner decisions.

## 6. Sources

All rows checked 2026-10-22. "Undated" = an undated living page or a file on a default branch.

### 6.1 Reading algorithm (RA)

| id | tier | title / url | source-date | checked | supports |
|---|---|---|---|---|---|
| RA1 | T2 | Mostow, "Why and how our automated reading tutor listens" (ISADEPT 2012) — https://www.cs.cmu.edu/~listen/pdfs/2012-05-05%20ISADEPT2012%20keynote%20final.pdf | 2012 | 2026-10-22 | MultiMatch; regressions as reading; 2 s + 2 s; false alarms 4 % → < 1 %, 23 % detection; ~17 % insertions; dialect; distracters |
| RA2 | T2 | Li & Mostow, real-time tracking accuracy (FLAIRS 2012) — https://www.cs.cmu.edu/~listen/pdfs/FLAIRS2012%20Real-time%20Tracking%20accuracy.pdf | 2012 | 2026-10-22 | 0.2 s lag 58 → 70 %; off-task 17.6 % |
| RA3 | T2 | Banerjee, Beck & Mostow, predicting oral reading miscues (Eurospeech 2003) — https://www.isca-archive.org/eurospeech_2003/banerjee03_eurospeech.pdf | 2003 | 2026-10-22 | ignoring 36 function words halves false alarms |
| RA4 | T3 | ReadAlongs/Studio README — https://github.com/ReadAlongs/Studio | © 2019–2025 | 2026-10-22 | SoundSwallower aligner; MIT |
| RA5 | T1 | Microsoft, Practice words with Reading Coach — https://support.microsoft.com/en-us/education/learning-accelerators/practice-words-with-reading-coach | undated | 2026-10-22 | model + practise; no count or mastery rule |
| RA6 | T1 | Microsoft, Getting started with Reading Progress — https://support.microsoft.com/en-US/education/getting-started-with-reading-progress-in-teams | undated | 2026-10-22 | miscue categories incl. self-correction, repetition; sensitivity |
| RA7 | T1 | Microsoft Learn, pronunciation assessment — https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-pronunciation-assessment | 2025-11-21 (updated 2026-07-03) | 2026-10-22 | `EnableMiscue`; not in continuous mode |
| RA8 | T1 | RapidFuzz `fuzz` docs — https://rapidfuzz.github.io/RapidFuzz/Usage/fuzz.html | 3.14.6 | 2026-10-22 | `ratio` = normalised Indel similarity |
| RA9 | T1/T3 | sherpa hotwords docs and `offline-recognizer-transducer-nemo-impl.h` — https://raw.githubusercontent.com/k2-fsa/sherpa-onnx/master/sherpa-onnx/csrc/offline-recognizer-transducer-nemo-impl.h | undated (master) | 2026-10-22 | NeMo transducer hotwords in `modified_beam_search` |
| RA10 | T2 | Settles & Meeder, half-life regression (ACL 2016) — https://aclanthology.org/P16-1174/ | 2016 | 2026-10-22 | learned half-lives; > 45 % error reduction |
| RA11 | T2 | Henkel et al., LLM grading of reading-comprehension answers — https://arxiv.org/abs/2310.18373v2 | 2023 (v2) | 2026-10-22 | GPT-4 QWK 0.92 (one study, Ghana) |
| RA12 | T2 | ASAG with feedback (via search) — https://arxiv.org/pdf/2407.12818 | 2024 | 2026-10-22 | keyword matching as the early baseline |
| RA13 | T1 | num2words README + PyPI — https://pypi.org/pypi/num2words/json | 0.5.14, 2024-12-17 | 2026-10-22 | cardinal, ordinal, year; LGPL |
| RA14 | T4 | Louisiana DOE running-record handout (after Clay 1993) — https://doe.louisiana.gov/docs/default-source/louisiana-teacher-leaders/fi4-handout-assessment-data-collection-rti-running-record-info.pdf | undated (PDF 2006-05) | 2026-10-22 | error and non-error conventions; skipped line; SC rate (*reported*) |
| RA15 | T3 | aeneas README — https://raw.githubusercontent.com/readbeyond/aeneas/master/README.md | v1.7.3, 2017-03-15 | 2026-10-22 | audio must match text; AGPL |
| RA16 | T2 | Dixon, on-line time warping (IJCAI 2005, via search) — https://webspace.eecs.qmul.ac.uk/s.e.dixon/pub/2005/ijcai05.pdf | 2005 | 2026-10-22 | band around a forward path |
| RA17 | T1 | Biopython pairwise alignment — https://biopython.org/docs/latest/Tutorial/chapter_pairwise.html | 1.88 | 2026-10-22 | affine and end-gap scores |
| RA18 | T3 | whisperX README — https://raw.githubusercontent.com/m-bain/whisperX/main/README.md | undated | 2026-10-22 | aligns its own transcript |
| RA19 | T1 | NeMo text normalisation — https://docs.nvidia.com/nemo-framework/user-guide/25.09/nemotoolkit/nlp/text_normalization/wfst/wfst_text_normalization.html | 25.09 | 2026-10-22 | Pynini WFST |
| RA20 | T1 | Montreal Forced Aligner — https://montreal-forced-aligner.readthedocs.io/en/latest/ | v3.4 | 2026-10-22 | exists |
| RA21 | T3 | Gentle README — https://raw.githubusercontent.com/lowerquality/gentle/master/README.md | undated | 2026-10-22 | lenient Kaldi aligner |
| RA22 | T2 | Molenaar et al., oral reading accuracy (Interspeech 2023) — https://arxiv.org/abs/2306.03444 | 2023-06-06 | 2026-10-22 | MCC .63; no code located |
| RA23 | T3 | Local measurement: `rapidfuzz.fuzz.ratio` 3.14.6 in `.venv` on house/horse, there/three, though/through, walked/walk | 2026-10-22 | 2026-10-22 | 0.80, 0.80, 0.92, 0.80 |

### 6.2 AI-led session (SS)

| id | tier | title / url | source-date | checked | supports |
|---|---|---|---|---|---|
| SS1 | T2 | Ong et al., RouteLLM — https://arxiv.org/abs/2406.18665v4 | v4 2025-02 | 2026-10-22 | learned routing, > 2× cost cut |
| SS2 | T3 | lm-sys/RouteLLM README — https://github.com/lm-sys/RouteLLM | undated | 2026-10-22 | calibration on own traffic |
| SS3 | T2 | Chen, Zaharia, Zou, FrugalGPT — https://arxiv.org/abs/2305.05176 | 2023-05-09 | 2026-10-22 | cascade with a scorer; price spread |
| SS4 | T1 | Rasa Pro command generator — https://rasa.com/docs/pro/customize/command-generator.md | undated | 2026-10-22 | fixed command set |
| SS5 | T4 (vendor) | Duolingo, AI and Video Call — https://blog.duolingo.com/ai-and-video-call | 2025-04-22 | 2026-10-22 | separate prep step; facts extracted after the call |
| SS6 | T2 | Settles & Meeder 2016 (= RA10) — https://aclanthology.org/P16-1174/ | 2016-08 | 2026-10-22 | HLR |
| SS7 | T4 (vendor) | Duolingo Birdbrain — https://blog.duolingo.com/learning-how-to-help-you-learn-introducing-birdbrain | 2020-10-07 | 2026-10-22 | difficulty prediction |
| SS8 | T1 | AnkiMorphs glossary — https://mortii.github.io/anki-morphs/user_guide/glossary.html | undated | 2026-10-22 | known by interval |
| SS9 | T1 | AnkiMorphs recalc score — https://mortii.github.io/anki-morphs/user_guide/usage/recalc.html | undated | 2026-10-22 | score = 10⁶ × unknowns + … |
| SS10 | T1 | Lute v3 `term.py` — https://raw.githubusercontent.com/LuteOrg/lute-v3/master/lute/models/term.py | undated | 2026-10-22 | statuses 0, 1–5, 98, 99 |
| SS11 | T1 | LingQ status help — https://lingq-support.groovehq.com/help/can-you-explain-a-lingqs-status | 2020-10-06 | 2026-10-22 | statuses |
| SS12 | T3 | anki-llm prompt reference — https://anki-llm.raine.dev/prompt-reference/ | undated | 2026-10-22 | field_map; pass / flag / reject |
| SS13 | T3 | anki-llm README — https://raw.githubusercontent.com/raine/anki-llm/main/README.md | undated | 2026-10-22 | candidates, duplicates |
| SS14 | T4 (vendor) | Khan Academy, 7-step prompting — https://blog.khanacademy.org/khan-academys-7-step-approach-to-prompt-engineering-for-khanmigo | 2023-10-23 (upd. 2025-03-21) | 2026-10-22 | persona testing |
| SS15 | T4 (vendor) | Khanmigo math updates — https://blog.khanacademy.org/khanmigo-math-computation-and-tutoring-updates/ | 2025-02-26 | 2026-10-22 | private drafting; grounding |
| SS16 | T4 (vendor, A/B-tested) | Khan Academy, building a better AI tutor — https://blog.khanacademy.org/?p=21314 | 2026-05-06 | 2026-10-22 | plain text over JSON; +3.4 % |
| SS17 | T2 | Puech et al., StratL — https://arxiv.org/html/2410.03781v2 | v2 2025-03-18 | 2026-10-22 | code graph picks; 17 students, GPT-4o |
| SS18 | T2 | Wang et al., Bridge (NAACL 2024) — https://arxiv.org/abs/2310.10648 | v3 2024-04-06 | 2026-10-22 | +76 %; −97 % with random decisions |
| SS19 | T2 | LearnLM tech report — https://arxiv.org/abs/2412.16429 | v3 2025-08-22 | 2026-10-22 | pedagogical instruction following |
| SS20 | T2 | Henkel et al., LLMs marking K-12 short answers — https://arxiv.org/abs/2405.02985 | 2024-05-05 | 2026-10-22 | GPT-4 few-shot κ 0.70 vs human 0.75 |
| SS21 | T2 | Henkel et al. (= RA11) — https://arxiv.org/abs/2310.18373 | v2 2024-05-05 | 2026-10-22 | QWK 0.92 |
| SS22 | T2 | Mandel et al., offline policy evaluation (AAMAS 2014, via search) — https://grail.cs.washington.edu/wp-content/uploads/2015/08/mandel2014ope.pdf | 2014 | 2026-10-22 | importance sampling; 2,000 students |
| SS23 | T2 | Parasuraman, Sheridan, Wickens, levels of automation (IEEE SMC-A 30(3)) — https://vufind.lboro.ac.uk/PrimoRecord/cdi_ieee_primary_844354 | 2000 | 2026-10-22 | 10 levels (record only; wording via SS24) |
| SS24 | T4 | Summary of SS23 — https://andrewclark.super.site/all-media/a-model-for-types-and-levels-of-human-interaction-with-automation | undated | 2026-10-22 | level wording (*reported*) |
| SS25 | T2 | Corbalan, Kester, van Merriënboer, shared control (2008) — https://research.ou.nl/en/publications/selecting-learning-tasks-effects-of-adaptation-and-shared-control/ | 2008 | 2026-10-22 | system preselects, learner picks (abstract) |
| SS26 | T2 | Reeve & Cheon, autonomy-supportive teaching — https://selfdeterminationtheory.org/wp-content/uploads/2021/05/2021_ReeveCheon_AutonomySupportive.pdf | 2021 | 2026-10-22 | rationale-giving (via search) |
| SS27 | T2 | Mueller & Dweck 1998 — https://www.columbia.edu/cu/psychology/courses/3615/Readings/Mueller_Dweck.pdf | 1998 | 2026-10-22 | intelligence praise harms persistence |
| SS28 | T4 | Structural Learning, wait time (Rowe) — https://www.structural-learning.com/research-briefings/wait-time-three-seconds | undated | 2026-10-22 | ≥ 3 s (*reported*) |
| SS29 | T1 | cmi5 specification (Quartz) — https://raw.githubusercontent.com/AICC/CMI-5_Spec_Current/quartz/cmi5_spec.md | 2016-06-01 | 2026-10-22 | defined verbs |
| SS30 | T1/T4 | WWC dialogic reading report — https://ies.ed.gov/ncee/WWC/Docs/InterventionReports/wwc_dialogic_reading_042710.pdf | 2010-04 | 2026-10-22 | PEER/CROWD (*reported*; PDF not readable) |
| SS31 | T4 | Reading A-Z, scoring a running record — https://www.readinga-z.com/guided/runrec/scoring.html | undated | 2026-10-22 | 95 / 90–94 / < 90 % (*reported*) |
| SS32 | T4 | Hu & Nation 2000 replication abstract — https://aila2021.dryfta.com/program/abstract-archive/abstract/public/416/unknown-vocabulary-density-reading-comprehension-and-the-98-coverage-figure-replicating-hu-nation-2000 | 2021 | 2026-10-22 | 98 % coverage, adults (*reported*) |
| SS33 | T4 | Vanderbilt bibliography, Krashen 1982 — https://my.vanderbilt.edu/l2studies/?p=28 | undated | 2026-10-22 | i+1 loosely defined (*reported*) |
| SS34 | T4 | Kleppmann, fencing tokens — https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html | 2016-02-08 | 2026-10-22 | pattern name |
| SS35 | T4 | Amazon help, Kindle furthest page read — https://digprjsurvey.amazon.com/csad/help/node/GDNJ68Z4KQE9VRRT | undated | 2026-10-22 | (*reported*) |
| SS36 | T2 | Badrinath, Wang, Pardos, pyBKT (EDM 2021) — https://arxiv.org/abs/2105.00385 | 2021-05 | 2026-10-22 | BKT alternative |
| SS37 | T1 | open-spaced-repetition/fsrs4anki — https://github.com/open-spaced-repetition/fsrs4anki | undated | 2026-10-22 | FSRS in Anki ≥ 23.10 |
| SS38 | T4 | Reading Recovery, teaching for processing — https://readingrecovery.org/?p=12752 | undated | 2026-10-22 | self-monitoring (*reported*) |

### 6.3 Learners and privacy (LP)

| id | tier | title / url | source-date | checked | supports |
|---|---|---|---|---|---|
| LP1 | T1 | presidio-analyzer on PyPI — https://pypi.org/project/presidio-analyzer/ | 2.2.364, 2026-07-22 | 2026-10-22 | MIT; Py 3.10–3.14 |
| LP2 | T1 | Presidio home — https://presidio.dataprivacystack.org/ | undated | 2026-10-22 | no completeness guarantee; NLP engines |
| LP3 | T1 | Presidio anonymizer — https://presidio.dataprivacystack.org/anonymizer/ | undated | 2026-10-22 | operators; random salt since 2.2.361 |
| LP4 | T1 | Presidio, adding recognizers — https://presidio.dataprivacystack.org/analyzer/adding_recognizers/ | undated | 2026-10-22 | deny lists |
| LP5 | T1 | llm-guard on PyPI — https://pypi.org/project/llm-guard/ | 0.3.16, 2025-05-19 | 2026-10-22 | MIT; Py 3.10–3.12 |
| LP6 | T1 | LLM-Guard Anonymize — https://protectai.github.io/llm-guard/input_scanners/anonymize/ | undated | 2026-10-22 | Vault; English-only detection |
| LP7 | T1 | Philterd/philter — https://github.com/Philterd/philter | undated | 2026-10-22 | Java; not a fit |
| LP8 | T2 | Zafar & Nowaczyk, robustness risks in PII detection — https://arxiv.org/abs/2609.03464 | 2026-09-03 | 2026-10-22 | detectors degrade out of distribution (one study) |
| LP9 | T2 | Serenari & Lee, LOPSIDED — https://arxiv.org/abs/2510.27016 | 2025-10-30 | 2026-10-22 | surrogates; 5× fewer utility errors (one study) |
| LP10 | T2 | Hou et al., pseudonymisation for cloud LLMs — https://arxiv.org/abs/2502.15233 | 2025-02-21 | 2026-10-22 | utility kept |
| LP11 | T1 | sherpa speaker identification docs — https://k2-fsa.github.io/sherpa/onnx/speaker-identification/index.html | undated | 2026-10-22 | feature exists |
| LP12 | T3 | sherpa-onnx `speaker-identification.py` — https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/speaker-identification.py | undated | 2026-10-22 | averaged enrolment; threshold 0.6 |
| LP13 | T1 | sherpa-onnx speaker model release — https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models | "08 Dec" (year not shown) | 2026-10-22 | per-model licences |
| LP14 | T1 | modelscope/3D-Speaker — https://github.com/modelscope/3D-Speaker | undated | 2026-10-22 | Apache-2.0; EERs; Mandarin data |
| LP15 | T1 | wenet-e2e/wespeaker — https://github.com/wenet-e2e/wespeaker | undated | 2026-10-22 | model licences not stated |
| LP16 | T1 | speechbrain/spkrec-ecapa-voxceleb — https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb | 2021-03-05 (as stated) | 2026-10-22 | EER 0.80 % adults |
| LP17 | T2 | Zheng et al., age-agnostic speaker verification — https://arxiv.org/abs/2508.01637 | 2025-08-03 | 2026-10-22 | adult models suboptimal on children |
| LP18 | T2 | FT-Boosted SV (classroom speech) — https://arxiv.org/abs/2505.20222 | 2025-05-26 | 2026-10-22 | child fine-tuning lowers EER |
| LP19 | T1 | deepinsight/insightface — https://github.com/deepinsight/insightface | 2025-11-24 (licence notice) | 2026-10-22 | weights non-commercial |
| LP20 | T1 | OpenCV zoo SFace — https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface | undated | 2026-10-22 | Apache-2.0 |
| LP21 | T1 | OpenCV zoo YuNet — https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet | undated | 2026-10-22 | MIT; faces ~10–300 px |
| LP22 | T1 | ageitgey/face_recognition — https://github.com/ageitgey/face_recognition | undated | 2026-10-22 | poor on children; Windows unsupported |
| LP23 | T1 | Google, child use of Google Assistant — https://support.google.com/families/answer/9071584?hl=en | undated | 2026-10-22 | parent sets up Voice Match; re-train |
| LP24 | T1 (snippet; page 503) | Amazon, Alexa Voice ID for a child — https://www.amazon.com/gp/help/customer/display.html?nodeId=G3UFSS8YLN4P59KD | undated | 2026-10-22 | parent sets it up; ≤ 4 children |
| LP25 | T1 | Alexa voice-forward consent tutorial — https://developer.amazon.com/en-US/docs/alexa/custom-skills/tutorial-test-voice-forward-consent.html | 2022-03-23 | 2026-10-22 | unrecognised voice → passcode |
| LP26 | T1 | ICO Age Appropriate Design Code — https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/childrens-information/childrens-code-guidance-and-resources/age-appropriate-design-a-code-of-practice-for-online-services/ | undated | 2026-10-22 | 15 standards; data sharing |
| LP27 | T1 | ICO std 7 default settings (same base + `7-default-settings/`) | undated | 2026-10-22 | high privacy by default |
| LP28 | T1 | ICO std 8 data minimisation (same base + `8-data-minimisation/`) | undated | 2026-10-22 | minimum data; separate choices |
| LP29 | T1 | ICO std 11 parental controls (same base + `11-parental-controls/`) | undated | 2026-10-22 | tell the child when monitored |
| LP30 | T1 | ICO std 12 profiling (same base + `12-profiling/`) | undated | 2026-10-22 | profiling off by default |
| LP31 | T1 | ICO std 14 connected toys and devices (same base + `14-connected-toys-and-devices/`) | undated | 2026-10-22 | scope; listening mode; visitors |
| LP32 | T1 | ICO biometric recognition guidance — https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/lawful-basis/biometric-data-guidance-biometric-recognition/ | undated ("under review") | 2026-10-22 | headings only |
| LP33 | T1 | GDPR Art. 4 — https://gdpr-info.eu/art-4-gdpr/ | undated | 2026-10-22 | pseudonymisation; biometric data |
| LP34 | T1 | GDPR Art. 8 — https://gdpr-info.eu/art-8-gdpr/ | undated | 2026-10-22 | parental consent below 13–16 |
| LP35 | T1 | GDPR Art. 9 — https://gdpr-info.eu/art-9-gdpr/ | undated | 2026-10-22 | special category; explicit consent |
| LP36 | T1 | GDPR Art. 2 and Recital 18 — https://gdpr-info.eu/art-2-gdpr/ | undated | 2026-10-22 | household exemption; providers covered |
| LP37 | T1 | EU AI Act Art. 5 — https://artificialintelligenceact.eu/article/5/ | effective 2025-02-02 | 2026-10-22 | emotion inference in education banned |
| LP38 | T1 | EU AI Act Art. 2 — https://artificialintelligenceact.eu/article/2/ | undated | 2026-10-22 | personal use exempt |
| LP39 | T1 | 16 CFR 312.2 — https://www.law.cornell.edu/cfr/text/16/312.2 | undated | 2026-10-22 | voiceprints are personal information |
| LP40 | T1 | 16 CFR 312.5 — https://www.law.cornell.edu/cfr/text/16/312.5 | undated | 2026-10-22 | separate consent to disclose; audio exception |
| LP41 | T1 | 16 CFR 312.10 — https://www.law.cornell.edu/cfr/text/16/312.10 | undated | 2026-10-22 | written retention policy |
| LP42 | T1 | FTC COPPA Rule page — https://www.ftc.gov/legal-library/browse/rules/childrens-online-privacy-protection-rule-coppa | Federal Register 2025-04-22 | 2026-10-22 | amended rule; applies to operators |
| LP43 | T1 | OPC Canada, biometrics guidance for businesses — https://www.priv.gc.ca/en/privacy-topics/health-genetic-and-other-body-information/biometrics/gd_bio_org-final/ | 2025 | 2026-10-22 | express consent; verification over identification; on-device; alternatives; drift |
| LP44 | T4 | Langlois, Quebec biometrics summary — https://langlois.ca/en/insights/use-of-biometric-data-quebecs-privacy-commissioner-keeps-the-bar-high/ | undated | 2026-10-22 | express consent; declaration (*reported*) |
| LP45 | T1 page / T4 substance | EDPB Guidelines 01/2025 on pseudonymisation — https://www.edpb.europa.eu/our-work-tools/documents/public-consultations/2025/guidelines-012025-pseudonymisation_en | consultation 2025-01-17 to 2025-03-14 | 2026-10-22 | still personal data (*reported*) |
| LP46 | T1 (not read) | ENISA pseudonymisation techniques — https://www.enisa.europa.eu/publications/pseudonymisation-techniques-and-best-practices | 2019-12-03 | 2026-10-22 | exists |
| LP47 | T1 | W3C DPV, ISO/IEC TS 27560 consent records — https://w3c-cg.github.io/dpv/guides/consent-27560 | undated | 2026-10-22 | consent record fields and statuses |
| LP48 | T1 | NIST Privacy Framework — https://www.nist.gov/privacy-framework | undated | 2026-10-22 | v1.0; v1.1 draft |
| LP49 | — | Research 2026-10-21 rows R16, R17 (magpie docs) | undated | 2026-10-22 | telemetry; `DO_NOT_TRACK` |

### 6.4 Research-file rows relied on

- `2026-10-21-ai-led-study.md`:
  - A1, A3–A5, A7–A13, A15, A16;
  - B1–B6, B8, B9, B11–B13, B15, B16, B18;
  - N1, N3, N7, N9, N13–N17, N19–N21;
  - P3, P9, P16–P18, P23, P25, P27, P31, P32, P35, P37, P38;
  - R2, R3, R5–R7, R9, R15–R17;
  - §1 owner decisions;
  - §3.3, §6, §9;
  - pool D1–D20.
- `2026-10-19-prior-art-book-study.md`: `reading-coach-faq`, `project-listen`, `openpronounce`, `sherpa-onnx-hotwords`, `lute-v3`, §1 wheel list, D5, D6, D9.
- Full traces of all 227 findings (including every *used* row) were produced for this file. Only the contradicted and unmentioned rows are listed in §4, because those are what H7.2 asks to resolve.
