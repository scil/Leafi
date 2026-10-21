# Design: `.env` settings page in the task editor

Status: implemented 2026-10-21 (rev 7 design, after five codex rounds and one confirming round; the confirming round's single remaining finding, marker write failure, is resolved in §2 step 7 and not re-reviewed). Rounds: `reviews/2026-10-21-codex-env-design-review-{1..6}.md`.

Implementation notes (where the code differs from the text below): enum-like keys without a registry (`ASR_HOTWORDS`, `OCR_SNAP`, `BOOK_LOOKUP`, `OCR_VERSION`, `VERIFY_MODE`, `SPEAKER_BACKEND`) take their options from `ENUMS` in `leafi/envedit.py` rather than from new `Literal` field types, so no runtime setting gains a stricter startup check; the `env-file` check's cases are tested through `envfile.health` in `tests/test_envfile.py`; a key documented in `.env.example` that no program reads (`XIAOMI_*`) is editable and labelled as such, not Unknown.

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
