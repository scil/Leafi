# Codex design review, round 7 — rev 8 settings manifest (gpt-6-astra, reasoning high, read-only)

Run 2026-10-21 against the Rev 8 section. Prompt: prompts/env-round-7.md.

## 1. Defects

**P1 = blocker; P2 = correctness gap.**

**D1 — P1: The gate schema rejects its own boolean example.**  
Location: [§8.1, §8.2 and §8.5](E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:35).

`PRON_AUTO_JUDGE` has `gate.values: ["true"]`, but `options` is permitted only for `enum` and `list`. The unconditional requirement that *every gate value belongs to options* therefore rejects this entry.

There is also an unresolved comparison rule: validating the submitted `"true"` produces Python `True`; it does not equal the manifest string `"true"`. Both operands need normalization into the same domain. The existing typed-gate tests would catch this comparison mistake, but the design must resolve the schema contradiction first.

Specify gate validation separately for boolean, enum/list and nonempty gates; retain alias tests for `yes`, `1` and `on`.

**D2 — P1: The migration can silently remove existing privacy, masking and release protections.**  
Location: [§8.2–§8.5](E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:63).

The promised retained tests do not independently cover every protection being deleted:

- Removing `secret` from `BARK_URL` or `HEARTBEAT_URL` passes the credential-name rule. Neither name matches it, and the masking tests exercise `TELEGRAM_BOT_TOKEN` and Unknown keys. Their values would become visible.
- Omitting `privacy` from `REDACT_TERMS`, `AUDIO_KEEP_CLIPS`, `EVAL_TRANSCRIPTS`, `BRAIN_BACKEND`, `STUDY_BRAIN_MODEL` or either TTS backend can pass the retained tests. Those tests exercise confirmation for `NOTIFY_WITH_SNAPSHOT` and `BOOK_LOOKUP`.
- Removing the `ASR_HOTWORDS=lexicon`, `OCR_SECOND_OPINION nonempty` or `BRAIN_LOCAL_MODEL nonempty` gate can pass. The generic assertion that offered options are not gated is self-consistent even when the gate itself is missing.

These are concrete regressions from [the existing protection tables](E:/GitHub/scil/Leafi/leafi/envedit.py:29), including ADR-0011 release gates. Add independent, parameterized behavioral tests for every existing protected key and gate. Deriving expected protections from the manifest would not catch omissions.

**D3 — P2: Agreement covers backend registries, but not other finite choices.**  
Location: [§8.2 agreement tests](E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:63).

For example, adding `"PP-OCRv7"` to `OCR_VERSION.options` satisfies the manifest’s enum rules and its Settings annotation, which is `str`. The page could save it, while [RapidOCR rejects it](E:/GitHub/scil/Leafi/leafi/services/ocr/rapidocr.py:27). None of the specified agreement tests checks that domain.

Likewise, adding an unsupported service to `SUPERVISE.options` passes string validation and list encoding tests; [the supervisor’s explicit service branches](E:/GitHub/scil/Leafi/leafi/ops/supervisor.py:457) do not supervise it.

Finite choices need agreement with their actual consumers, including non-backend enums and list members. Encoding round trips establish representation, not supported meaning.

**D4 — P2: Non-Settings defaults and reader relationships can drift undetected.**  
Location: [§8.1 defaults and §8.2 agreement](E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:57).

The tests check that external references have entries naming their readers, but do not require agreement with external default values or fallback operators. Changing `${GATUS_TOKEN:-change-me}` to another fallback—or changing `:-` to `-`—need not fail any specified test.

A plain `default` string also cannot represent the distinction between “absent” and “absent **or empty**.” Rev 7 explicitly displays that distinction. For `GATUS_TOKEN=''`, Leafi receives an empty string while Compose supplies `change-me`.

Require external default/operator agreement and retain empty-value consequences. Reader agreement should also be bidirectional: the present wording permits stale non-Settings reader claims and checks Settings field existence without explicitly requiring every corresponding reader association.

