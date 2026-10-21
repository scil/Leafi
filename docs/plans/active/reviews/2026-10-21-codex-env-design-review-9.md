# Codex design review, round 9 — rev 8 §8.7 incl. validator (gpt-6-astra, reasoning high, read-only)

Run 2026-10-21. Prompt: prompts/env-round-9.md.

## 1. Round-8 blockers

- **Non-Compose reader/default agreement — partially resolved:** reader derivations are specified, but the devices reader’s missing-value consequence remains unrepresented.
- **Editor-time protection/options agreement — resolved:** the shared checker and independent code floor close the identified gap.
- **Related behavior-preservation ambiguity — resolved:** §8.7 explicitly preserves fallback and unknown-value behavior when extracting domain constants.

## 2. Defects in §8.7

**Validator imports and calls are not guaranteed safe.** Restricting `fn` to `leafi.*` or `agent.*` does not establish purity. Specifically, importing the proposed `agent.config:parse_weekly_report` executes [`settings = Settings()`](/E:/GitHub/scil/Leafi/agent/config.py:69), potentially reading ambient environment and `.env` or failing before validation. The contract needs import-safe parser modules and deterministic, synchronous functions with no I/O, global Settings access, or mutation. Merely calling something a parser does not enforce these properties.

**Sharing a callable does not establish equivalent validation.** Require exactly one text argument, identical input preparation, and runtime use of the returned value. The editor should discard the parsed result after checking validity; runtime should consume it. Otherwise different arguments, ambient Settings, or ignored results permit disagreement.

Concrete extraction problems:

- [`timing._parse(settings)`](/E:/GitHub/scil/Leafi/leafi/ops/timing.py:85) accepts a Settings object and catches parsing failures itself. The shared functions must extract the individual raising parsers, preserving grace-default merging and leaving fallback handling in the runtime wrapper.
- [`ACTIVE_HOURS`](/E:/GitHub/scil/Leafi/leafi/ops/checks.py:156) uses `partition` during construction but converts both endpoints with `int` later, after registry reads. Extracting only `partition` validates nothing. Moving conversion into `build()` can turn a deferred check failure into a construction failure. Specify the complete parser and preserve its runtime execution boundary.
- [`parsed_weekly_report` and `parsed_schedule`](/E:/GitHub/scil/Leafi/agent/config.py:49) are permissive: the former accepts `noday:99:99`; the latter accepts `task:not-a-time`. Behavior-preserving extraction alone cannot promise complete semantic validity. State whether validation covers existing parser acceptance or stronger rules.

**The AST check is easily satisfied vacuously.** A dead branch containing `parse_weekly_report("sun:20:45")` passes a name search. So can an unrelated call, a shadowed function name, or a call whose result is discarded while old parsing remains. This is a useful wiring lint, not proof of agreement. Require explicit consumer bindings and behavioral regression coverage demonstrating that the relevant setting reaches the shared parser and its result drives runtime behavior.

**Empty-value severity is contradictory.** The text says validators run on `set` only, then requires calls for `empty`; it also says any rejection of `""` refuses the operation, despite `warning` permitting saves. Define one policy for effective empty text, including `set("")`, and apply severity consistently. Otherwise equivalent values can have different outcomes depending on the operation used.

**The hub helper exists, but its string result is insufficient.** [`_expand(value, lookup, missing)`](/E:/GitHub/scil/Leafi/leafi/core/hub.py:59) can be called as proposed with an additional fresh `missing` list. Both absent and empty values select the fallback for `${V:-x}`. For `${V}`, both return `""` **and record a missing requirement**; the caller then disables the device. The existing `empty` vocabulary cannot distinguish ordinary empty text from device disablement. Reference discovery must also follow the actual expansion scope—device `options`, not arbitrary YAML strings.

## 3. Decisions still required

- **Blocker:** define the validator execution contract, including import safety, purity, argument normalization, return-value use, and preserved runtime fallback/error boundaries.
- **Blocker:** replace the AST check’s claimed guarantee with explicit consumer binding and behavioral verification; define the intended validation depth for the initial parsers.
- **Blocker:** reconcile `set("")`/`empty` execution and error/warning severity.
- **Blocker:** represent and verify the devices reader’s missing-required-value consequence.
- **Implementer may decide:** parser names and module placement, AST tooling, script-table extraction mechanics, and whether to expose `_expand` publicly.

### Remaining blockers before coding

1. Safe, equivalent validator execution and meaningful consumer verification.
2. Consistent empty-value severity.
3. Devices-reader missing/disabled semantics.
