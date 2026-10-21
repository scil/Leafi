# Codex design review, round 11 — confirming, rev 8 §8.1-8.9 (gpt-6-astra, reasoning high, read-only)

Run 2026-10-21. Prompt: prompts/env-round-11.md.

## 1. Round-10 items

- **Blocker — partially resolved:** per-device readers and key-specific disablement are defined; fallback derivation and repeated-reference aggregation remain defective.
- **Import-safety instrumentation — resolved:** §8.9 specifies direct observation of `.env` opens and `BaseSettings` construction.
- **Active-hours short circuit — resolved:** §8.9 explicitly preserves it.

## 2. Contradictions or new defects

- **Medium — [§8.9, line 144](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:144):** the algorithm contradicts its example. `_expand("${A:-x}/${B}", …)` produces `x/<sentinel>`; removing the sentinel leaves `x/`, **not `x`**. Extracting the key’s fallback requires distinguishing literal surrounding text from the reference.
- **Medium — [§8.9, line 142](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:142):** “strictest” resolves disablement versus fallback, but cannot choose between `${V:-x}` and `${V:-y}` on the same device. One `default.value` still cannot represent both; aggregation and agreement checking remain undefined.

The ordered overrides otherwise reconcile §§8.1–8.9, but these cases leave the final reading ambiguous.

### Remaining blockers before coding

- Define reference-level fallback extraction and representation/checking of differing fallbacks within one device.
