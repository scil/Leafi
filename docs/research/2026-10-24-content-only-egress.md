# Content-only egress: research and reference collection

Question: how should `leafi/`'s egress redact text once the owner's rule of 2026-10-24 drops the source rules ("egress redacts by content only and ignores where a text came from"; plan Decision log)? Decision it serves: ADR-0021 and the design note `docs/plans/active/2026-10-24-content-only-egress-design.md`. Method: `tiered-research` (sources by authority tier, verdicts with their corpus), then `gather-code-references` (project facts first, then external patterns, then a decision pool). Checked 2026-10-24.

## 1. Owner decisions this collection serves (2026-10-24)

| # | Decision | Source |
|---|---|---|
| O1 | Content-only redaction for all of `leafi/`'s cloud traffic (Brain, TTS, every service through `leafi.privacy.egress`) | owner, chat |
| O2 | The per-learner `cloud.text` setting is removed | owner |
| O3 | Guests are treated like enrolled learners for text | owner |
| O4 | `provenance_class` / `source_learners` are dropped from storage; deletion by learner and session ids | owner |
| O5 | The name detector scans every text except the fields a request declares as book text | owner (the recommended option) |
| O6 | An unanswered school leaves verbatim when the detector is off, missing or misses it (T6 "send anyway") | owner, earlier the same day |
| O7 | The habit track (`agent/`, ADR-0011) is unchanged | owner |

## 2. Project facts (code, 2026-10-24)

From a full inventory of `leafi/`, `tests/`, `config/` and `docs/` (≈ 130 sites; the design note lists them by group):
- Schema version 6 (`leafi/core/storage.py:159`); migrations live in `storage.py` (`migrate_file`, `_step`); the next one is **7**. M7's planned `item_status_events` migration and M7f's interests migration are not written yet, so they move to 8 and 9.
- Nothing but egress, `forget` (`records._purge_derived`), the write fence (`learner_store.stated_sources`, `insert_named`) and `cards.stored_text` reads the stored provenance columns. No routing reads them.
- The Kokoro vs edge-tts choice (`TtsService._must_stay_local`) uses the in-memory `Provenance` (`learners_own`) **and** a content check (a listed protected name, M5 D13).
- `egress._gate` holds every source refusal: parent text (`CLOUD_PARENT_TEXT`), a source learner's `cloud.text`, a guest, unknown provenance. The detector runs only on `learner` / `derived_from_learner` leaves (`egress.py:393, 399–400`); plain strings get the lists only (`_plain_strings`).
- The provenance columns carry only a column CHECK (`_PROV`) and no index, foreign key, trigger or view (schema read at `storage.py:161–330`), so SQLite's `ALTER TABLE … DROP COLUMN` applies (see S2).
- The Python install runs SQLite 3.54.1 (ADR-0019 §2), above DROP COLUMN's 3.35.0.
- The name detector is Presidio with spaCy `en_core_web_sm` 3.8.0 (`leafi/privacy/detector.py`); the round-1 probe found it misses lower-case names ("st marys school", "riverside primary", "oakfield", "tom").

## 3. Sources