**D5 — P2: Generated examples are checked for canonical syntax, not usable settings.**  
Location: [§8.3 and §8.5](E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:70).

An active example `ASR_THREADS=eight` is canonical and can exactly match generated output, yet Settings rejects it. The existing example test compares dotenv text with `EnvFile.values()`; it does not instantiate Settings from the example.

Validate active generated assignments through the file-only Settings validation and applicable manifest constraints. Independently preserve safe example states for gated features and privacy opt-ins; byte-for-byte regeneration alone proves neither.

I found no necessary import-boundary violation in placing a standard-library loader under `leafi.core`. Keeping §1, §2 and §5 intact also preserves the transaction machinery; rev 8 does not inherently weaken atomic writes.

## 2. Test-time agreement versus Settings construction

**The reasoning against checking at every Settings construction is sound.** Household services should not depend on editor metadata being present and correct. Static Settings classes also retain their typing benefits.

**P2 — Location: §8.2.** The stronger claim that a test prevents runtime disagreement is conditional on deploying exactly the tested code and manifest. Tests cannot catch a later local manifest edit, a partial update, or a process using already-imported Settings code with a newer manifest.

A shape-valid manifest can then expose a secret, remove a confirmation requirement, or offer an unsupported enum value. The unchanged whole-file validation still catches scalar values rejected by Settings, but it cannot recover missing privacy metadata or validate domains represented as plain strings.

The appropriate runtime boundary is **the editor**, not Settings construction: it can check compatibility against the loaded classes and refuse editing on disagreement while other services continue. Safety policies also need independent checks such as D2; comparing types and defaults alone cannot establish them.

## 3. Type table: concrete reader behavior

I used read-only probes against the installed **pydantic-settings 2.14.2**. Not every type has a valid parser-disagreement counterexample; expected conversion should not be reported as a defect.

| Type | Concrete value and reader result | Assessment / location |
|---|---|---|
| `text` | `WEEKLY_REPORT=garbage` passes `str` validation, but `parsed_weekly_report()` rejects it when splitting the required three components. | **P2, inherited limitation:** Settings string validation does not validate downstream grammars. [Reader](E:/GitHub/scil/Leafi/agent/config.py:49). Plain strings themselves preserve canonical text. |
| `secret` | Empty `GATUS_TOKEN`: Settings reads `""`; Compose uses `change-me`. Empty `CAM_PASSWORD` likewise activates Compose’s fallback. | **P2, §8.1 defaults:** an intentional reader difference whose explanation rev 8 must retain. [Compose](E:/GitHub/scil/Leafi/docker-compose.yml:53). This applies to an API `empty` operation; a blank password input remains unchanged. |
| `int` | `TASK_REPEAT_MIN=0` parses as integer `0`, but timing validation supplies `5` to PowerShell. Separately, `4.0` parses as integer `4`. | **Expected conversion/fallback, §8.1 and retained §5:** timing warnings already explain the first case. No new integer parser mismatch. |
| `float` | `KEEP_CRASH_WINDOW_MIN=nan` passes float parsing; timing validation substitutes `30` before PowerShell receives it. `9007199254740993` becomes `9007199254740992.0`. | **Expected fallback/precision behavior:** “float parse” permits nonfinite values and rounding; it does not promise finite or exact arithmetic. |
| `bool` | `true` → `True`; `false` → `False`. Both work. `yes`, `1`, `on` also parse as true, although the new page need not emit them. | **No emitted-value parser counterexample. P1 is D1:** comparing typed `True` with string `"true"` fails. `(默认)` must retain the existing `unset` operation; `BOOL=` would be rejected. |
| `path` | `DATA_DIR=` becomes `Path(".")`; `./data//cache` becomes `data/cache`. | **P2 usability/semantics, §8.1:** empty means the current directory, not the field default or “disabled.” These are normal Path conversions. Windows backslashes remain rejected by the unchanged storage grammar. |
| `enum` | With the unchecked option addition described in D3, `OCR_VERSION=PP-OCRv7` passes manifest and Settings validation but RapidOCR rejects it. | **P2, §8.2:** missing agreement with the consumer’s domain. No demonstrated mismatch for the currently valid choices. |
| `list` | `SUPERVISE=docker,camera` remains a string in Settings and becomes two service names downstream. `SUPERVISE=` becomes an empty selection. Both agree. However, valid `KEEP_BACKOFF_S=5,5,30` contains a repeated delay and cannot be represented by this checkbox type. | **P2 if applied beyond sets, §8.1:** this is a finite-set type, not a general comma-separated-list type. Ordered/repeated delays, free-form redaction terms and key/value grace entries require other handling. |

