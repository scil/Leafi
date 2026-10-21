# Codex design review, round 8 — rev 8 §8.6 (gpt-6-astra, reasoning high, read-only)

Run 2026-10-21. Prompt: prompts/env-round-8.md.

## 1. Resolution status

- **D1 — resolved:** gate literals and submissions share typed validation; option membership applies only to enum/list gates.
- **D2 — resolved:** the independent behavioral protection floor covers the existing protections.
- **D3 — resolved:** consumer-domain agreement is now required; implementation must preserve runtime behavior.
- **D4 — partially resolved:** Settings and Compose semantics are specified; equivalent default and bidirectional reader checks remain unspecified for scripts and other configuration readers.
- **D5 — resolved:** generated active assignments receive semantic validation and safe-example checks.
- **Round-7 §2 — partially resolved:** editor-local checks catch structural Settings disagreement, but changes to secrets, privacy flags, gates or string-backed options can still pass.

## 2. New defects and verified behavior

**Empty parsing: no defect found.** At [§8.6, defaults](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:90), the proposed derivation matches the current Settings configuration:

| Field | `TypeAdapter.validate_strings("")` | Dotenv `KEY=` |
|---|---|---|
| `str` | `""` | `""` |
| `Path` | `Path(".")` | `Path(".")` |
| `int` | Validation error | Validation error |
| `float` | Validation error | Validation error |
| `bool` | Validation error | Validation error |

Verified with installed **pydantic-settings 2.14.2 / Pydantic 2.13.4**, using synthetic dotenv text through the dotenv source in memory; `.env` was not read. This assumes the current source configuration: `env_ignore_empty=True` would instead discard empty values and permit defaults. [Versioned dotenv implementation](https://github.com/pydantic/pydantic-settings/blob/v2.14.2/pydantic_settings/sources/providers/dotenv.py).

**P2 — new behavioral ambiguity: [§8.6, consumer domains](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:88).** Adding constants alone is harmless; making consumers enforce their membership can change behavior. Currently:

- [Supervisor](/E:/GitHub/scil/Leafi/leafi/ops/supervisor.py:460) ignores unrecognized service names.
- [Sherpa](/E:/GitHub/scil/Leafi/leafi/services/asr/sherpa.py:76) enables hotwords for any value other than `"off"`.
- [Speaker](/E:/GitHub/scil/Leafi/agent/speaker.py:31) uses go2rtc for any value other than `"local"`.

Replacing these branches with rejection or narrower membership tests changes existing configurations, potentially breaking service startup or operation. Require behavior-preserving constant extraction; “runtime never imports `domain`” does not itself ensure that.

Two **residual**, rather than newly introduced, gaps remain:

- **P2 — §8.6 defaults:** neither the `PC_INPUT_DEVICE:-DJI` fallback in [devices.yml](/E:/GitHub/scil/Leafi/config/devices.yml:23) nor script fallback defaults receive the explicitly specified agreement checks.
- **P2 — §8.6 runtime boundary:** removing `BARK_URL.secret` leaves field sets, types and defaults unchanged. The editor accepts that local manifest edit; the protection test only catches it when tests run. Unsupported string-backed options have the same limitation.

## 3. Decisions still required

- **Blocker:** complete the default/reader agreement contract for non-Compose configuration and script readers.
- **Blocker:** specify how editor-time validation detects protection and option changes that preserve Settings structure.
- **Implementer may decide:** constant organization and refactoring mechanics, while preserving existing fallback, unknown-value and ordering behavior.
- **Implementer may decide:** perform typed gate normalization in `envedit` after the standard-library loader’s shape validation; no Pydantic dependency is needed in the core loader.

### Remaining blockers before coding

- Complete non-Compose reader/default agreement.
- Close the editor’s protection/options compatibility gap.
