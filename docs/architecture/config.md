# Configuration

Three roots, one owner each:

| Root | Owner | Reload | Holds |
|---|---|---|---|
| `.env` (from `.env.example`) | `leafi/core/config.py` (pydantic-settings; the legacy `agent/config.py` reads the same file) | process start | secrets, hosts, ports, model names, feature flags |
| `config/devices.yml` | `leafi/core/hub.py` | process start (`python -m leafi devices` prints the parsed result) | which devices exist and which capabilities each provides |
| `config/tasks.yml` | `agent/tasks.py` (task editor UI) | mtime check on every read | habit tasks |

`.env` is edited on the task editor's 设置 (.env) tab (`python -m agent.webui`) or by hand. The page and the CLI (`python -m leafi privacy terms import`, which removes the retired `REDACT_TERMS`) write only through `leafi/core/envfile.py::update_env` (lock, backup to `data/env-backup/`, ACL kept) and only while the file is in canonical form: every line blank, a column-0 comment, or `KEY=value` with a bare `[A-Za-z0-9_./:@,+=%-]*` value, a single-quoted value without `'`, `\` or `${`, or (for a value with an apostrophe) a double-quoted value without `"`, `\` or `$`; an empty value followed by a comment is written `KEY=''  # …`. Design: `docs/plans/active/2026-10-21-env-settings-page.md`.

## `config/devices.yml` (schema v1)

```yaml
version: 1
voice_policy: all          # all | primary | none
primary_mouth: desk_cam    # used when voice_policy = primary
devices:
  - name: desk_cam
    adapter: go2rtc_camera
    capabilities: [eye, mouth]        # ear is opt-in once the mic path is verified
    options:
      go2rtc_url: ${GO2RTC_URL}       # ${VAR} expands from .env
      stream: ${STREAM_NAME}
      audio_codec: opus
      src_dir: ${SPEAKER_SRC_DIR}
      snapshot_width: 1920
  - name: pc
    adapter: local_pc
    capabilities: [ear, mouth, face]
    options:
      input_device: ${PC_INPUT_DEVICE:-DJI}  # name fragment, index or `default`
      zeros_lost_after_s: 10          # all-zero capture this long → ListenerLost (TD-26); 0 disables
  - name: console
    adapter: console
    capabilities: [listener, face]    # typed input; always safe to leave on
  - name: hallway_presence
    adapter: frigate_presence
    capabilities: [presence]
  - name: parent_phone
    adapter: notifier
    capabilities: [notifier]
```

Selection block (required for study):

```yaml
study:
  eye: desk_cam            # the one Eye used for pages
  listener: pc             # the one voice Listener; console controls stay active in parallel
```

Rules: unknown `adapter` or capability → startup error naming the device. A device whose options are missing a required `${VAR}` is **disabled with a warning**, not fatal, so a laptop without the camera still runs text mode. `console` is always added if no `listener`/`face` exists.

## `.env` keys

Every key `.env` may hold is described once, in `config/env-schema.json` (type, choices, defaults per reader, help, which program reads it and what to restart, secret / privacy flags, release gates, validators). The settings page renders it, `.env.example` is generated from it (`python -m leafi env-example`), and `leafi/envedit.py::agreement` (run by `tests/test_env_schema.py` and by the page) fails when it disagrees with the Settings classes, Compose, `devices.yml`, the timing script, a choice list's code constant, a validator's consumer or the protection floor in `leafi/envprotect.py`. Add a setting by adding the Settings field and its manifest entry; the test names whichever is missing. Design: `docs/plans/active/2026-10-21-env-settings-page.md` (Rev 8).

`devices.yml` values may use `${VAR:-default}` for optional variables (empty allowed); a plain `${VAR}` is required.

Removed names: `BRAIN_MODEL` no longer configures the study track (2026-10-20, replaced by `STUDY_BRAIN_MODEL`; the habit track still reads it). Renamed: the repository path in `SPEAKER_SRC_DIR` examples changed from `Carema-Kis-AI` to `Leafi` (2026-10-19).
