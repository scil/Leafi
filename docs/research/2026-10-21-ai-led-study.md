# AI-led study: tutors, reading cycle, new content, practice policy, runtime (reference collection)

Checked: 2026-10-21. Method: `tiered-research` (T1 = the owner's own docs, T2 = empirical studies with scope, T3 = exemplars verified by direct access, T4 = secondary; a single T2 or T4 row never decides). Five parallel searches; every claim below traces to a row of §8. Rows marked *(abstract)* or *(reported)* were not read in full.

Decision it serves: replacing the hard-coded study flow (ADR-0013 session rules: practice at every sentence end, a spoken line after every sentence) with an AI-led study session in which the Brain chooses the activity and code enforces privacy, timing and limits. The ADR that follows must be reviewed by codex before code (AGENTS.md → Verification).

## 1. Owner's requirements (2026-10-21, verbatim structure, translated)

Task types:
1. Anki review.
2. Physical-book reading tutoring: a **cycle = reading + practice**; several cycles per session.
   - Reading modes: (a) the learner reads, Leafi listens; (b) the learner points at content, Leafi reads it (optional: translate every sentence, or only hard sentences).
   - Practice types: (a) errors found during reading — so **no correction during reading**; (b) new words, phrases, word combinations, sentences, grammar; (c) comprehension questions; (d) practised content becomes Anki cards.
3. Practice has an amount, duration, timing, rhythm and method.

Daily goals per user, e.g. finish today's Anki reviews.

Extra work a physical book brings: identify the content (book, page, paragraph; page turns by OCR or by asking) and keep content and records; decide what is "new"; detect reading errors, which needs word confidence and an alignment that maps speech to the right sentence whatever the cause of skips and rereads (today: *when the start is lost, later sentences get forced onto the first sentence*, session 11).

Principle: **the AI steers the learning process, not code**; tuned and accumulated through practice.

Additions (2026-10-21, second message):
1. Leafi (AI + code) and the user:
   - **Learner autonomy** `0–10`: 0 = Leafi decides goals, content and pace; 10 = the user decides everything and Leafi asks; in between, Leafi negotiates its preferred goal, method and pace with the user's wishes.
   - **Several users**: recognise who is studying; keep each user's data apart.
2. AI and code inside Leafi:
   - May the code be called the **harness**?
   - Code keeps the data and metrics; the AI can store or update the data and metrics it touches at run time — e.g. per practice: method, duration, dialogue, outcome assessment, model and prompt used.
3. Reading cycle: interruption timing, handling of the learner's silence, and encouragement are **settings**; after reading, besides practice, a **learner-asks Q&A** step.
4. Model access: besides Claude and Ollama, support **magpie** (https://usemagpie.ai/) to switch models freely.

Owner decisions (2026-10-21, third message; they supersede the matching proposals above and in §8):
1. **Autonomy is Leafi's, not the learner's**: `0–10`, the higher, the harder Leafi argues for its own default goal, method and pace; at 10 Leafi is fully autonomous and the learner follows.
2. **Recognising learners by voice and face is on by default**, unless the learner explicitly forbids it or turns it off in settings.
3. The harness **stores the learning content** itself (pages, stories, topics, words and difficulties), so later practice can reuse it: familiar topics and stories, recent difficulties.
4. **Whether learner content may go to the cloud is a learner setting, default allowed** — the earlier privacy policy was too strict.
5. magpie: **any provider**; **telemetry off**; magpie **may store data locally**.

Owner decisions (2026-10-21, fourth message):
6. **Audio and images are processed locally first.** When local processing fails or is unsure, Leafi asks the learner to help or confirm; it may also ask whether it may consult a **remote teacher** (send that audio clip or image to a cloud model) — per case, with the learner's yes.
7. **Learner identity sent to the cloud is altered moderately** (name, age, …) as long as the result is unaffected.

## 2. Who steers: what LLM tutors actually do

No verified system lets the LLM run a whole session unsupervised. The designs sit on a spectrum (rows A1–A14):

| Where the boundary sits | Systems | Evidence |
|---|---|---|
| Prompt only (pedagogy in the system prompt, no code state) | ChatGPT study mode, Claude learning mode, Mr. Ranedeer | OpenAI says prompt-level pedagogy is fast to iterate but inconsistent (A5); Anthropic's own docs say a style is advisory and must-happen behaviour belongs in code (A7) |
| LLM loops over tools; code owns gates and the tool set per context | DeepTutor (mastery gate, tools mounted by context, `ask_user`), Pipecat Flows (tools per node, LLM picks the edge) | A8, A13 |
| LLM classifies or proposes; code decides | StratL (LLM labels learner state → code graph → intent prompt chunks), Bridge (decide error → strategy → intention before speaking), Khanmigo (router decides when the math agent runs) | A10, A11, A4 |
| Code decides; LLM only words it | ES-LLMs, OATutor (BKT), IntelliCode | A12, A9 |

What the evidence says about the boundary:
- Two studies favour code or a graph choosing the teaching move over letting the LLM pick (StratL's ablation, GPT-4o, 17 teenagers, maths; ES-LLMs, simulation + 6 experts, abstract). Neither involves children or reading aloud; both are small. LearnLM (expert role-players, text) shows a general model follows pedagogy written as hard and soft constraints in the system instruction (A1). The disagreement is about what was measured (strategy fidelity vs reply preference), not a contradiction.
- "Decide, then speak" as an explicit step improves replies (Bridge: expert decisions given to GPT-4 → 76 % more preferred, A11; Khanmigo drafts the student's possible paths privately, A3).
- What learner state to pass per turn has the best evidence from Khan Academy's A/B tests (vendor-reported, A4): a summary of recent attempts, unmastered prerequisites, and the last 24 h of same-skill chat as plain text rather than JSON.

**Synthesis for Leafi (inference):** the owner's "AI steers" fits the middle of the spectrum. The Brain chooses the next activity and its content **from a menu code computes** (allowed activities, a default, limits), and writes the words; code executes each activity and owns everything inside it that is measured or safety-relevant. This is CALM's "LLM issues commands, flows execute" (R6) and Pipecat's "tools per node, LLM chooses the edge" (A13). Given the two studies above, the AI-led policy should be evaluated against the code default before it is trusted (§7 D9).

## 3. The reading cycle

### 3.1 When feedback happens

| Product / study | Behaviour | Row |
|---|---|---|
| Microsoft Reading Coach | Reads the whole passage, then a results page, then **Word Practice on up to 5 words** chosen by the system from substitutions, omissions, insertions, mispronunciations, repetitions; each word until mastered; optional "Read again"; sessions up to 10 min; on-device speech. No mid-reading correction is documented. | B1–B4 |
| Microsoft Reading Progress | Pronunciation sensitivity Less/More per assignment; error taxonomy omission, insertion, mispronunciation, repetition, self-correction; WCPM. | B5 |
| Project LISTEN | One sentence shown at a time; intervenes only at sentence end or after silence: 2 s → backchannel, 2 s more → prompt; a skipped word gets a non-verbal cue and the child keeps the turn; rereads the sentence aloud when it was not fluent. Prefers false acceptance: false rejection ≈ 4 % → < 1 %. | B9 |
| Amira / EPS Reading Assistant | ≥ 3 s "productive struggle" before help (mean ≈ 6 s); help frequency configurable; ≈ one intervention per page *(reported)*. | B7, B8 |
| Ello | Lenient on purpose; children get discouraged. | B10 |
| Google Read Along | Help on tap (say the word, then sound it out); with two languages it translates each line after it is read. | B6 |

Studies (rows P7–P13, B12–B18): correcting beats not correcting; active repetition of the corrected word or sentence beats hearing it; explicit error marking between two readings beats implicit feedback for word accuracy (Bai 2022, n = 525, Dutch grade 1). The **timing split runs along scope lines**: immediate correction wins for isolated sight words with special-needs samples; delayed attention to errors raises self-correction in connected text with typical 6-year-olds (single small study); interruption is argued to weaken self-monitoring. L2 feedback studies are split too (immediate helps low-proficiency Chinese-L1 learners in one study, P11).

**Synthesis:** a child reading a real book is closest to "connected text, typical reader": do not interrupt within a sentence; collect candidates; practise **after the reading cycle** with a short list (Microsoft's 5) and active repetition; optionally reread. This matches the owner's requirement 2.2(a) and the Reading Coach loop the 2026-10-19 research recorded. Silence (stuck) is a separate trigger: wait ≥ 3–4 s before offering help (B8, B9).

### 3.2 Leafi-reads mode (the learner points, Leafi reads)

Read Along translates every line after it is read; Immersive Reader translates a word or the whole text; reading pens scan and read a line, and one review reports children leaning on the Chinese (B19–B21, T4). **No product documents a rule for "hard sentences only"**; the only documented "hard" signal is the learner's own struggle (Microsoft). Leafi would need its own rule: unknown-word density, word level (§4), sentence length, the learner's Difficulties. ReadAlong Studio (offline forced alignment of known text) fits highlighting while Leafi reads (B16).

### 3.3 Tracking and alignment (the session-11 defect)

Techniques from Project LISTEN (B9, B11) and later work (B13–B15):
- **Restrict the hypothesis space** to the current sentence ± one sentence, but model real reading: repeat, skip, restart, jump back, jump forward, each with a probability.
- **MultiMatch-style DP**: mismatch cost from spelling and sound distance; a jump penalty for any move other than stay or +1; tuned to prefer one isolated mismatch over jumping away and back. Rereads are normal reading, not insertions.
- **Track realistically, display and credit conservatively**: internally follow the reader; credit only the earliest uncredited word (skipping at most one).
- **Off-task rule**: more than 2 consecutive heard words without two successive matches = off-task speech; pause tracking (≈ 18 % of child speech).
- **Confidence only after tracking settles** ("tracking trips up scoring"); bias towards acceptance; a single low-confidence word is "maybe", not a correction trigger. Detection is poor even in research systems (LISTEN caught 23 % of substitutions; Whisper precision 0.52 on Dutch children), so a candidate must not be presented as "wrong".
- **Partial words**: phonetic truncations catch false starts.
- **Verbatim risk**: ASR that cleans up disfluencies breaks comparison against the text (B15). Whether Parakeet TDT keeps repetitions and fragments is unmeasured.
- **Latency**: committing the position 0.2 s behind the audio raised exact tracking accuracy from 58 % to 70 % (B11).

Mapping to ADR-0013 (inference): rule 1's window (`hi = pcur + ceil(1.5·m) + 8`) cannot reach a sentence the reader has moved to after a lost start, and rule 3's "run ≥ 2" accepts a forced alignment (session 11: "She smiled at the clever fox" → 4 false candidates in sentence 1). The LISTEN approach suggests an explicit jump model over the whole page with a per-jump cost and an off-task outcome instead of forcing the nearest window. Per-word confidence (Parakeet gives it; P-2 measured right words 0.75–0.93, wrong 0.15–0.55) is unused by ADR-0013 today.

## 4. What counts as new

Signals in real products (rows N1–N20):
1. **A per-term status held by the learner model**: unknown / learning levels / known / ignored; "new" = no status row (Lute, LingQ, Migaku). Ignored keeps names and numbers out.
2. **Implicit promotion**: finishing a page makes untouched unknowns known (Lute, LingQ; a LingQ setting). For Leafi, acoustic and alignment evidence per word is stronger than "not clicked".
3. **Known from the SRS interval**: AnkiMorphs — known once the card's interval ≥ a threshold (Migaku ≈ 21 days *(reported)*). Leafi can read this through AnkiConnect, keeping Anki the scheduler (D6 of 2026-10-19).
4. **Frequency band as a prior**: Language Reactor's vocabulary-size slider, Clozemaster's top-10k, Readlang's "most useful". For a child: Cambridge Young Learners wordlists (Pre A1–A2, ages 6–12) and SUBTLEX-UK children's frequency fit better than adult lists; EVP gives CEFR per sense (licence unverified).
5. **Self-mark, reversible** (all readers).
6. **Failed recall** lowers status (Anki lapses already record it).
7. **Units beyond words**: lemma with inflections inheriting status; multi-word terms as units (Lute parents); EVP phrases and idioms; **grammar** via the English Grammar Profile (CEFR inventory) — no reader app models grammar, so this would be Leafi's own design.
8. **i+1**: a practice or card sentence with exactly one unknown (AnkiMorphs score: 10⁶ × unknowns, then frequency, then length penalty). Page coverage ≈ 95–98 % known for unassisted comprehension (adult scope).

## 5. Practice and cards

- **Prompt shape per practice type** (Duolingo, N9): fixed rules plus slots (target item, item kind, learner level, page context, theme); overgenerate, keep the best; humans reviewed at Duolingo — Leafi substitutes automatic checks plus a parent preview.
- **Card contract** (anki-llm, N14; Kotoba, N15): a strict JSON array mapped to note fields; checks return pass / flag / reject with a reason; plan → preview → batch → validate (target present; sentence uses only known words plus the target).
- **Card schema**: lemma first (Anki duplicate check on the first field, N13) → the sentence it was met in (Lute `{sentence}`, Readlang) → short meaning → optional audio → tags; recognition and recall cards from one note (Anki manual). SuperMemo's 20 rules (minimum information, cloze, no sets, context cues, "do not learn what you do not understand") as the checklist (N16).
- **Explanations** are better when the Brain gets the error, the target and the goal, not a bare word (Explain My Answer, N10 *(reported)*).
- **Comprehension questions**: plan 2–4 higher-order questions per section at chosen points (WWC, P3); LLM questions for primary pupils were comparable to human ones but had answerability flaws (N20, one study) → validate that the answer is in the page.
- **Practice methods** (P1–P5, P21–P24): guided rereading with a fluent model; for vocabulary, a child-friendly explanation in context, then cued recall with immediate feedback; block new words, mix only reviewed ones; never prompt guessing from pictures (WWC, P2).

## 6. Practice policy defaults (amount, duration, timing, rhythm, praise)

Starting values for the Brain's policy text and the code limits. Each is a default to tune, not a researched constant; "programme practice" means a T1 programme's own rule, not a study.

| Dimension | Default | Basis | Strength |
|---|---|---|---|
| Errors practised per cycle | ≤ 5 words, each until correct or 2 retries, skip always | Microsoft 5 (B4); ADR-0013 ≤ 2 retries | product practice |
| New items taught per cycle | 3–5 (≤ 8 per session) | Text Talk 3–4 per read-aloud (P25); incidental learning 9–18 % (P15) | programme practice |
| Encounters before "known" | ≥ 6 retrievals over ≥ 3 days, or Anki interval ≥ threshold | 2 to > 20 encounters in studies (P14); AnkiMorphs (N7) | weak |
| Comprehension questions | 2–4 per page or section, after reading | WWC (P3) | T1 guide |
| Session length | 15–20 min, hard max 30 (≈ 15 for ages 6–7); practice block ≤ 5–8 min | Reading Recovery 30 min one-to-one (P27); Reading Coach ≤ 10 min (B3); attention plateaus at 8–9 (P31, one study) | weak |
| Frequency | short and frequent (≥ 3 days a week) over long | tutoring meta-analysis (P28); hours did not moderate (P29) | moderate |
| Correction timing | none within a sentence; stuck word after ≥ 3–4 s silence; corrections in the practice phase, immediate there | §3.1 | split evidence, scope-matched |
| Rhythm | each session starts by rereading a familiar page; reread a page 2–3 times across cycles; word review same day / ~1 / ~3 / ~7 days (Anki does it) | Reading Recovery (P27); spacing (P16–P18) | moderate (spacing), weak (counts) |
| Praise | specific (self-correction, rereading, effort), not "smart", not inflated, at most one per page/turn, every self-correction | P32–P38 | moderate (kind), none (frequency) |
| Daily goal | composable targets: "Anki due = 0", "N new items", "1 page read"; minimum target keeps any streak; rest days; no nagging | Anki deck options (N17); Duolingo streak (N18, engagement only) | T1 (Anki) |

The per-sentence praise line Leafi speaks today ("Nice! / Smooth. / Got it.") conflicts with three rows at once: it interrupts reading (§3.1), it is the frequent praise P37/P38 warn against, and its playback closes the listening gate.

## 7. Runtime: an AI-led session under Leafi's constraints

Sources: R1–R14.

**Boundary.**
- *The Brain decides, once per activity boundary*: the next activity from `allowed` (listen to reading, practise words, teach new items, quiz, read aloud / translate, add a card, review Anki, break, end); which page items to use (ids code supplies); the child-facing wording; whether to propose a card; when to suggest ending.
- *Code decides*: turn-taking and timing (VAD, endpointing, half-duplex gate, silence thresholds); everything inside an activity that is measured (alignment, acoustic evidence for `confirmed`, retry caps, skip always — ADR-0013's owner role stays for what remains of it); limits (session minutes, items per cycle, LLM calls, cards); the allow-list per state; privacy redaction; the default action and fallbacks.

**Observation and decision format.**
- One observation per boundary, built by one module that is the only path to the Brain: trigger, session counters and limits, page excerpt and line ids, last activity outcome, difficulties as expected page words + category, plus the heard words when the learner's cloud setting allows it (D20), `allowed`, `default`, a rolling session note (not the full history).
- One decision schema for the whole session via structured outputs (`output_config.format`): `anyOf` one object per activity with a `const` name, `say_before`, and a short `note`. Keep the schema, effort and thinking constant all session so the grammar and prompt caches stay warm (R2, R3).
- Code validates after parsing (structured outputs cannot express numeric bounds, R2): activity ∈ allowed, ids exist, counts within limits, text length and content checks; one retry with the rejection reason (LiveKit `ToolError` style, R9), then `default`.

**Latency.** The Brain is called only at activity boundaries (between cycles), never per utterance; a local filler line plays while it thinks (Pipecat `pre_actions: tts_say`, R7); a hard timeout (2–3 s, to be measured) runs `default`; the decision can start while the child finishes the last line. Measured numbers are missing (§9).

**Fallback chain (application-owned).** Claude → Ollama with the same observation and schema (`format` = JSON schema, temperature 0; qwen3:8b 5.2 GB or 14b 9.3 GB must be measured next to Parakeet and Kokoro in 16 GB) → static default policy. A small classifier model (e.g. `nimble`, vendor-reported) could choose only the activity, with templates for words.

**Harness.** "Harness" is Anthropic's word for the code around a model that builds its context, exposes its tools, executes their effects, keeps state and enforces limits (Claude Code is called an agent harness; R15). Leafi's code plays exactly that role for the Brain, so the term fits: *study harness* = everything in §7's "code decides" list plus the record keeping below. It goes into `GLOSSARY.md` with the ADR.

**What the Brain may write.** Record-keeping tools whose effects code validates and stores (DeepTutor's user-editable memory layers, A8; Bloom's separate user-model store, A15): `record_assessment` (an activity's outcome in the Brain's words, tied to an activity id), `note_learner` (a durable observation about the learner, shown to the parent and editable), `set_item_status` (a word or phrase status change proposed by the Brain, applied only within code's rules — `confirmed` still needs acoustic evidence per ADR-0013). Code records the rest itself on every Brain call: model id and provider, prompt version hash, observation sent, decision returned, latency, tokens, validation result. The dialogue record is stored locally for the parent whatever the cloud setting; with the setting on, the turns sent to the Brain also exist at the provider (D20).

**Model access through magpie (R16–R17).** magpie is an MIT-licensed local desktop gateway (Go; Windows, macOS, Linux) at `127.0.0.1:3425` that accepts OpenAI Chat, OpenAI Responses, Anthropic Messages and Gemini requests and translates between them (streaming, tool calls, reasoning), routing to about twenty provider presets (Claude, OpenAI, Gemini, DeepSeek, Kimi, GLM, Qwen, MiniMax, Mistral, xAI, Groq, OpenRouter, Ollama, …) and to reused subscriptions. Models are named `provider/model`; groups `group/<id>` and `auto/<model>`; local clients use a placeholder key. A Leafi Brain backend for magpie is the existing Anthropic client with `base_url=http://127.0.0.1:3425` (or the OpenAI-compatible path shared with Ollama). Open points: structured outputs pass-through is not documented (probe before relying on it); whether request bodies are stored locally is not stated; a daily telemetry ping (random id, versions, which providers and models) is on by default and is switched off with `DO_NOT_TRACK=1` or Settings → Privacy; every provider behind magpie is a row of the egress table under the learner's cloud setting (D20). Owner decision: any provider, telemetry off, local storage allowed (D18).

**SDK facts (local source, R5).** `anthropic` 0.120.2: non-beta `messages` has `output_config`, `output_format`, `parse`, `cache_control`; **`beta.messages` also has `fallbacks`, `tool_runner`, `context_management`**. AGENTS.md's "no `fallbacks`" and TD-1 are true only for the non-beta namespace; `fallbacks` switches between Claude models only and never reaches Ollama. SDK 2.0/2.1 were released 2026-10-21 (R4). Per R1, Opus 5.5 rejects forced `tool_choice` (`any`/`tool`); use `auto` with strict tools or structured outputs.

## 8. Decision pool

| # | Decision | State | Basis |
|---|---|---|---|
| D1 | Session = cycles of READ (no interruption within a sentence) → PRACTICE of collected candidates → optional reread → next cycle; the per-sentence PRACTICE and per-sentence praise of ADR-0013 go | **Proposed** (needs a new ADR superseding ADR-0013's session rules) | §3.1, §6, owner requirement 2.2(a) |
| D2 | The Brain chooses the next activity and content from a code-computed menu at activity boundaries; code executes, times and limits | **Proposed** | §2, §7 |
| D3 | One observation builder is the only path to the Brain and applies the learner's cloud setting (D20): with cloud allowed it may carry heard words and the learner's text; with cloud off, miscues leave as expected page words + category and learner text stays local | **Proposed** (revised by owner decision 4) | §7, owner decisions |
| D4 | One structured-output decision schema per session; code validator; default action on timeout, refusal or rejection | **Proposed** | R1–R3, R9 |
| D5 | Alignment v2: page-wide jump model with per-jump cost, off-task outcome, conservative crediting, rereads as reading; per-word confidence used after tracking settles | **Needs design + prototype on recorded audio** | §3.3; session-11 defect |
| D6 | Learner model: per-term status (unknown / learning / known / ignored) by lemma and multi-word unit; known also from the Anki interval; frequency-band prior from Cambridge YLE + SUBTLEX-UK children | **Proposed** | §4 |
| D7 | Card pipeline: strict JSON contract, automatic checks (target present, i+1, answerable), parent preview, AnkiConnect with duplicate check | **Proposed** | §5 |
| D8 | Leafi-reads mode: highlight while reading known text; translation every sentence or "hard only" by Leafi's own rule | **Needs design** (no product rule exists) | §3.2 |
| D9 | Evaluate the AI-led policy against the code default on recorded sessions before trusting it | **Proposed** | §2 (two studies favour code choosing) |
| D10 | Ollama fallback model | **Needs measurement** (VRAM next to Parakeet + Kokoro; tool/schema reliability eval) | R11–R13 |
| D11 | Practice policy defaults of §6 as the Brain's policy text and code limits; all settings per learner | **Proposed** | §6 |
| D12 | Correct AGENTS.md / TD-1 about `fallbacks` in `beta.messages` | **Doc fix** | R5 |
| D13 | **Leafi autonomy** 0–10 per learner (owner decision 1): low = Leafi proposes and the learner's choice wins; middle = Leafi argues for its default and negotiates; 10 = Leafi decides goal, content and pace and the learner follows. The Brain receives the level in the observation; the harness enforces the asking levels (below a threshold Leafi must ask before starting an activity) | **Decided by owner; thresholds to design** | owner decisions; A1, A16 |
| D14 | Several learners: a `learners` table; every learning record keyed by learner. Identification by voice and face **on by default**, off when the learner forbids it or turns it off; saying or choosing a name always works as the fallback and confirmation. Recognition runs locally; voiceprints and face embeddings stay on the machine. The habit track's red line 01 (the cloud vision judge never infers identity) is separate and stays | **Decided by owner; recognition models to choose and measure** | owner decision 2 |
| D15 | Name the code around the Brain the *study harness*; the Brain writes records only through harness tools; the harness logs model, provider, prompt version, latency, tokens per call | **Proposed** | R15, A8 |
| D16 | Reading-cycle settings per learner: interruption policy (never / sentence end / stuck only), silence thresholds (backchannel, prompt), encouragement style and frequency | **Proposed** | owner addition 3; B8, B9, §6 |
| D17 | Learner-asks Q&A step after reading: the Brain answers from the page and the learning record; the question goes to the cloud when the learner's cloud setting allows it (default), else a local model answers | **Decided by owner** | owner additions 3, decision 4 |
| D18 | Brain backend `magpie` via its Anthropic Messages or OpenAI endpoint; any provider; `DO_NOT_TRACK=1` (and the privacy toggle) set by the harness's setup; magpie may keep local logs; structured outputs probed before relying on them | **Decided by owner + probe** | R16, R17, owner decision 5 |
| D19 | Learning-content memory in the harness: pages, stories, topics, items met and difficulties, per learner, queryable by the Brain (`recall_learning`: recent difficulties, familiar topics and stories) so practice reuses familiar material | **Decided by owner; schema to design** | owner decision 3; A4 (recent-attempt summaries help), A8 |
| D20 | **New privacy policy** superseding ADR-0011's text-only rule: a per-learner `cloud` setting, default on, covering learner text (words heard, questions, answers, name); still logged per destination in the egress table; the parent can turn it off and `forget` still deletes. **Audio and images** never leave by default: local first; on a local failure or low confidence Leafi asks the learner, then may ask "may I ask a remote teacher?" and sends that one clip or image only on a yes (each consent logged with the destination). **Pseudonymised identity**: before any cloud call the harness replaces the learner's name with a stable alias per learner, and age with an age band (or age ± 1 inside the same school year), and strips other identifying fields; the alias is mapped back locally in replies. Changes the AGENTS.md boundary, `tests/test_privacy.py` (the canary now checks the real name and exact age never leave, and audio/images leave only after a recorded consent), ADR-0011, `security.md`, `NOTIFY_WITH_SNAPSHOT`'s role | **Decided by owner** | owner decisions 4, 6, 7 |

## 9. Gaps (carried into the design or into measurements)

1. No study of a Chinese-L1 child reading English aloud with an AI tutor; the timing rule is extrapolated along scope lines.
2. Parakeet TDT: does it keep repetitions and partial words verbatim; is its word confidence calibrated on this child's speech (labelled set needed, `pronunciation-evaluation.md`).
3. Brain latency: Opus 5.5 time to first token with a structured-output schema at low effort; cold grammar compile; a local model's latency and VRAM.
4. Local-model reliability for the decision schema (an eval set of recorded observations → decisions).
5. No product rule for "hard sentences"; no evidence on praise frequency or in-session break frequency; no child-normed vocabulary-size test.
6. Unverified: AnkiConnect actions for today's review counts (`getNumCardsReviewedToday` etc.) against the installed add-on; EVP/EGP licence; Cambridge YLE list contents; Amira's intervention cap; Khanmigo inner-monologue details; OpenAI study-mode page (403).
7. Full texts not read: NRP ch. 3 sub-scores, WWC 2016 evidence levels, Therrien moderators, Bai et al. IberSPEECH 2021 (confidence thresholds), Rasmussen 2011 (offline tracking), Mostow & Aist 1999.

## 10. Source table

Tiers as in `tiered-research`. A vendor's first-hand engineering post about its own product is T4 with weight. All rows checked 2026-10-21.

### A. LLM tutors

| id | tier | resource | url | source-date |
|---|---|---|---|---|
| A1 | T2 | LearnLM tech report (Gemini 1.5 variant; expert role-players; 2,360 conversations) | https://arxiv.org/html/2412.16429v3 | v3 2025-08-22 |
| A2 | T1 | Gemini API LearnLM page (LearnLM folded into Gemini 2.5+) | https://ai.google.dev/gemini-api/docs/learnlm | 2026-04-28 |
| A3 | T4 (vendor) | Khan Academy, Khanmigo math computation and tutoring updates | https://blog.khanacademy.org/khanmigo-math-computation-and-tutoring-updates/ | 2025-02-26 |
| A4 | T4 (vendor, A/B-tested) | Khan Academy, how we're building a better AI tutor | https://blog.khanacademy.org/?p=21314 | 2026-05 |
| A5 | T1 (snippet; page 403) | OpenAI, introducing study mode | https://openai.com/index/chatgpt-study-mode/ | 2025-07-29 |
| A6 | T1 | Anthropic, Claude for Education (learning mode) | https://www.anthropic.com/news/introducing-claude-for-education | 2025-04-02 |
| A7 | T1 | Claude Code output styles (styles are advisory; hooks enforce) | https://code.claude.com/docs/en/output-styles | undated (living) |
| A8 | T3 | HKUDS/DeepTutor README | https://github.com/HKUDS/DeepTutor | v1.6.15, 2026-10-19 |
| A9 | T3 | CAHLR/OATutor README (BKT, LLM hints only) | https://github.com/CAHLR/OATutor | undated |
| A10 | T2 | StratL, Puech et al., Findings of ACL 2025 (GPT-4o, 17 students, maths) | https://arxiv.org/html/2410.03781v2 | 2025-03-18 |
| A11 | T2 | Bridge, Wang et al., NAACL 2024 (GPT-4, 700 tutoring chats) | https://arxiv.org/abs/2310.10648 | 2024-04-06 |
| A12 | T2 (abstract) | ES-LLMs, Kadir, AIED 2026 (simulation, 6 experts) | https://arxiv.org/abs/2603.23990 | 2026-03-25 |
| A13 | T1 | Pipecat Flows guide and types | https://docs.pipecat.ai/guides/features/pipecat-flows | pipecat-ai 1.5.0 |
| A14 | T4 (vendor) | Khan Academy, 7-step approach to prompt engineering | https://blog.khanacademy.org/khan-academys-7-step-approach-to-prompt-engineering-for-khanmigo | 2023-10-23, upd. 2025-03-21 |

### B. Read-aloud tutors, tracking, correction

| id | tier | resource | url | source-date |
|---|---|---|---|---|
| B1 | T1 | Microsoft, getting started with Reading Coach | https://support.microsoft.com/en-US/education/getting-started-with-reading-coach | undated (living) |
| B2 | T1 | Microsoft, practice words with Reading Coach | https://support.microsoft.com/en-us/education/learning-accelerators/practice-words-with-reading-coach | undated (living) |
| B3 | T1 | Microsoft, Reading Coach in Immersive Reader (≤ 10 min) | https://support.microsoft.com/en-us/education/use-reading-coach-in-immersive-reader | undated (living) |
| B4 | T1 | Microsoft Education blog, educator's guide (5 words, read again) | https://www.microsoft.com/en-us/education/blog/?p=7446 | 2025-01-09 |
| B5 | T1 | Microsoft, Reading Progress in Teams (sensitivity, taxonomy) | https://support.microsoft.com/en-US/education/getting-started-with-reading-progress-in-teams | undated (living) |
| B6 | T1 | Google Read Along help | https://support.google.com/readalong/answer/12291548 | undated (living) |
| B7 | T4 | Amira Intervention Encyclopedia (≈ 1 per page, reported) | https://explore.amiralearning.com/hubfs/Customer-Resources/Intervention_Encyclopedia.pdf | undated |
| B8 | T1 | EPS Reading Assistant, how help works (≥ 3 s, mean ≈ 6 s) | https://support.epslearning.com/how-does-reading-assistant-help-during-practice | 2026-07-02 |
| B9 | T2 | Mostow, why and how our automated reading tutor listens (Project LISTEN, grades 1–4) | https://www.cs.cmu.edu/~listen/pdfs/2012-05-05%20ISADEPT2012%20keynote%20final.pdf | 2012 |
| B10 | T1 | Ello, the reading coach FAQ (lenient) | https://www.ello.com/the-reading-coach | undated (living) |
| B11 | T2 | Li & Mostow, real-time tracking accuracy (80 children) | https://www.cs.cmu.edu/~listen/pdfs/FLAIRS2012%20Real-time%20Tracking%20accuracy.pdf | 2012 |
| B12 | T2 | Bai et al., explicit vs implicit feedback (n = 525, Dutch grade 1) | https://www.isca-archive.org/interspeech_2022/bai22b_interspeech.pdf | 2022-09 |
| B13 | T2 | Gao et al., miscue detection (71 Dutch children 6–13) | https://arxiv.org/pdf/2406.07060 | 2024 |
| B14 | T2 | Sunder et al., pointer-network reading tracker | https://arxiv.org/abs/2310.11486v1 | 2023-10-17 |
| B15 | T2 (abstract) | Smith et al., target-text prompting for verbatim ASR | https://www.isca-archive.org/interspeech_2025/smith25_interspeech.html | 2025 |
| B16 | T3 | ReadAlong Studio (NRC Canada) | https://github.com/ReadAlongs/Studio | 2019–2025 |
| B17 | T2 (abstract) | Review of 24 error-correction studies (J. Behavioral Education) | https://link.springer.com/article/10.1023/A:1022864707734 | 1998 |
| B18 | T2 (abstract) | Auckland thesis, delayed attention raises self-correction (6 children) | https://researchspace.auckland.ac.nz/handle/2292/1464 | 1981? |
| B19 | T4 | Read Along launch coverage | https://techcrunch.com/2020/05/07/google-launches-read-along-a-free-app-that-helps-young-children-practice-reading | 2020-05-07 |

### N. New content, practice generation, goals

| id | tier | resource | url | source-date |
|---|---|---|---|---|
| N1 | T1 | Lute v3 `Status` model | https://raw.githubusercontent.com/LuteOrg/lute-v3/master/lute/models/term.py | undated (living) |
| N2 | T1 | Lute manual: reading, parent terms, stats, Anki export | https://raw.githubusercontent.com/LuteOrg/lute-manual/master/src/usage/reading/reading.md | undated (living) |
| N3 | T1 | LingQ help, statuses | https://lingq-support.groovehq.com/help/can-you-explain-a-lingqs-status | 2020-10-06 |
| N4 | T1 | LingQ help, how new words are found | https://lingq-support.groovehq.com/help/how-do-you-know-which-words-are-new-to-me | 2020-10-14 |
| N5 | T4 | Migaku word statuses (reported) | https://migaku.com/ja/blog/youtube/supercharge-your-language-learning-tracking-learned-words | undated |
| N7 | T1 | AnkiMorphs glossary and recalc (known by interval, i+1 score) | https://mortii.github.io/anki-morphs/user_guide/glossary.html | undated (living) |
| N8 | T1 | Clozemaster FAQ | https://www.clozemaster.com/faq | undated (living) |
| N9 | T4 (vendor) | Duolingo, LLM "Mad Lib" prompts | https://blog.duolingo.com/large-language-model-duolingo-lessons | 2023-06-22 |
| N10 | T4 | OpenAI customer story, Duolingo (Explain My Answer) | https://openai.com/index/duolingo | 2023 |
| N11 | T4 (vendor) | Duolingo, Birdbrain | https://blog.duolingo.com/learning-how-to-help-you-learn-introducing-birdbrain | 2020-10-07 |
| N12 | T4 | English Profile (EVP/EGP) | https://en.wikipedia.org/wiki/English_Profile | undated |
| N13 | T4 | Yomichan (first-field duplicate check) | https://github.com/Rapptz/yomichan | undated |
| N14 | T3 | anki-llm prompt reference | https://anki-llm.raine.dev/prompt-reference/ | undated (living) |
| N15 | T3 | Kotoba (plan → preview → batch → validate) | https://github.com/yufengliu15/kotoba | 2026-06-17 |
| N16 | T1 | SuperMemo, twenty rules of formulating knowledge | https://www.supermemo.com/en/blog/twenty-rules-of-formulating-knowledge | 1999 (upd.) |
| N17 | T1 | Anki manual, deck options (limits, FSRS retention) | https://docs.ankiweb.net/deck-options.html | undated (living) |
| N18 | T4 (vendor) | Duolingo, streaks | https://blog.duolingo.com/how-streaks-keep-duolingo-learners-committed-to-their-language-goals | 2017-05-10 |
| N19 | T4 | Cambridge Young Learners wordlist (Flyers) | https://www.cambridgeenglish.org/pl/Images/149681-yle-flyers-word-list.pdf | exams from 2018 |
| N20 | T2 | LLM comprehension MCQs for primary pupils | https://arxiv.org/abs/2506.15598 | 2025 |
| N21 | T2 | SUBTLEX-UK (incl. children's programmes) | https://eprints.nottingham.ac.uk/2947/ | 2014 |
| N22 | T2 | Nation 2006, vocabulary size and coverage | https://www.wgtn.ac.nz/__data/assets/pdf_file/0018/1626120/2006-How-large-a-vocab.pdf | 2006 |

### P. Practice dosage and timing

| id | tier | resource | url | source-date |
|---|---|---|---|---|
| P1 | T1 | National Reading Panel ch. 3, fluency | https://www.nichd.nih.gov/sites/default/files/publications/pubs/nrp/Documents/ch3.pdf | 2000 |
| P2 | T1 | WWC, Foundational Skills K–3 (NCEE 2016-4008) | https://ies.ed.gov/ncee/wwc/Docs/PracticeGuide/wwc_foundationalreading_040717.pdf | 2016 |
| P3 | T1 | WWC, Improving Reading Comprehension K–3 | https://ies.ed.gov/ncee/wwc/practiceguide/14 | 2010 |
| P4 | T2 (abstract) | Therrien, repeated reading meta-analysis | https://apps.asha.org/EvidenceMaps/Articles/ArticleSummary/903ec865-92fd-4ca5-9cea-8534b161420a | 2004 |
| P6 | T2 | Kuhn & Stahl, fluency review | https://scholarworks.gsu.edu/psych_facpub/162 | 2003 |
| P9 | T2 | Shake, teacher interruptions and self-monitoring | https://scholars.uky.edu/en/publications/teacher-interruptions-during-oral-reading-instruction-self-monito/ | 1986 |
| P10 | T2 | Grønli et al., feedback on young students' oral reading (52 studies) | https://journals.sagepub.com/doi/reader/10.3102/00346543241306070 | 2025 |
| P11 | T2 (abstract) | Li, Ellis & Shu, immediate vs delayed CF (Chinese L1 EFL, n = 120) | https://researchspace.auckland.ac.nz/handle/2292/28987 | 2016 |
| P14 | T2 | Uchihara, Webb & Yanagisawa, repetition meta-analysis | https://todoele.net/node/429491 | 2019 |
| P15 | T2 | Webb, Uchihara & Yanagisawa, incidental learning meta-analysis | https://www.cambridge.org/core/product/E38E3468FD2090B1FA3051051DE8E70C | 2023 |
| P16 | T2 | Kim & Webb, spaced practice in L2 (37 experiments) | https://www.cambridge.org/core/product/C833408A4C3BAD939CA39EA734423BB7 | 2022 |
| P18 | T2 (abstract) | Rogers & Cheung, spacing with Cantonese-L1 primary EFL | https://www.cambridge.org/core/services/aop-cambridge-core/content/view/DFAD98F9D5B1547579EA1CC7D339B85D/S0272263120000236a.pdf/does-it-matter-when-you-review-input-spacing-ecological-validity-and-the-learning-of-l2-vocabulary.pdf | 2020 |
| P19 | T2 | Brunmair & Richter, interleaving meta-analysis | https://www.psychologie.uni-wuerzburg.de/fileadmin/06020400/2019/Brunmair_Richter_in_press__2019_META-ANALYSIS_OF_INTERLEAVED_LEARNING.pdf | 2019 |
| P22 | T2 | Preschool testing-effect experiments | https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2018.01446/pdf | 2018 |
| P23 | T2 (abstract) | Biemiller & Boote, vocabulary in primary grades | https://www.ovid.com/journals/jedup/pdf/00004760-200602000-00004~an-effective-method-for-building-meaning-vocabulary-in | 2006 |
| P24 | T2 | Marulis & Neuman, vocabulary interventions meta-analysis | https://journals.sagepub.com/doi/10.3102/0034654310377087 | 2010 |
| P25 | T1 (programme) | Text Talk (Beck & McKeown) | https://teacher.scholastic.com/products/texttalk/pdfs/Capturing_the_Benefits.pdf | 2001 |
| P27 | T1 (programme) | Reading Recovery facts | https://readingrecovery.org/wp-content/uploads/2023/02/GetTheFacts.pdf | 2023 |
| P28 | T2 | Nickow, Oreopoulos & Quan, tutoring meta-analysis | https://www.nber.org/papers/w27476 | 2020/2024 |
| P29 | T2 (abstract) | Wanzek et al., Tier 2 K–3 interventions | https://meadowscenter.org/library/meta-analyses-of-the-effects-of-tier-2-type-reading-interventions-in-grades-k-3/ | 2016 |
| P31 | T2 (abstract) | Sustained attention in children 5–12 (n = 57) | https://www.cogstate.com/publication/the-development-of-sustained-attention-in-children-the-effect-of-age-and-task-load/ | 2006 |
| P32 | T1 (programme, reported) | Pause, Prompt, Praise (Glynn, McNaughton et al.) | https://poutamapounamu.org.nz/module-7a/6-coherency-across-the-school | 1979 |
| P35 | T2 | Mueller & Dweck, praise for intelligence | https://jwilson.coe.uga.edu/emat7050/Students/Ramsey/Perils%20of%20Praise-Dweck.pdf | 1998 |
| P37 | T2 (reported) | Brummelman et al., inflated praise | https://parentingscience.com/praise-and-intelligence/ | 2014 |
| P38 | T2 (abstract) | Henderlong & Lepper, praise review | https://pubmed.ncbi.nlm.nih.gov/12206194/ | 2002 |

### R. Runtime

| id | tier | resource | url | source-date |
|---|---|---|---|---|
| R1 | T1 | Anthropic, define tools / tool_choice | https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools | undated (living) |
| R2 | T1 | Anthropic, structured outputs | https://platform.claude.com/docs/en/build-with-claude/structured-outputs | undated (living) |
| R3 | T1 | Anthropic, prompt caching | https://platform.claude.com/docs/en/build-with-claude/prompt-caching | undated (living) |
| R4 | T1 | anthropic-sdk-python CHANGELOG | https://raw.githubusercontent.com/anthropics/anthropic-sdk-python/main/CHANGELOG.md | 2026-10-21 |
| R5 | T1 (local source) | installed `anthropic` 0.120.2, `.venv\Lib\site-packages\anthropic` | — | 0.120.2 |
| R6 | T1 | Rasa CALM | https://rasa.com/docs/learn/concepts/calm/ | undated (living) |
| R7 | T1 | Pipecat Flows types (`pre_actions`, `context_strategy`) | https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/flows/types.py | pipecat-ai 1.5.0 |
| R8 | T4 (vendor) | Anthropic, building effective agents | https://www.anthropic.com/engineering/building-effective-agents | 2024-12-19 |
| R9 | T1 | LiveKit Agents, function tools (`ToolError`) | https://docs.livekit.io/agents/build/tools/function-tools/ | undated (living) |
| R10 | T4 (vendor) | Anthropic, effective context engineering | https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents | 2025-09-29 |
| R11 | T1 | Ollama tool calling | https://docs.ollama.com/capabilities/tool-calling | undated (living) |
| R12 | T1 | Ollama structured outputs | https://docs.ollama.com/capabilities/structured-outputs | undated (living) |
| R13 | T1 | Ollama library, qwen3 | https://ollama.com/library/qwen3 | undated |
| R14 | T1 | OpenAI Agents SDK voice pipeline (mic muted between turn events; design reference) | https://openai.github.io/openai-agents-python/voice/pipeline/ | undated (living) |
| R15 | T4 (vendor) | Anthropic engineering, effective harnesses for long-running agents ("agent harness") | https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents | 2025-11-26 |
| R16 | T1 | magpie site and get-started docs | https://usemagpie.ai/docs/start | undated (living) |
| R17 | T1 | yetone/magpie README (Go, MIT, ~19k stars, telemetry, `DO_NOT_TRACK`) | https://github.com/yetone/magpie | undated (living) |
| A15 | T3 | plastic-labs/tutor-gpt (Bloom) README | https://github.com/plastic-labs/tutor-gpt | v0.8.0 |
| A16 | T3 | Mr. Ranedeer README (preference fields) | https://github.com/JushBJJ/Mr.-Ranedeer-AI-Tutor | v2.7 |
