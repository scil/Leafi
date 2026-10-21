# Codex design review, round 1 — .env settings page (gpt-6-astra, reasoning high, read-only)

Run 2026-10-21 against docs/plans/active/2026-10-21-env-settings-page.md (first draft). Prompt: prompts/env-round-1.md. Claude verified the python-dotenv 1.2.2 claims by probe: `\` expands inside single quotes, bare `\` does not, a UTF-8 BOM becomes part of the first key, the last duplicate wins.

## 1. Defects

Read the full design and all requested files, limiting `leafi/cli.py` to `cmd_setup`. I did not read `.env`. Synthetic, in-memory probes confirmed the python-dotenv behaviors below.

1. **High — Design §1, `Unset` and duplicates.** Commenting out the last assignment exposes an earlier assignment; it does not restore the default. For example, unsetting the last line of `NOTIFY_WITH_SNAPSHOT=true` followed by `NOTIFY_WITH_SNAPSHOT=false` enables snapshots. Unset must deactivate **all applicable assignments**, with their locations shown before saving.

2. **High — Design §1, quoting and “effective value.”** The proposed serializer changes literal values containing interpolation syntax. Writing `CAM_PASSWORD="abc$NAME"` permits Compose interpolation; `${NAME}` also expands in python-dotenv. Local probes confirmed that **single quotes do not suppress `${...}` expansion in python-dotenv**, so switching quote styles is insufficient. Separate literal source text from resolved values and define a supported cross-reader serialization policy; reject edits that cannot round-trip faithfully.

3. **High — Design §§2–4, secret classification and key identity.** The fixed uppercase secret table misses unknown credentials such as `OLD_TELEGRAM_BOT_TOKEN`; the build-time test never examines unknown keys in the owner's file. The Settings models also default to case-insensitive matching, so `telegram_bot_token` is a working credential even though the design specifies no corresponding masking or duplicate rule. Normalize classification appropriately, preserve spelling on disk, and mask unknown credential-like keys conservatively.

4. **High — Design §§1–2 and §4, interpolation dependencies.** Masking and confirmation depend only on the directly edited key. With `TELEGRAM_BOT_TOKEN=...` and `CUSTOM=${TELEGRAM_BOT_TOKEN}`, a resolved `CUSTOM` value exposes the token; with `NOTIFY_WITH_SNAPSHOT=${FLAG}`, editing `FLAG` changes privacy behavior without confirming `NOTIFY_WITH_SNAPSHOT`. Dependency-aware masking, confirmation and restart calculation are required if interpolation remains supported.

5. **High — Design §4, digest check and replacement.** `ThreadingHTTPServer` permits two saves to pass the same digest check before either writes. They then share `.env.tmp`, allowing lost changes, replacement failures or interference between writes. Atomic replacement prevents partial destination files; it does not make the read/check/write transaction atomic. Serialize cooperating writers, use unique temporary files, and specify how concurrent external edits are detected.

6. **Medium — Design §3, candidate Settings validation.** `Settings(_env_file=...)` still gives process-environment values precedence over file values. Validation therefore need not describe the saved file's behavior after a differently launched restart. Moreover, only the whole **leafi** model is constructed: changing a referenced variable can invalidate a habit-only field without validating that resulting field. Validate both complete file-derived configurations using controlled sources; report process overrides separately. `env_lookup()` explicitly has this same environment-first distinction.

7. **Medium — Design §§2–4, defaults and empty values.** Settings defaults do not describe Compose defaults. In the supplied Compose file, both absent and empty `CAM_PASSWORD` select `change-me`; absent or empty `GATUS_TOKEN` selects `change-me` for Gatus while leafi defaults to an empty token. Thus `Empty()` does not necessarily clear a downstream credential, and “not set” can conceal an active fallback credential. Show defaults and empty-value consequences per reader.

8. **Medium — Design §4, restart calculation; `docs/architecture/config.md`, timing settings.** Membership in a Settings class is insufficient to determine activation instructions. `TASK_REPEAT_MIN` configures the installed logon trigger through `install-tasks.ps1`; restarting the supervisor does not update that trigger. The documented `KEEP_*` settings have a launcher reader as well. The design also discovers `gatus` and Frigate-config references without defining their complete restart mapping. An explicit activation-action mapping is needed alongside reader discovery.

9. **High — Design §§2–3, privacy confirmation and allowed options; ADR-0011, v1 scope.** A confirmation checkbox does not satisfy the evaluation prerequisites for `PRON_AUTO_JUDGE=true` or `ASR_HOTWORDS=lexicon`. The proposed validation accepts values without establishing those prerequisites. Distinguish “recognized by the implementation” from “permitted in this release”; enforce the ADR gates or explicitly amend the ADR before enabling these choices.

## 2. Recommendations for the five open questions

1. **Placement — Low; §1.** The proposed placement is predictable enough if existing bytes remain untouched and the catalog supplies section anchors explicitly. Specify insertion at the end of the matching section; use the added-settings section when no unambiguous anchor exists.

2. **Unset — High; §1.** Commenting is reasonable, but deactivate every assignment that could remain effective for the affected readers. Describe it as removing file overrides, since process overrides and reader-specific defaults can still apply.

3. **CSRF — Medium; §5.** The Host, Origin, JSON and unpredictable-token checks are sufficient for the stated browser-origin threat when implemented together with no CORS access. Apply them to existing task mutations in the same change, preferably checking Host on the token-serving HTML routes too; derive permitted ports from server configuration so ephemeral-port tests work.

4. **Backups — Medium; §4.** Five local backups are acceptable, provided backups and temporary files receive access protection comparable to `.env`, failures clean up temporary copies, and no HTTP route serves them. Explicitly acknowledge that reset and credential rotation retain previous values in comments and backups; gitignore alone is not access protection.

5. **Other readers — High; §3.** Yes: validating both Settings classes misses Compose interpolation, empty/default semantics, environment precedence and downstream device/config interpretation. Add synthetic reader-compatibility fixtures and reader-specific validation; keep rendered credentials out of command output and diagnostics.

## 3. Decisions an implementer would still have to invent

- **Blocker — Medium; §2, catalog membership.** The key-list source is `.env.example`, but many known Settings fields are absent there, including `BRAIN_BACKEND`, `LEAFI_DEBUG_TEXT`, `SUPERVISOR_PORT` and most timing settings. Define the catalog as a union of sources and decide how Settings-only and reference-only keys receive groups, help and defaults; otherwise “every known setting” is unattainable.

- **Blocker — Medium; §§2–3, module ownership.** Decide where catalog assembly and registry access live. Importing service registries from `leafi.core.envcatalog` would violate `test_core_imports_nothing_from_other_rings`; keep discovery in an outer composition layer and inject metadata into core. Importing `agent.config` also instantiates `settings`, so metadata inspection currently validates the live `.env` as a side effect and may prevent the editor from starting on a malformed habit setting.

- **Blocker — High; §§1 and 3, supported file dialect.** Specify handling of existing multiline assignments, malformed syntax, BOMs and mixed-case collisions. The installed python-dotenv parser treats a UTF-8 BOM as part of the first key with the readers' current `utf-8` configuration; preserving bytes must not become silently treating that key as effective. Unsupported constructs should be preserved and diagnosed, with unsafe edits blocked.

- **Blocker — High; §4, request and error contracts.** Define allowed key names, whether new unknown keys may be created, exact operation schemas and sanitized validation errors. Reject assignment-breaking key characters and malformed operations before applying changes; errors and tracebacks must not echo credential values or candidate-file contents.

- **Blocker — Medium; §§3–4, temporary-file lifecycle.** Specify permissions, exclusive creation, cleanup on every failure path, backup-failure behavior and preservation of destination access controls after replacement. Include `cmd_setup` in the shared write/concurrency policy; sharing only `EnvFile.apply()` leaves two independent writers.

- **Implementer may decide — Low; §§1–2, placement mechanics.** Inject section-placement metadata into the pure editor rather than having it discover `.env.example`. Define duplicate-header selection, dominant-newline ties and insertion into files without a final newline.

- **Implementer may decide — Medium; §§4–6, conflict recovery and secret controls.** Preserve pending secret inputs only in page memory, distinguish unchanged/empty/unset explicitly, and require review when reapplying edits after a 409. An old privacy confirmation should not silently authorize a materially different refreshed change.

### Remaining blockers before coding

Resolve literal/interpolated value semantics, duplicate and case handling, secret masking, complete candidate validation, serialized writes, ADR feature gates, catalog ownership/coverage, activation instructions, and the request/error/file-lifecycle contracts above.