| # | Source | Tier | source-date | checked | Taken | Not taken |
|---|---|---|---|---|---|---|
| S1 | Presidio home, `presidio.dataprivacystack.org` | 1 (owner of the tool) | living page | 2026-10-24 | "there is no guarantee that Presidio will find all sensitive information … additional systems and protections should be employed" | — |
| S2 | SQLite `lang_altertable.html` §DROP COLUMN; release log 3.35.0 | 1 | living page; 2021-03-12 | 2026-10-24 | the eight failure conditions (PRIMARY KEY, UNIQUE, indexed, partial-index WHERE, a CHECK *not associated with the dropped column*, foreign key, generated column, trigger or view); added in 3.35.0 | — |
| S3 | LangChain guardrails, `PIIMiddleware` (Python docs) | 1 (vendor docs) | living page | 2026-10-24 | redaction as one middleware on the model call; strategies redact / mask / hash / block; input on by default, output optional; the warning that input redaction does not clean earlier records, logs or traces | regex-only detectors (email, card, IP, URL): too narrow for names |
| S4 | LLM Guard Anonymize / Deanonymize (`protectai.github.io/llm-guard`) | 1 (vendor docs) | living page | 2026-10-24 | reversible redaction: placeholders, a Vault holding originals, Deanonymize on the reply; Presidio underneath; `allowed_names`, `hidden_names`; "entity detection functionality is English-specific" | a second detector stack (transformer NER models) beside Leafi's |
| S5 | NeMo Guardrails, PII detection (NVIDIA docs, 0.21.0) | 1 (vendor docs) | 0.21.0 | 2026-10-24 | Presidio-backed rails scoped separately to user input, bot output and retrieved chunks: redaction scope is chosen per field type | the rails runtime |
| S6 | Portkey / TrueFoundry gateway PII redaction | 4 (product docs as examples) | living pages | 2026-10-24 | numbered placeholders (`{{EMAIL_ADDRESS_1}}`); redaction at a gateway in front of every call | a hosted gateway: every request would leave the machine twice |
| S7 | Costa et al., *Securing AI Agents with Information-Flow Control* (FIDES), arXiv 2505.23643; Microsoft Agent Framework security docs | 2 (one study) + 1 (vendor) | 2025; living | 2026-10-24 | label-based flow control is the alternative to content redaction; its known cost is label creep | not adopted: the owner chose content-only (O1) |
| S8 | CaMeL; APPA (arXiv 2607.24625); *Confuse the Model, Control the Flow* (arXiv 2609.14003) | 2 | 2025–2026 | 2026-10-24 | the same alternative; one study reports leakage when enforcement relies on the model | reported only |
| S9 | Round-1 detector probe (`reviews/2026-10-24-practice-design-rev3-claude-b.md` #5) | project measurement | 2026-10-24 | 2026-10-24 | lower-case school and person names missed; mixed case found | one probe, six sentences: not a recall figure |

## 4. Verdicts

| Claim | Verdict | Corpus |
|---|---|---|
| Content redaction alone finds every name | CONTRADICTED by S1 (no guarantee) and S9 (probe misses) | Presidio's own site; the project probe |
| Mature tools redact by content at one seam before the model call | CONFIRMED (S3, S4, S5, S6) | vendor docs |
| Reversible placeholders (redact, then restore in the reply) are a common pattern | CONFIRMED (S4 Vault, S6 numbered placeholders); Leafi's surrogates already do it (ADR-0018 §3) | vendor docs; `pseudonym.py` |
| Redaction scope chosen per field type is an established practice | CONFIRMED for NeMo (input / output / retrieval rails, S5); LangChain scopes input vs output (S3) | vendor docs |
| SQLite can drop the provenance columns without a table rebuild | CONFIRMED (S2) given no index, FK, trigger or view names them (project fact §2); to be asserted by the migration's test | SQLite docs; `storage.py` |

## 5. Decision pool

| Candidate | Status | Basis |
|---|---|---|
| One redaction step at `prepare` for every cloud-bound text | adopt | S3, S4, S5; O1 |
| Keep Leafi's surrogate lists and map-back as the reversible placeholder mechanism | adopt | S4, S6; ADR-0018 §3 |
| Detector on every non-book field; lists on every field | adopt | O5; S5's per-field scope |
| A second NER stack (LLM Guard's transformer models) for better recall | defer | S4; would need a recall measurement on this household's transcripts first (ADR-0018 §3 step 2 already asks for one) |
| Lower-casing-aware detection (case-folded list matching already exists; detector on a title-cased copy) | defer, measure | S9; an original idea, unmeasured |
| Label-based flow control (FIDES-style) | reject | O1 |
| A hosted redaction gateway | reject | S6: a second party receives every request |
| DROP COLUMN in place, then one `VACUUM` | adopt | S2; ADR-0019 §7 (`secure_delete`, `VACUUM` for remnants) |
| Keep `consents.purpose = 'cloud_text'` in the CHECK for old rows, write none | adopt | project fact (history rows exist) |
| Clear the whole TTS cache on `forget --learner` instead of per-clip sources | adopt | O4; the cache is a 90-day cache (`security.md`) |

## 6. Gaps

- No recall figure for the detector on this household's transcripts, typed lines or ASR output (ADR-0018 §3 already requires one before claiming completeness). Under content-only it is the only protection, so the gap matters more: the design states it as the accepted cost (O1, O6) and adds the measurement to M10.
- Whether Parakeet's casing holds on children's speech in practice is unmeasured; typed console lines are often lower case.