Two details matter:

- [PowerShell timing](E:/GitHub/scil/Leafi/scripts/win/timing.ps1:4) consumes `python -m leafi timing --env`; it does **not** independently parse `.env`. Claims about PowerShell directly misreading quoted booleans or comma lists would be incorrect here.
- “None checked writes `KEY=`” must mean the **empty value operation**. With an existing inline comment, canonical serialization writes `KEY=''   # help`. Literal `KEY=   # help` would violate the retained guarantee.

## 4. What an implementer still has to decide

| Classification | Severity / location | Required decision |
|---|---|---|
| **Blocker** | P1, §8.1–§8.5 | Define type-specific gate shapes and normalization of both submitted values and gate literals. |
| **Blocker** | P1, §8.4–§8.5 | Specify independent regression coverage preserving every current secret exception, privacy confirmation and release gate. |
| **Blocker** | P2, §8.2 | Define consumer agreement for non-backend enums and finite-set options. |
| **Blocker** | P2, §8.1–§8.2 | Represent absent-versus-empty defaults and verify external defaults and reader associations. |
| **Blocker** | P2, §8.3–§8.5 | Require semantic validation of generated active examples, including safe gate and opt-in states. |
| **Implementer may decide** | P2, §8.1 | Classify individual comma-separated settings. Keep ordered, repeated or free-form values out of the checkbox type. |
| **Implementer may decide** | P2, §8.1 and §5 | Reject noncanonical list order or normalize it. Define confirmation hashing consistently with the submitted and written representation. |
| **Implementer may decide** | P2, §8.1/page | Display existing boolean aliases and noncanonical list spellings without silently changing untouched values; distinguish absent defaults from an explicit empty selection. |
| **Implementer may decide** | P2, §8.2 | Add editor-local compatibility checks for deployment skew. Keep them out of service Settings construction. |
| **Implementer may decide** | P2, §8.3 | When no example exists, require an explicit example if defaults differ between readers or no default exists. There is otherwise no unique “its default.” |
| **Implementer may decide** | P2, §8.2 | Specify malformed/missing-file error responses and lazy loading so manifest failure cannot prevent the task tab from starting. |

## Remaining blockers before coding

D1–D5: gate semantics; complete protection-preservation tests; consumer-domain agreement; external reader/default semantics; and semantic validation of generated examples.
## 1. Defects

**P1 = blocker; P2 = correctness gap.**

**D1 — P1: The gate schema rejects its own boolean example.**  
Location: [§8.1, §8.2 and §8.5](E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:35).

`PRON_AUTO_JUDGE` has `gate.values: ["true"]`, but `options` is permitted only for `enum` and `list`. The unconditional requirement that *every gate value belongs to options* therefore rejects this entry.

There is also an unresolved comparison rule: validating the submitted `"true"` produces Python `True`; it does not equal the manifest string `"true"`. Both operands need normalization into the same domain. The existing typed-gate tests would catch this comparison mistake, but the design must resolve the schema contradiction first.

Specify gate validation separately for boolean, enum/list and nonempty gates; retain alias tests for `yes`, `1` and `on`.

**D2 — P1: The migration can silently remove existing privacy, masking and release protections.**  
