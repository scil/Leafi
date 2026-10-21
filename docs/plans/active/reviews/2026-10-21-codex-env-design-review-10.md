# Codex design review, round 10 — rev 8 §8.8 (gpt-6-astra, reasoning high, read-only)

Run 2026-10-21. Prompt: prompts/env-round-10.md.

## 1. Round-9 blockers

- **Validator execution contract — resolved:** purity, input, result use, validation depth and runtime boundaries are specified.
- **Consumer binding — resolved:** behavioral spy tests replace the insufficient AST check.
- **Empty-value severity — resolved:** `set("")` and `empty` share validation and severity.
- **Devices-reader consequences — partially resolved:** disablement is represented, but per-reference differences remain ambiguous.

## 2. New defects in §8.8

- **Medium — [devices derivation, line 138](E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:138):** a nonempty `missing` list does not necessarily implicate the key being examined. For `${A:-x}/${B}`, an all-missing lookup records `B`; attributing disablement to empty `A` is wrong. Derive consequences per reference or isolate the target key.
- **Medium — same location:** one `default["devices.yml"]` record cannot express `${V:-x}` on one device and required `${V}` on another. Recording device names does not define how these different defaults and consequences fit the manifest.
- **Low — [import test, line 128](E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:128):** successful import with poisoned `.env` does not prove that no read occurred; an exception could be caught. Directly detect forbidden reads and Settings construction.

## 3. Implementability of Rev 8

**No—one important decision remains.**

- **Blocker:** define how differing device-reference defaults and consequences are represented and checked, with missing requirements attributed to the correct key.
- **Implementer may decide:** the subprocess instrumentation that directly verifies import safety.
- **Implementer may decide:** preserve the existing active-hours short circuit by parsing only after both registry values exist, as required by unchanged behavior.

### Remaining blockers before coding

- Devices-reader representation and derivation for multiple references.
## 1. Round-9 blockers

- **Validator execution contract — resolved:** purity, input, result use, validation depth and runtime boundaries are specified.
- **Consumer binding — resolved:** behavioral spy tests replace the insufficient AST check.
- **Empty-value severity — resolved:** `set("")` and `empty` share validation and severity.
- **Devices-reader consequences — partially resolved:** disablement is represented, but per-reference differences remain ambiguous.

## 2. New defects in §8.8

- **Medium — [devices derivation, line 138](E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:138):** a nonempty `missing` list does not necessarily implicate the key being examined. For `${A:-x}/${B}`, an all-missing lookup records `B`; attributing disablement to empty `A` is wrong. Derive consequences per reference or isolate the target key.
- **Medium — same location:** one `default["devices.yml"]` record cannot express `${V:-x}` on one device and required `${V}` on another. Recording device names does not define how these different defaults and consequences fit the manifest.
- **Low — [import test, line 128](E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:128):** successful import with poisoned `.env` does not prove that no read occurred; an exception could be caught. Directly detect forbidden reads and Settings construction.

## 3. Implementability of Rev 8

**No—one important decision remains.**

- **Blocker:** define how differing device-reference defaults and consequences are represented and checked, with missing requirements attributed to the correct key.
- **Implementer may decide:** the subprocess instrumentation that directly verifies import safety.
- **Implementer may decide:** preserve the existing active-hours short circuit by parsing only after both registry values exist, as required by unchanged behavior.

### Remaining blockers before coding

- Devices-reader representation and derivation for multiple references.
