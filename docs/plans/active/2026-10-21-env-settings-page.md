# Design: `.env` settings page in the task editor

Status: implemented 2026-10-21 (rev 7 design, after five codex rounds and one confirming round; the confirming round's single remaining finding, marker write failure, is resolved in §2 step 7 and not re-reviewed). Rounds: `reviews/2026-10-21-codex-env-design-review-{1..6}.md`.

Implementation notes (where the code differs from the text below): enum-like keys without a registry (`ASR_HOTWORDS`, `OCR_SNAP`, `BOOK_LOOKUP`, `OCR_VERSION`, `VERIFY_MODE`, `SPEAKER_BACKEND`) take their options from `ENUMS` in `leafi/envedit.py` rather than from new `Literal` field types, so no runtime setting gains a stricter startup check; the `env-file` check's cases are tested through `envfile.health` in `tests/test_envfile.py`; a key documented in `.env.example` that no program reads (`XIAOMI_*`) is editable and labelled as such, not Unknown.

## Rev 8 (2026-10-21, owner's request): one settings manifest

Implementation review (2026-10-21, `reviews/2026-10-21-codex-env-impl-review-{1..7}.md`): the final round (Claude Opus 5.5) found that a learner's name with an apostrophe could not be stored, a regression of `setup --redact`. Canonical form therefore gains one form: a **double-quoted** value containing no `"`, `\` or `$` (python-dotenv and Compose both read it literally: no escape processing without `\`, no interpolation without `$`; proven by the Compose agreement test). The writer uses it only for values containing `'`. `OLLAMA_URL` (where the vision judge posts camera frames) and `TELEGRAM_CHAT_ID` (where snapshots go) joined the privacy floor, as did `LEAFI_NO_NETWORK` in round 5.

Status: implemented 2026-10-21 after review rounds 7–11 (`reviews/2026-10-21-codex-env-design-review-{7..11}.md`); the round-11 correction in §8.9 is not re-reviewed. Where the code differs from the text: groups and keys carry `notes` / `notes_after` so `.env.example`'s free-standing comment lines survive generation; the per-key text of `docs/architecture/config.md` was merged into `help` (that table is now a pointer); §8.7's per-constant behaviour test is a stronger static one — `tests/test_env_validators.py` asserts no runtime code reads the six new domain constants at all, so no service can behave differently because of them.

The implemented catalog (§3) reassembles each key's facts from six places: two Settings classes, `.env.example`, `docs/architecture/config.md`, `${VAR}` scans of four files, and five constant tables in `leafi/envedit.py` (`SECRET_KEYS`, `PRIVACY_KEYS`, `ENUMS`, `GATES`, `ACTIVATION`). The owner asked for one JSON file that is the only source of truth for what `.env` may contain, with each key's type and choices, so the page can render dropdowns and checkboxes from it. Rev 8 replaces §3's discovery with that manifest; §1, §2, §4's masking rule, §5's procedure and §6 are unchanged.

### 8.1 `config/env-schema.json`

```json
{
  "version": 1,
  "readers": {
    "leafi":        {"action": "restart the supervisor (Leafi console) and any running study session"},
    "habit agent":  {"action": "restart the habit agent"},
    "compose:frigate": {"action": "run scripts\\win\\apply-env.bat (recreates the Frigate container)"},
    "compose:gatus":   {"action": "docker compose up -d gatus"},
    "devices.yml":  {"action": "restart the supervisor (Leafi console) and any running study session"},
    "logon task":   {"action": "rerun scripts\\win\\install-tasks.ps1"},
    "keep.ps1":     {"action": "restart the supervisor task (keep.ps1 reads them at start)"}
  },
  "groups": [{"id": "camera", "title": "机型切换(唯一开关):…"}, …],
  "keys": {
    "SUPERVISE": {
      "group": "supervision", "type": "list",
      "options": ["docker", "camera", "frigate", "mosquitto", "gatus", "habit-agent", "ollama"],
      "default": {"leafi": "docker,camera,frigate,mosquitto,gatus"},
      "readers": ["leafi"],
      "help": "Services the supervisor keeps running; habit-agent is opt-in (it speaks on schedule).",
      "example": {"value": "docker,camera,frigate,mosquitto,gatus", "commented": true}
    },
    "PRON_AUTO_JUDGE": {"group": "study", "type": "bool", "default": {"leafi": "false"}, "readers": ["leafi"],
                        "privacy": true, "gate": {"values": ["true"]}, "help": "…"}
  }
}
```

Per key: `group` (an id from `groups`, which fixes section order and header text), `type`, `options` (`enum` and `list` only), `default` per Settings reader (as the text a reader would be given, so `"false"`, `"4"`), `readers`, `help`, `secret`, `privacy`, `gate`, `example` (the value and whether `.env.example` shows it commented). Absent booleans mean `false`. Key order inside `keys` is the order on the page and in `.env.example`.

Types and what they accept (the page renders each one; `envedit` validates with it, after the Settings type):

| `type` | Page control | Accepts | Settings annotation it must match |
|---|---|---|---|
| `text` | text box | any storable text (§1) | `str` |
| `secret` | password box, blank = unchanged | any storable text | `str` (and `secret` implied) |
| `int`, `float` | text box, numeric keyboard | the Settings type's parse | `int`, `float` |
| `bool` | dropdown `(默认) / true / false` | `true`, `false` (the page writes only these) | `bool` |
| `path` | text box | storable text | `Path` |
| `enum` | dropdown of `options` minus gated | one of `options` | `str` |
| `list` | checkboxes of `options` minus gated | comma-separated, no spaces, each item in `options`, no repeats, written in `options` order; none checked writes `KEY=` | `str` |

`gate` is data instead of code: `{"values": [...]}` refuses those values (for `list`, any of those items), `{"nonempty": true}` refuses any non-empty value (`OCR_SECOND_OPINION`, `BRAIN_LOCAL_MODEL`). Comparison is on the value as validated by the Settings type, so `yes`, `1`, `on` match a gated `"true"`. For backend keys `options` lists every backend the registry knows **including deferred ones**, and the deferred ones are listed in `gate.values`.

Keys that only compose or scripts read (`CAM_PASSWORD`, `TASK_REPEAT_MIN`'s `logon task` reader, …) are entries like any other; their defaults per non-Settings reader (Compose `${VAR:-x}`) are under `default` with the reader name. Keys documented but read by nothing (`XIAOMI_*`) have `"readers": []` and say so in `help`.

### 8.2 Who owns what, and where agreement is checked

- The **manifest** owns everything descriptive: group, order, help, type, options, readers, activation, secret, privacy, gate, example.
- The **Settings classes** keep their fields and defaults: they are what each process runs with, and type checkers and IDEs read them. A key a Settings class reads is therefore declared twice (the field and the manifest entry). That is the price of keeping runtime types static; the alternative, building the Settings classes from JSON at import, loses static typing for every `settings.x` in the code base.
- **Agreement is checked by a test, not at runtime.** `tests/test_env_schema.py` fails when: a field of either Settings class has no entry, or an entry names a Settings reader whose class has no such field; a manifest default differs from the field default (both rendered to text); `type` does not match the field annotation (table above); a `${VAR}` in `docker-compose.yml`, `config/devices.yml`, `config/gatus/config.yaml`, `config/frigate/*.yml`, or a key in `scripts/win/timing.ps1`, has no entry naming that reader; a reader has no `action`; a backend key's `options` differ from its registry's `backends ∪ deferred` or its deferred backends are not gated; a key whose name matches the credential rule is not `secret`; `.env.example` differs from the generated one (§8.3).
  - Why not inside `Settings` (a check at construction): every household service builds a Settings at start. A manifest mistake — a typo in help text's sibling field, a stale default — would then stop the supervisor, the habit agent and every study session, and the supervisor's restarts would loop on it. The manifest is documentation and page metadata; it must never be able to take a running service down. The test stops the mistake before a commit instead.
  - The page is the one runtime consumer, so `envedit` validates the manifest's own shape at load (unknown `type`, an `enum` without `options`, a `group` not in `groups`, a gate value outside `options`): on failure the settings tab shows the error and is read-only; the task tab and every other process are unaffected.
- Loader: `leafi/core/envschema.py` (standard library only: `json` and dataclasses) parses and shape-checks the manifest, so `leafi.ops` may use it later; `leafi/envedit.py` uses it instead of discovery.

### 8.3 `.env.example` is generated

`python -m leafi env-example` writes `.env.example` from the manifest: one `# ===== <group title> =====` header per group, then for each key `KEY=<example>   # <help>` (or `# KEY=<example>   # <help>` when `example.commented`), through `EnvFile`'s serialiser so the output is canonical; a key with no `example` is written with its default commented. `tests/test_env_schema.py` regenerates it and fails when the committed file differs ("run python -m leafi env-example"). The current hand-written Chinese section headers and comments move into `groups[].title` and `help` verbatim.

`docs/architecture/config.md`'s per-key table moves into the manifest's `help` (it is the richest help text today) and the page shows it; `config.md` keeps its three-roots table and the canonical-form paragraph and points to the manifest for the per-key list.

### 8.4 What is deleted

From `leafi/envedit.py`: `.env.example` and `config.md` parsing, the `${VAR}` scans (they move into the agreement test), `SECRET_KEYS`, `PRIVACY_KEYS`, `ENUMS`, `ACTIVATION`, `_gates()`. `allowed()`, `gated()` and `_kind()` read the manifest. The credential name rule stays as a test only: an Unknown key (in `.env`, not in the manifest) is still masked and offers only removal (§4).

### 8.5 Tests added or changed

`tests/test_env_schema.py` (the agreement list in §8.2, plus: the manifest loads; every gate value is in `options`; list values round-trip through the page's encoding; the generated `.env.example` is canonical and equals the committed one); `tests/test_envedit.py` keeps its behaviour tests (gates on typed values, privacy confirmation, masking, all-or-nothing) and gains: a `list` save writes items in `options` order without spaces, rejects an unknown item and a repeated item; a manifest with a bad shape makes `view` report it and `save` refuse.

### 8.6 Round-7 resolutions (these override §8.1–§8.5 where they differ)

**Gates (D1).** A gate is a list of values in the key's own Settings domain: `"gate": {"values": ["true"]}` for `bool`, `{"values": ["lexicon"]}` for `enum`, `{"values": ["ollama", "whisper"]}` for an item of a `list` or `enum`, `{"nonempty": true}` for free text. At load, each gate literal is parsed with the key's Settings `TypeAdapter` (the leafi class when both readers have the field), exactly as a submitted value is; comparison is between the two typed values, so a submitted `yes`, `1` or `on` matches the gate literal `"true"`. "Gate values ⊆ options" applies only to `enum` and `list`.

**Protection floor (D2).** Deleting the five tables must not let an edit to the manifest remove a protection silently. `tests/test_env_protections.py` holds, as plain lists written in the test (intentionally independent of the manifest), the protections that exist today: the 7 secret keys, the 9 privacy keys, and the gated cases (`PRON_AUTO_JUDGE` ∈ {true, yes, 1, on}, `ASR_HOTWORDS=lexicon`, `OCR_SNAP=auto`, `ASR_BACKEND=whisper`, `OCR_BACKEND=qwen_vl`, `BRAIN_BACKEND=ollama`, `OCR_SECOND_OPINION=x`, `BRAIN_LOCAL_MODEL=x`). It checks them **behaviourally** through `envedit.view`/`save` on a temp `.env`: each secret's canary value never appears in a response; each privacy key's change is refused without its value-bound confirmation; each gated case is refused. Removing a protection therefore needs a deliberate edit to this test, visible in review. The credential name rule also stays in that test.

**Consumer domains (D3).** Every `enum` and `list` key names the code constant that defines its domain: `"domain": "leafi.ops.supervisor:SERVICES"`. The agreement test imports it and requires `set(options) == set(domain)` (for backend keys, `domain` is the registry and the rule stays `backends ∪ deferred`). Where a consumer has no constant today, the implementation adds one in the consumer and makes the consumer use it (`OCR_VERSION` in `services/ocr/rapidocr.py`, `SUPERVISE` in `ops/supervisor.py`, `REQUIRED_CHANNELS` in `ops/checks.py`, `ASR_HOTWORDS`, `OCR_SNAP`, `BOOK_LOOKUP`, `VERIFY_MODE`, `SPEAKER_BACKEND` where they are read). The page and the runtime never import `domain`; it exists for the test.

**Defaults per reader, with the empty case (D4).** `default` becomes `{reader: {"value": "<text>", "empty": "empty" | "default" | "error" | "current-dir"}}` — what the reader does with `KEY=`. For Settings readers the test derives both from the field (`TypeAdapter.validate_strings("")`: `str` → `empty`, `Path` → `current-dir`, `int`/`float`/`bool` → `error`) and requires equality. For Compose the test parses every `${VAR…}` and requires equality both ways: `${V:-x}` ↔ `{"value": "x", "empty": "default"}`, `${V-x}` ↔ `{"value": "x", "empty": "empty"}`, `${V}` ↔ `{"value": "", "empty": "empty"}`; a manifest reader `compose:<svc>` with no matching reference fails, as does a reference with no matching reader. The page shows each reader's empty consequence before an `empty` op (as rev 7 did), and `empty` is offered only when no Settings reader has `"empty": "error"`.

**Generated example is checked for meaning (D5).** Beyond byte equality and canonical form: the active assignments of the generated `.env.example` pass the file-only Settings validation of §5 for both classes and the manifest's options; no active example sets a gated value; every privacy key's active example equals its leafi or habit default (the opt-in stays off in a copy of the example); a key with no `example` whose readers' defaults differ, or that has no default, fails the manifest shape check (an explicit `example` is required).

**Runtime boundary (round-7 §2).** Settings construction stays untouched. The settings tab loads the manifest lazily per request; besides its shape it compares the manifest with the Settings classes actually loaded (field set, type mapping, defaults): any disagreement (a deployment skew the commit-time test could not see) makes the tab read-only with the list of mismatches; the task tab and every service are unaffected.

**Implementer decisions recorded.** `list` means a finite set: written in `options` order, no spaces, no repeats; `SUPERVISE` and `REQUIRED_CHANNELS` are lists; ordered or free-form comma values (`KEEP_BACKOFF_S`, `SUPERVISOR_GRACE`, `REDACT_TERMS`) stay `text`. An existing value the page would spell differently (`yes` for a bool, a list out of order) is shown as found and rewritten only when the owner changes that key; the confirmation hash covers the value as written. `bool` writes `true`/`false`; `(默认)` is `unset`, never `KEY=`. "None checked" in a list is the `empty` op (so `KEY=''` when a comment follows). The manifest's own load failure returns `{"manifest_error": "…"}` from `GET /api/env` and refuses saves.

### 8.7 Round-8 resolutions and the `validator` field (override earlier sections where they differ)

**One agreement checker, run by the test and by the editor.** `leafi/envedit.py::agreement(manifest) -> list[str]` performs every check of §8.2 and §8.6 (fields, types, defaults with the empty case, readers both ways, `domain` options, gates, validators, the protection floor). `tests/test_env_schema.py` asserts it returns `[]`; the settings tab calls it on every load and is read-only, listing the mismatches, when it does not. So a local manifest edit that keeps the Settings structure but weakens a protection or adds an unsupported option is caught by the editor too, not only when tests run (round 8, blocker 2). Services never call it.

**Protection floor in code.** The floor lists move from the test into `leafi/envprotect.py` (`SECRET_FLOOR`, `PRIVACY_FLOOR`, `GATE_FLOOR`; plain constants, nothing else). `agreement` requires the manifest to be at least as strict (each floor secret is `secret`, each floor privacy key is `privacy`, each floor gate case is gated); `tests/test_env_protections.py` keeps the behavioural checks through `view`/`save`. The floor is a safety invariant, not a second description: weakening it is a code change in review, while the manifest stays the one place for everything descriptive.

**Every reader's default, with its own parser (round 8, blocker 1).** Each reader kind declares how its default is derived, and `agreement` checks it both ways:
- Settings readers: from the field (§8.6).
- `compose:<svc>`: from `${V:-x}` / `${V-x}` / `${V}` in `docker-compose.yml` (§8.6).
- `devices.yml`: from its `${V:-x}` / `${V}` references, interpreted by the same expansion function `leafi.core.hub` uses (called with a lookup that returns `None`, then `""`), so the manifest's `{"value", "empty"}` is whatever the hub really does.
- `config/gatus/config.yaml` and Frigate's YAML are not `.env` readers: they read container environment that Compose builds. Their `${V}` references must be covered by a `compose:<svc>` reader of the same key; they get no reader of their own.
- `scripts/win/timing.ps1` is not a `.env` reader either (it reads `python -m leafi timing --env`). Its readers stay `logon task` / `keep.ps1` for **activation only**; `agreement` requires its fallback table to equal the leafi Settings defaults for the same keys.

**Domain constants preserve behaviour.** Extracting a `domain` constant must not change any consumer's branching: the supervisor still ignores an unknown service name, sherpa still treats any non-`off` hotwords value as on, the speaker still treats any non-`local` backend as go2rtc. The constant is the set the page offers; the consumer may keep accepting more. A test per extracted constant runs the consumer's existing behaviour on one value outside the domain and asserts it is unchanged.

**`validator` (owner's request).** For a value whose rule is more than a type and a choice list:

```json
"WEEKLY_REPORT": {"type": "text", "validator": {"fn": "agent.config:parse_weekly_report", "severity": "error"}}
```

- `fn` names the **consumer's own parser**, `module:function`, taking the text and returning the parsed value or raising `ValueError` (message without the value). It is never a separate checking function, so the page and the service cannot disagree about what is valid. Where the parser is a method or inline code today, it is moved to a module-level function that the old call site now calls (behaviour unchanged; the existing tests of that consumer must stay green).
- `severity`: `error` blocks the save; `warning` saves and reports, for settings whose consumer already falls back on a bad value.
- Only modules under `leafi.` or `agent.` are accepted; the function is imported only by `envedit` when validating, never at service start.
- The validator runs after the type check and before the gate check, on `set` values only (`empty` is governed by the reader's `empty` rule; an `empty` that the validator rejects is refused when the validator's own call with `""` raises).
- `agreement` checks: `fn` resolves to a callable; it accepts every active example and every default of that key; and the consumer really calls it — the module that owns the setting's runtime use contains a call to that function name (AST search), so a validator cannot quietly drift from the code that reads the value.
- Initial validators: `WEEKLY_REPORT` and `SCHEDULE` (`agent/config.py`, from the `parsed_*` methods), `SUPERVISOR_GRACE` and `KEEP_BACKOFF_S` (`leafi/ops/timing.py`, from `_parse`, severity `warning` because the supervisor falls back), `ACTIVE_HOURS` (`leafi/ops/checks.py`, from the inline `partition`). Cross-key invariants (the timing rules) stay in §5's whole-file validation.

### 8.8 Round-9 resolutions (override §8.7 where they differ)

**Validator contract.** A validator is `fn(text: str) -> parsed`: exactly one argument, synchronous, deterministic, no I/O, no environment or Settings access, no mutation of module state; it raises `ValueError` with a message that does not contain the text. The editor calls it on the effective text and discards the result; the consumer calls the **same** function on the Settings field's text and uses the result. Validators live only in import-safe parser modules: `agent/parsers.py` (new; `parse_weekly_report`, `parse_schedule`, moved from the `parsed_*` methods, which now return `parsers.parse_…(self.weekly_report)`), and the pure functions added to `leafi/ops/timing.py` (`parse_grace(text) -> dict[str, float]` overrides only, `parse_backoff(text) -> tuple[float, ...]`) and `leafi/ops/checks.py` (`parse_active_hours(text) -> tuple[int, int]`, including both `int` conversions). `tests/test_env_validators.py` imports every validator module in a fresh subprocess (`python -I`, empty temp cwd, empty environment) and asserts the import succeeds and neither `agent.config` nor `leafi.core.config`'s `Settings()` was instantiated (no `.env` read: the temp cwd has a poisoned `.env` whose parse would raise).

**Runtime boundaries stay where they are.** `timing._parse` keeps its `try/except` and grace-default merging; it now calls `parse_grace`/`parse_backoff` inside them, so a bad value still falls back with the same problem names. `checks.build` still only stores the text; the `active_hours` check function calls `parse_active_hours` when it runs, so a bad value still fails that check, not `build()`. `parsed_weekly_report`/`parsed_schedule` keep their call sites.

**Validation depth = today's acceptance.** Each validator accepts exactly what its runtime parser accepts today (`parse_weekly_report` still accepts `noday:99:99`; `parse_schedule` still accepts `task:not-a-time`). Making them stricter is a behaviour change of the services and is out of scope; recorded as a follow-up, not done here.

**Consumer binding is behavioural, not lexical.** Each `validator` entry also names its call site: `"consumer": "agent.config:Settings.parsed_weekly_report"`. `tests/test_env_validators.py` has one test per validator that replaces the validator with a spy returning a sentinel, runs the consumer on a Settings built with a chosen text, and asserts the spy received exactly that text and the sentinel came back from (or drove) the consumer: for `timing.resolve`, the grace/backoff in the resulting `Timing`; for the `active-hours` check, the hours passed to `hours_cover`; for the habit agent, the return of `parsed_*`. The AST search of §8.7 is dropped. `agreement` checks only that `fn` and `consumer` resolve.

**Empty values, one rule.** The effective text of `set("")` and of `empty` is `""`, and both go through the same steps: the reader `empty` rule (§8.6) first, then the validator on `""` if the key has one, with its declared `severity` applied the same way as for any other text. `unset` runs no validator (the default applies; `agreement` checks every default passes its validator).

**devices.yml readers.** Discovery follows the hub's scope: only `${…}` inside `devices[*].options` values of `config/devices.yml`, each recorded with its device name. The derived consequence calls `leafi.core.hub._expand(value, lookup, missing)` with a fresh `missing` list for an absent and for an empty value: a non-empty `missing` means `"empty": "disables-device"` (and for absent, `"absent": "disables-device"`), otherwise the returned text is the default. So `default` per reader gains an optional `absent` (`"default"`, `"empty"` or `"disables-device"`) beside `empty`. The page shows "empty here disables device <name>" before an `empty` op or `unset` on such a key.

### 8.9 Round-10 resolutions (override §8.8 where they differ)

**One reader per device.** A key referenced in `config/devices.yml` gets one reader per device that references it, named `devices.yml:<device>` (like `compose:<service>`), each with its own `default` record and the activation of `leafi`. So `${V:-x}` on one device and a required `${V}` on another are two readers with two records. If one device references the same key more than once, its record is the strictest of them (`disables-device` beats a fallback).

**Consequences are attributed to the key under test only.** For key `K` in one options value, `_expand` is called with a lookup that returns the test value (`None` for absent, `""` for empty) for `K` and a fixed non-empty sentinel for every other variable; `K` disables the device only if `K` itself is in `missing`. The returned text with the sentinels removed is the fallback default. So `${A:-x}/${B}` gives `A`: default `x`, never disables; `B`: disables when absent or empty.

**Round-11 correction: one reader per reference, expanded alone.** The reader is `devices.yml:<device>.<option>` (the option key whose value holds the reference; a second reference to the same key in the same option gets a `#2` suffix), not one per device. Its default is derived by finding each `${…}` occurrence with the hub's own reference pattern and calling `_expand` on **that occurrence's text alone** (`"${A:-x}"`, not `"${A:-x}/${B}"`), so the fallback is exactly `x` and no surrounding literal or neighbour leaks in; the sentinel lookup above is then only needed for the `missing` attribution, which is per occurrence too. Two references to one key with different fallbacks are two readers with two records, so no aggregation rule is needed. (This correction closes round 11's two findings and is not re-reviewed: the review budget of five rounds for Rev 8 is spent.)

**Import safety is observed directly.** The subprocess import test installs `sys.addaudithook` before importing each validator module and fails on any `open` event whose path ends in `.env`, and replaces `pydantic_settings.BaseSettings.__init__` with a recorder that fails on any call; success of the import alone is not evidence.

**Active hours.** `parse_active_hours` is called inside the check after both registry values are read, as today (the existing short circuit on missing registry values is unchanged).

## Purpose

The owner edits `.env` by hand (`scripts\win\edit-env.bat`). Mistakes found so far: stale key names that silently stop working (`TARGET_BRUSH_SECONDS`, renamed to `TARGET_ACTIVE_SECONDS`), a key whose two readers have different defaults (`GO2RTC_URL`: 2984 in `leafi`, 1984 in `agent`), and no hint about which service must restart. The owner asked for a page in the task editor (`python -m agent.webui`, `http://127.0.0.1:8770`) that edits `.env`, with secrets masked.

Done means: the owner sees every known setting with its source text (secrets as "set / not set" only), per-reader defaults, help, and readers; edits the settings the page can edit safely; saves; and is told exactly what to do for each change to take effect. Bytes the page did not change stay byte-identical.

## Non-goals

- Editing `config/devices.yml` or `config/tasks.yml`.
- Running restarts from the page. It names the action; the owner runs it.
- Being a general `.env` editor. The page edits a **safe subset** (§1) and diagnoses the rest; anything outside it is edited by hand.
- Remote access or authentication beyond what a loopback tool needs (§6).
- Changing any setting's meaning, default or release gate (§3).

## Context

- Readers of `.env`, each with its own parser:
  - `leafi/core/config.py::Settings` and `agent/config.py::Settings`: pydantic-settings 2.14 over python-dotenv 1.2.2, case-insensitive keys, process environment wins over the file.
  - Docker Compose (`docker-compose.yml`): its own parser, case-sensitive, interpolates `$VAR` and `${VAR}` in unquoted and double-quoted values, `${VAR:-x}` defaults.
  - `config/devices.yml` (`leafi.core.config.env_lookup`, environment first) and `config/gatus/config.yaml`.
  - Frigate (only when the container is recreated: `scripts\win\apply-env.bat`).
  - `scripts/win/timing.ps1` (`KEEP_*`, `TASK_REPEAT_MIN`), used by `keep.ps1` and `install-tasks.ps1`.
- python-dotenv 1.2.2 facts, checked by probe on 2026-10-21: `${A}` is expanded in unquoted, double- **and single-quoted** values; bare `$A` is not expanded; for a duplicated key the last line wins; a UTF-8 BOM becomes part of the first key (`﻿FIRST`), so that key silently does not work.
- The only existing programmatic writer is `leafi/cli.py::cmd_setup`; it rewrites with `\n` endings and moves `REDACT_TERMS` to the end. It moves onto the shared writer (§2).
- `tests/test_architecture.py`: `leafi.core` imports nothing from devices/services/study; `leafi.ops` imports only core/devices; only `leafi/core/config.py` reads `os.environ`. `agent → leafi` is an accepted direction (`agent/speaker.py`).
- `agent/webui` already imports `agent.config.settings`, which validates the live `.env` at import; a malformed habit value already stops the editor from starting. Unchanged by this design (accepted; the page's own validation prevents saving such a value).

## Design

### 1. Canonical form (`leafi/core/envfile.py`, pure: bytes in, bytes out, stdlib only)

Rounds 1 and 2 showed that recognising the readers' dialects line by line keeps missing syntax (interpolation in single quotes, backslash escapes, Compose's `KEY: value`, indented keys). So the page does not recognise dialects: it writes only to a file that is entirely in **canonical form** (a term of this design), whose every line all readers provably read the same way. The owner's `.env` was canonical on 2026-10-21.

A file is canonical when it is valid UTF-8 without a BOM, uses one newline style throughout, and every line is exactly one of:

| Line | Grammar (whole line) |
|---|---|
| blank | empty |
| comment | `#` in column 0, then anything (this includes commented assignments `# KEY=…`) |
| assignment | `KEY=VALUE` or `KEY=VALUE<spaces>#comment`, with `KEY` = `[A-Z][A-Z0-9_]*` in column 0 and `VALUE` either *bare* `[A-Za-z0-9_./:@,+=%-]*` or *single-quoted* `'[^'\\\r\n]*'` containing no `${`; an **empty bare** value (`KEY=`) must end the line (both parsers skip the spaces after `=`, so `KEY=   # note` reads as the text `# note`, verified with python-dotenv 1.2.2); an inline `#comment` contains no `$` (Compose expands `$$` in what it takes as value text) |

and no key has more than one assignment line. Nothing else is canonical: no leading whitespace, `export`, double quotes, backslashes, `${`, unquoted `$` or `#` inside a value, lower-case or mixed-case keys, `:` assignments.

Why every reader agrees on a canonical line: a bare value contains no quote, escape, `$`, space or `#`, so python-dotenv, pydantic-settings and Compose all take it verbatim; a single-quoted value contains no `'` or `\` (python-dotenv's only single-quote escapes), no newline, and no `${` (the only form python-dotenv expands in single quotes; Compose expands nothing in single quotes). A `#` in column 0 is a comment for all three. Because a canonical file contains no `${`, no reader interpolates anything, so whole-file validation (§5) cannot consult the process environment through interpolation.

If the file is **not** canonical, the page is read-only and shows no values: a banner lists each offending line by number, key name (if any) and rule broken ("leading space", "double quotes", "backslash", "duplicate of line 12", "empty value followed by a comment: readers see the comment as the value"), and says "fix these lines by hand (scripts\win\edit-env.bat), then reload".

**`.env.example` is fixed in the same change**: today `XIAOMI_USERID`, `XIAOMI_DID`, `BARK_URL`, `CHILD_FACE_LABEL` and `REDACT_TERMS` are written `KEY=   # help`, so a copy of the example sets them to their help text (verified 2026-10-21; the owner's `.env` does not have this shape). They become `KEY=''   # help`. A test keeps `.env.example` canonical.

**Agreement tests** (the proof, not a model): for generated canonical files including adversarial values (`%`, `=`, `@`, `:`, `$x`, `#` inside single quotes, trailing `+`), python-dotenv `dotenv_values` and — when docker is installed — `docker compose --env-file <f> config --environment` return the same text for every key, and both Settings classes validate the typed value of that same text; for each non-canonical example from rounds 1–2 (`'a\\b'`, `KEY: v`, ` KEY=v`, `"x${Y}"`, BOM, CRLF+LF mix, `'a\'`) the file is rejected as non-canonical.

Writing a value: bare if it is non-empty and matches the bare class; `''` if it is empty and the line keeps an inline comment; `KEY=` if it is empty and the line has no comment; else single-quoted. A value containing `'`, `\`, `${`, a newline, a NUL or a character outside printable UTF-8 is **rejected** with "cannot be stored so that every reader reads the same text; edit by hand". The written file is canonical by construction, and `apply` asserts it (re-checks canonical form of its own output).

Operations, on catalog keys of a canonical file:

| Op | Effect |
|---|---|
| `set v` | replace only the value of the key's one assignment line, keeping any trailing ` #comment`; if the key has no assignment line, insert one per placement below |
| `empty` | `set ""` (serialised as above: `KEY=`, or `KEY=''` when the line keeps a comment); the page shows each reader's consequence first (§3) |
| `unset` | turn the key's one assignment line into a comment (`# KEY=…`); canonical form guarantees there is no second assignment to take its place; the page states that process environment and per-reader defaults then apply |

Placement of a new line: directly below the last commented assignment of the same key if one exists; else at the end of the section the catalog names (§3: the section header text from `.env.example`, injected as data, matched by exact line text, first match); else at the end of the file under a `# ===== Added by the settings page =====` header (created once). The newline style is the file's one style (an empty file gets `\n`, which the owner's `.env` uses); a missing final newline is added only when a line is appended after it.

`EnvFile.parse(raw) → EnvFile`, `.problems() → [LineProblem(line, key|None, rule)]` (empty ⇔ canonical), `.values() → {KEY: text}`, `.apply(ops, placement) → EnvFile` (raises `NotCanonical` when `problems()` is non-empty, `Unstorable(KEY)` for a rejected value), `.render() → bytes` (byte-identical when no op), `.digest()` (sha256). Placement anchors are passed in as data; `envfile` reads no other file.

### 2. One writer for every program (`leafi/core/envfile.py::update_env`)

```python
def update_env(path: Path, expected_digest: str, transform: Callable[[bytes], bytes], backup_dir: Path) -> str
```

`transform` receives the current bytes and returns the new bytes or raises; the caller supplies apply + validation (§5) in it, so `envfile` stays stdlib-only and the transaction stays in one place.

1. Lock: open `.env.lock` (gitignored, never deleted) and take an OS byte-range lock on it (`msvcrt.locking(LK_NBLCK)` retried for up to 5 s on Windows, `fcntl.flock` elsewhere). The OS releases it when the holder's process dies, so there is no stale-lock stealing. Inside the server a process-wide `threading.Lock` is taken first.
2. Read the bytes. A missing file has the digest `"absent"` and the bytes `b""`. If `digest != expected_digest` → `Conflict` (no write).
3. `new = transform(old)`; any exception → abort, nothing written.
4. Backup (existing file only): `backup_dir/.env.<stamp>.bak` with `stamp = max(time.time_ns(), largest existing stamp + 1)` chosen under the lock (unique and increasing even if the clock steps back), exclusive create, keep the 5 with the largest stamps. The backup gets `.env`'s security descriptor before any byte is written (`protect_like(dst, src)`, below). Any failure → abort.
5. Temp: `tempfile.mkstemp(dir=path.parent, prefix=".env.", suffix=".tmp")`, `protect_like(tmp, path)` before writing, write, `fsync`, **close** the handle.
6. Install, then classify the outcome by **what `.env` holds afterwards**, never by which call raised:
   - **Missing file**: `os.link(tmp, path)` (fails if `path` appeared meanwhile → `Conflict`), then remove `tmp`. The new `.env` has the directory's inherited permissions, like a file made by `edit-env.bat`'s `copy`.
   - **Windows, existing file**: `ReplaceFileW(path, tmp, side, 0, …)` with `side = .env.<random>.side` in the same directory and **no** ignore-merge flag, so a failure to carry the ACL is a failure. `ERROR_UNABLE_TO_MOVE_REPLACEMENT_2` means `.env` is now at `side` with its own ACL: restore with one `os.replace(side, path)` (a rename keeps the file's ACL). There is **no** other fallback: nothing is copied over `.env` by this code. Every other error leaves `.env` with the old bytes.
   - **Elsewhere**: `os.replace(tmp, path)` (mode already copied in step 5).
7. Outcome. `Conflict` (the digest check of step 2, or `os.link` raising `FileExistsError`) is decided first and means nothing was written. Otherwise read `path` back (absent counts as a state) and compare with the state before (old bytes, or absent) and the new bytes:

   | `.env` afterwards | Result | Cleanup |
   |---|---|---|
   | new bytes | `Committed(digest, warnings)` | remove `tmp` and `side` if present; a cleanup failure becomes a warning naming the leftover file, never a failure |
   | same as before (old bytes, or still absent on first creation) | `RolledBack(reason)` — means "nothing written" | remove `tmp` and `side` if present (warning on failure) |
   | anything else (absent when it existed, other bytes) | `RecoveryRequired(paths)` | **remove nothing**; write `data/env-recovery.json` (`{time, side, tmp, backup}` — paths only, exclusive create, with a numbered name if one exists); log `CRITICAL` with the same paths |

   The supervisor's `env-file` check fails while any `data/env-recovery*.json` exists, **or** any `.env.*.side` or `.env.*.tmp` older than 60 s exists beside `.env` (a recovery state removes nothing, so these are always left; the age skips a save in progress), **or** `.env` is missing, **or** `.env` is not canonical. Detection therefore needs no write: if the marker cannot be created (disk full), `save` still returns `RecoveryRequired` and logs `CRITICAL`, and the leftover files raise the alert. The marker only carries the paths for the owner. The owner restores by hand (`side` is the old file with its ACL; the backup holds the old bytes) and deletes the marker; the check then passes. The check is registered the ADR-0016 way: a `CHECKS` entry, its down/up catalog sentences in `leafi/core/alerts.py`, and its Gatus endpoint in `config/gatus/config.yaml`, so `tests/test_checks.py`'s catalog and dashboard coverage tests stay green.

8. Release the lock (closing the handle).

The HTTP mapping (§6): `Committed` → 200 `{ok:true}`; `RolledBack` → 200 `{ok:false}`; `Conflict` → 409; `RecoveryRequired` → 500 `{ok:false, recovery:{marker, side, tmp, backup}}` (file names, never contents). `cmd_setup` prints the same and exits non-zero for all but `Committed`.

`protect_like(dst, src)`: Windows: read `src`'s DACL with `GetFileSecurityW(DACL_SECURITY_INFORMATION)` and apply it with `SetFileSecurityW`; elsewhere `shutil.copymode`. A failure aborts the save, so a backup or temp file is never less protected than `.env`. When `src` is absent (first creation) it is a no-op.

`cmd_setup --redact` goes through the same coordinator as the page (§5) with the digest it just read (`"absent"` when there is no `.env`, keeping today's create-if-missing behaviour); the explicit command is its own confirmation for `REDACT_TERMS`, so the CLI builds the `confirm` entry itself. An external editor saving between steps 2 and 6 is the one race left (milliseconds; the editor reports the file changed on disk). Accepted.

Stated plainly: `unset`, rotation and every save leave previous values in a comment (`unset`) and in the five backups (under `data/`, gitignored, never served by the page).

### 3. The catalog and the save coordinator (`leafi/envedit.py`, outer ring beside `cli.py`)

`leafi/envedit.py` may import service registries, both Settings classes, `leafi.ops.timing` and read repository files. It exposes `catalog() -> Catalog`, `view(raw) -> dict` (the GET body) and `save(path, digest, ops, confirm) -> SaveResult`, which builds the `transform` (apply → §5 checks) and calls `update_env`. Both the page and `cmd_setup` call `save`. `leafi.core.envfile` receives anchors as plain data. Catalog keys = union of:

| Source | Gives |
|---|---|
| `leafi.core.config.Settings.model_fields`, `agent.config.Settings.model_fields` (class attributes; no instance) | type, default per class, reader `leafi` / `habit agent` |
| `.env.example` (`KEY=` and `# KEY=` lines) | section (nearest `# =====` header), order, inline help |
| `docs/architecture/config.md` table rows (`` `KEY` ``, `` `A` / `B` `` forms) | help when `.env.example` has none |
| `${KEY…}` in `docker-compose.yml` (with the service it belongs to), `config/devices.yml`, `config/gatus/config.yaml`, `config/frigate/*.yml` | reader `compose:<service>` / `devices.yml` / `gatus` / `frigate`; Compose default (`:-x`: absent **or empty** → x; `-x`: absent → x) |
| `scripts/win/timing.ps1` defaults table | reader `logon task` (`TASK_REPEAT_MIN`) / `keep.ps1` (`KEEP_*`) |
| keys present in `.env` and in none of the above | group **Unknown**: "no reader found — probably a stale name" |

Keys with no `.env.example` section go to groups named by reader ("Study and ops (leafi)", "Habit agent", "Compose only"), alphabetical.

Defaults are shown **per reader**; a placeholder Compose default (`change-me`) is flagged: "absent or empty here means Gatus uses `change-me`".

**Activation**: a table in the catalog maps reader → action; key-specific rows override it.

| Reader | Action |
|---|---|
| `leafi` | restart the supervisor (Leafi console: restart supervisor) and any running study session |
| `habit agent` | restart the habit agent |
| `devices.yml` | as `leafi` |
| `compose:frigate`, `frigate` | `scripts\win\apply-env.bat` (recreates the container) |
| `compose:<other>`, `gatus` | `docker compose up -d <service>` |
| `logon task` (`TASK_REPEAT_MIN`) | rerun `scripts\win\install-tasks.ps1` |
| `keep.ps1` (`KEEP_*`) | restart the supervisor task (keep.ps1 reads them at start) |

A test fails when a reader found by discovery has no row, so a new reader cannot be added without an activation rule.

**Release gates** (ADR-0011 and ADR-0003): a `GATES` table in the catalog lists, per key, a predicate on the **typed** value (after pydantic validation, so `yes`, `1`, `on` and `true` are all `True`): `PRON_AUTO_JUDGE is True`, `ASR_HOTWORDS == "lexicon"`, `OCR_SNAP == "auto"`, `ASR_BACKEND`/`OCR_BACKEND` in the registry's `deferred`, `BRAIN_BACKEND == "ollama"`, `OCR_SECOND_OPINION != ""`, `BRAIN_LOCAL_MODEL != ""`. `save` rejects any op whose typed result matches a gate (server-side; the page also never offers it). A gated value already in the file is shown with "gated by ADR-0011 — change by hand only after its evaluation", and the page accepts only `unset` for that key. Enum-like keys are validated server-side against registry `backends` minus `deferred` (or a `Literal` added to the Settings field), after the same normalisation the reader applies (none: pydantic `str` is case-sensitive, so `Sherpa` is rejected, not accepted and later failing at startup).

**Privacy keys** (ADR-0011: changing them changes what may leave the house): `NOTIFY_WITH_SNAPSHOT`, `BOOK_LOOKUP`, `AUDIO_KEEP_CLIPS`, `EVAL_TRANSCRIPTS`, `REDACT_TERMS`, `BRAIN_BACKEND`, `STUDY_BRAIN_MODEL`, `TTS_BACKEND_EN`, `TTS_BACKEND_ZH`. A save that changes one must carry a confirmation for that key bound to the exact new value (§4); `REDACT_TERMS` is shown (the owner must read it) and never logged.

### 4. Secrets

A key is secret if its upper-cased name is in `SECRET_KEYS` (`TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`, `CAM_PASSWORD`, `TAPO_CLOUD_PASSWORD`, `GATUS_TOKEN`, `BARK_URL`, `HEARTBEAT_URL`) **or** its name matches `(?i)(TOKEN|PASSW|SECRET|KEY|CREDENTIAL|PRIVATE)` **or** it is in the Unknown group. In a canonical file no value references another, so masking a key's own lines (active and commented) is complete. In a non-canonical file the page shows no values at all, only the problem list (§1), so nothing is resolved or echoed.

The API never returns a secret's value: only `state` (`set`, `empty`, `default`). The page's input for a secret is a password field whose blank means "unchanged"; pending secret input lives only in page memory. A test fails when a key in `.env.example` or either Settings class matches the name rule but is missing from `SECRET_KEYS` (keeping the table honest for help text and docs).

### 5. Validation (in `envedit.save`'s `transform`, under the lock, on the candidate bytes)

0. The ops body is checked first: `set` requires a string `value`; `empty` and `unset` reject `value`; any other field → 400.
1. Per changed key with a Settings field: for `set`/`empty`, `TypeAdapter(annotation).validate_strings(value)` for each class that has it; type errors block the save. `unset` is not string-validated (each reader's default applies; step 2 validates the result). Then allowed values and `GATES` on the typed value (§3).
2. Whole-file: the candidate is canonical (asserted by `apply`), so it contains no `${` and parsing cannot consult the process environment. `EnvFile.values()` gives a plain dict; both Settings classes are validated from it with `Model.model_validate(values_lowercased)` on validation-only subclasses whose `settings_customise_sources` returns only the init source — no environment, no dotenv file, no temp file. Errors block the save. Then `leafi.ops.timing` validation; its conflicts are warnings (the runtime already falls back and alerts).
3. Process overrides: `leafi.core.config.env_overrides(keys) -> list[str]` (in `config.py`, the one module allowed to read `os.environ`) returns which changed keys the **editor's** environment shadows; the page warns "this process has KEY set in its environment; a service started the same way will ignore the file value". Names only.
4. Errors returned to the page name the key and the rule ("not an integer", "not an allowed value: …"); they never echo the value, the file or a traceback. The server logs exceptions with key names only.

### 6. HTTP API (in `agent/webui/__main__.py`) and request checks

```
GET  /api/env -> {digest, problems?:[{line, key?, rule}], groups:[{name, keys:[{key, state, value?, editable, reason?, defaults:{reader: value}, help, readers, activation, secret, privacy, gated?, allowed?}]}]}
POST /api/env <- {digest, ops:{KEY: {op:"set"|"empty"|"unset", value?}}, confirm:{KEY: sha256(value)}}
     -> {ok:true, digest, activation:[…], warnings:[…]}       (Committed)
      | {ok:false, errors:{KEY: msg}}                         (validation or RolledBack: nothing written)
      | 409 {error:"changed on disk"}                         (Conflict: nothing written)
      | 500 {ok:false, recovery:{marker, side, tmp, backup}}  (RecoveryRequired: the page shows the paths and the steps of §2, and stays read-only until reload)
```

- With `problems` present (non-canonical file) every key is `editable:false`, no `value` is sent and POST returns `{ok:false, errors:{"*": "file is not canonical"}}`.
- `value` is present only for non-secret keys of a canonical file.
- `KEY` must be a catalog key; Unknown and gated keys accept only `unset`. Unknown fields in the body → 400.
- `confirm[KEY]` must equal the sha256 of the UTF-8 bytes of the submitted value (or of `""` for `empty`/`unset`), so a confirmation cannot authorise a different value after a 409 reload; on 409 the page keeps pending edits in memory, clears confirmations, and shows a diff against the reloaded values before allowing save.
- `/api/env` and the existing `/api/tasks` (POST) both pass these checks, else 403 with no detail:
  1. `Host` equals `127.0.0.1:<port>` or `localhost:<port>`, `<port>` being the server's bound port (so tests on an ephemeral port work); also checked on `GET /` because it serves the token;
  2. POST: `Content-Type: application/json`; `Origin`, when present, is `http://127.0.0.1:<port>` or `http://localhost:<port>`;
  3. POST: `X-Leafi-Token` equals a random token (`secrets.token_urlsafe(32)`) made at server start and embedded in the served `index.html`.
  No CORS headers are ever sent.

### 7. Page

A second tab "设置 (.env)" in `index.html` (the UI is Chinese; help text as found). A non-canonical file shows only the problem list and the hint to fix by hand. Otherwise, per key: input by type (checkbox, select of allowed values, number, text, password for secrets), per-reader defaults, readers and activation as tags, a lock icon with the reason for gated and Unknown keys, a reset button (`unset`). A footer lists pending changes ("KEY: old → new", secrets "changed"), a confirmation checkbox per privacy key, Save; after save, the activation list and warnings.

## Tests (storage-touching: real files in a temp directory, never mocked)

- `tests/test_envfile.py`: no-op round trip byte-identical (CRLF, LF, `.env.example`); `.env.example` is canonical and every key in it reads (python-dotenv) as the text the grammar says — in particular the five `KEY=''   # help` lines read as empty; each op changes only the expected lines; every non-canonical example from rounds 1–3 (BOM, mixed newlines, leading space, `export`, double quotes, `'a\\b'`, `'a\'`, `KEY: v`, `${X}` in any quoting, lower-case key, duplicate, `KEY=   # note`, `KEY=x # $$`) yields a problem and makes `apply` raise; `empty` on a line with a comment writes `KEY=''  # …` and reads back empty; serialisation rejects `'`, `\`, `${`, newline, NUL; the agreement tests of §1 compare raw parser text (python-dotenv vs Compose) and, separately, typed values of both Settings classes; `update_env`: conflict, `"absent"` creation and its conflict when the file appears, backup rotation to 5 across saves within one millisecond, temp file removed after an injected failure, two processes (not threads) serialised by the OS lock, a killed holder releases it; Windows only: an explicit ACE set with `icacls` on the target survives a save and is present on the backup, and each ReplaceFileW outcome, injected through a fake that first produces the documented file state for real (rename `.env` to `side` for `_2`, etc.), ends in the table's result: `_2` with restore → `RolledBack` and old bytes; `_2` with a failing restore → `RecoveryRequired`, `side`, `tmp` and backup still on disk, marker written; success with an undeletable `side` → `Committed` plus a warning; `os.link` success with an undeletable `tmp` → `Committed` plus a warning; `os.link` raising `FileExistsError` → `Conflict`; `os.link` raising another error with `.env` still absent → `RolledBack`. `tests/test_checks.py`: the `env-file` check fails on a missing `.env`, a non-canonical `.env`, a canonical `.env` with a recovery marker present, and a canonical `.env` with a 2-minute-old `.env.x.side` and no marker (marker write failed); passes with a 10-second-old `.env.x.tmp` and after the leftovers are removed.
- `tests/test_envedit.py`: `cmd_setup` keeps line endings and position; gates reject `PRON_AUTO_JUDGE=yes`, `=1`, `=on`; `ASR_BACKEND=whisper` and `=Sherpa` rejected; whole-file validation ignores a conflicting value set in `os.environ` (monkeypatched).
- `tests/test_envcatalog.py`: every key of both Settings classes, `.env.example` and the `${…}` files is catalogued; activation row exists for every discovered reader; gated values never in `allowed`; secret-name rule vs `SECRET_KEYS`; `TARGET_BRUSH_SECONDS` in a sample file is Unknown and masked; `GO2RTC_URL` shows both defaults; `GATUS_TOKEN` shows the `change-me` Compose fallback.
- `tests/test_webui_env.py` (in-process server, ephemeral port, temp cwd): canary secret never in any response body or log record; 409 on stale digest; all-or-nothing on one bad value; privacy change without, or with a mismatched, confirmation rejected; Host / Content-Type / Origin / token each → 403, also on `/api/tasks`; nothing written outside the temp directory.
- `tests/test_architecture.py` gains: `leafi/core/envfile.py` imports only the standard library; `leafi/envedit.py` is not imported by `leafi.core`, `leafi.ops` or `leafi.study`.

## Resolved questions (rounds 1–2)

Placement as in §1 with injected anchors; the §6 checks also cover `/api/tasks`; backups accepted with the stated retention and a random suffix; reader disagreement is avoided by canonical form (whole file, not per line) and proven by agreement tests rather than modelled; locks are OS locks, never stolen by age; validation lives in the outer coordinator and reaches the writer as a `transform`; gates are enforced on typed values server-side.
