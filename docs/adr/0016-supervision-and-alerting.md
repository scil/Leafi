---
status: accepted
date: 2026-10-20
amends: 0011
revised: 2026-10-20 (codex design rounds 1–5, gpt-6-astra high, records under `.scratch/review/2026-10-20-adr-0016-*`); 2026-10-21 cut to v1 by the owner — the rounds had grown the design past one household's needs; the rare-case machinery is listed under "Accepted for v1"; one v1 round (medium) fixed delivery order, the scripts' fallback and rule 3's scope; 2026-10-21 the owner merged the watchdog and the keepers into one supervisor for every service; one medium round scoped rules 1 and 3, charged child exits, restarted Docker Desktop and recreated containers on recovery, and freed toasts from the Telegram queue; 2026-10-21 the owner added configuration checks, a Healthchecks.io heartbeat and Gatus as a read-only dashboard; one medium round: heartbeat only on the supervisor's dashboard entry, the heartbeat alarm as rule 2's stated exception, channel checks switchable, `down.bat` disables the task
---

# Supervision and alerting v1: one Leafi supervisor keeps every service running and sends every alert from one outbox

Nothing supervised Leafi's services. Viewing the camera in the Mi Home app kills the host go2rtc's P2P producer while the process keeps running (TD-25), so recovery was a manual restart, and every fault ended in a console log nobody reads. The owner asked for automatic restarts that give up after repeated failures and leave a record, every independent service kept running (not only go2rtc), and early notice of severe faults by Windows toast and Telegram.

Three rules came out of the design review and hold everywhere below:
1. **Every supervised child process (go2rtc, habit agent, Ollama) has exactly one lifecycle owner, the supervisor, and dies with it.** Containers keep Docker as their owner: `restart: unless-stopped` restarts a container that exits; the supervisor handles one that runs but does not answer.
2. **Every alert Leafi raises is a row in one SQLite outbox, rendered by one function from a fixed catalog.** Writers only insert. The one exception is the heartbeat's alarm, which Healthchecks.io raises outside the PC precisely when Leafi cannot.
3. **Every recovery the supervisor performs passes that service's budget**, written to storage before the action. The only uncharged action is the initial start of each child when the supervisor itself starts, which keep.ps1's backoff paces.

## One supervisor

`python -m leafi supervisor` (`leafi/ops/supervisor.py`) is single-instance (exclusive lock on `data/supervisor.lock`). Each poll (every 60 s) it observes every enabled service in turn, feeds the observation to that service's policy, and runs the recovery action when the policy asks for it. Child processes are started inside a Windows Job Object per child with kill-on-close, so they die with the supervisor however it dies. At start, the supervisor kills any instance of a child service it did not start (a go2rtc from `go2rtc-host.bat`, a habit agent started by hand) and starts its own, even for a service whose persisted budget has given up: a running process is still useful, and the supervisor only stops *recovering* it. After that, a child that exits is a BAD observation like any other, so a crash loop is charged and ends in one alert.

| Service (`SUPERVISE`) | Observation: GOOD / BAD / IDLE | Recovery | Grace after recovery |
|---|---|---|---|
| `camera` | go2rtc child not running or API fails → BAD; no demand (no consumer and Frigate does not list the camera) → IDLE; no live producer, or `frame.jpeg` not a JPEG ≥ 1 KiB → BAD; else GOOD. A frame is fetched only with demand (no extra Xiaomi cloud dials) | restart the go2rtc child | 90 s |
| `habit-agent` (opt-in: it speaks through the camera on its schedule) | child process alive → GOOD, else BAD | restart the child (`python -m agent.main`) | 90 s |
| `docker` | `docker info` succeeds → GOOD, else BAD | restart Docker Desktop: end its process if present, then start it (covers both an absent Desktop and a hung engine) | 180 s |
| `frigate` | `docker` not GOOD → IDLE; `GET /api/stats` 200 → GOOD, else BAD | `docker compose up -d frigate` (recreates a removed container), then `docker compose restart frigate` | 120 s |
| `mosquitto` | `docker` not GOOD → IDLE; TCP connect to `127.0.0.1:18830` → GOOD, else BAD | `docker compose up -d mosquitto`, then `docker compose restart mosquitto` | 60 s |
| `ollama` (off by default) | `GET /api/tags` 200 → GOOD, else BAD | restart the `ollama serve` child | 60 s |
| `gatus` (the dashboard below) | `docker` not GOOD → IDLE; `GET /health` 200 → GOOD, else BAD | `docker compose up -d gatus`, then `docker compose restart gatus` | 60 s |

Containers are observed only while Docker is GOOD (dependency suppression), so a stopped Docker engine gives one `docker` alert, not three. Anki is the owner's own app and is not supervised. A reading session is not supervised; it raises its own events (below).

## Policy (one instance per service, state in `service_state`)

```
grace: BAD is ignored until grace_until (set after every recovery and every supervisor start; 120 s after a resume,
       a poll whose wall-clock gap is > 180 s)
BAD  -> streak += 1, good_since = none
GOOD -> streak = 0, good_since = good_since or now
IDLE, recovery, resume -> streak = 0, good_since = none
streak == 2 -> want_recovery:
    gave_up       -> nothing
    kills < 3     -> commit kills += 1; run the service's recovery
    otherwise     -> commit gave_up = true and, if latch is up, latch = down + insert (service, down, restart_gave_up)
GOOD for 10 min -> commit kills = 0, gave_up = false and, if latch is down, latch = up + insert (service, up, recovered)
POST /rearm?service=S (default camera) -> commit kills = 0, gave_up = false; want_recovery (attempt 1 of 3; latch kept)
```

A crashed child is therefore restarted after about two minutes, a crash loop gets three restarts and then one alert, and one outage sends one down row whatever the button does. Traces checked in review for the camera hold for every service: a sleep is never counted as healthy time, and the budget survives a supervisor restart.

## Configuration checks (every 15 min)

Restarts cannot fix a setting that is wrong. The supervisor also runs a list of configuration checks (`leafi/ops/checks.py`), one function each, returning ok or a reason code. Each check has its own latch: a failure inserts one `check-<name>/down/<reason>` row, and the first passing run afterwards inserts the `up` row. **Checks never repair anything.** Changing Windows, Docker or `.env` settings is the owner's decision; the alert says what to change.

| Check | Passes when |
|---|---|
| `task` | the `leafi-supervisor` task exists and is enabled, with a logon trigger and a repeating trigger, `IgnoreNew`, and no time limit |
| `docker-autostart` | Docker Desktop's `settings-store.json` has `AutoStart: true` |
| `go2rtc-patched` | the SHA-256 of `tools/go2rtc/go2rtc.exe` equals `GO2RTC_SHA256` (AGENTS.md: never a stock build; the owner updates the setting after a patched rebuild) |
| `ports` | none of the ports Leafi binds (2984, 2554, 15000, 18830, 18771, 18080) is inside a Windows excluded port range (`netsh int ipv4 show excludedportrange`; the ranges move after reboots) |
| `power` | on AC power, sleep and hibernate after idle are "never" (`powercfg`) |
| `toasts` | toasts are not disabled globally, nor for Windows PowerShell (registry) |
| `active-hours` | Windows Update active hours cover `ACTIVE_HOURS` (default 7–21), so updates do not reboot the PC while the household uses it |
| `disk` | at least `MIN_FREE_GB` (default 5) free on the data drive |
| `models` | `leafi doctor` reports no backend as missing or error |
| `redact-terms` | `REDACT_TERMS` is set (the names removed from cloud payloads) |
| `telegram` | `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set (only while `telegram` is in `REQUIRED_CHANNELS`, default `telegram,heartbeat`: the owner chose both; toast-only is a supported choice by removing it) |
| `heartbeat` | `HEARTBEAT_URL` is set (only while `heartbeat` is in `REQUIRED_CHANNELS`) |
| `devices` | `config/devices.yml` parses |

Autologon is the owner's open decision and is not checked.

## Heartbeat (dead man's switch)

When the PC is off, asleep, frozen or logged off, the supervisor cannot alert anyone. So every poll it sends `GET HEARTBEAT_URL` (a Healthchecks.io check URL, 5 s limit). The owner configures Healthchecks.io to alert them, on Telegram for example, when the pings stop. When `HEARTBEAT_URL` is empty, nothing is sent. The request carries no body, and its URL holds only the check's random id.

## Dashboard (Gatus, read-only)

Gatus (`ghcr.io/twin/gatus:v5.37.0`, compose service `gatus`, published on `127.0.0.1:18080` only, SQLite history in a volume) shows the state of every service and check. Its configuration (`config/gatus/config.yaml`, in git) declares only external endpoints: one per service, one per check, and `leafi/supervisor`, which the supervisor pushes every poll and which alone has a 5-minute heartbeat, so a silent supervisor turns it red. Services and checks have no heartbeat: checks report every 15 min, and a disabled service reports nothing, so they show their last pushed state. It declares **no alerting provider and no active endpoint**: Gatus sends nothing and decides nothing. After each poll the supervisor pushes every observation (GOOD and IDLE as success; BAD as failure with a reason code), and after each check run every check result, to `POST /api/v1/endpoints/{key}/external` with `GATUS_TOKEN`. A failed push is logged at debug level and dropped. The dashboard is a view; the outbox stays the record.

## Keeping the supervisor alive

One Task Scheduler logon task, `leafi-supervisor`, runs `scripts/win/keep.ps1`. That loop starts the supervisor, and after an exit starts it again after 5 s, 30 s, 2 min, then every 5 min. Three exits within 30 min insert one `supervisor/down/repeated_exits` row and run `python -m leafi alert --drain`, which needs no supervisor. The task also has a trigger that repeats every 5 min. With `IgnoreNew` this leaves a running keep.ps1 alone and relaunches a dead one. A relaunched keep.ps1 whose supervisor is still alive gets exit code 3 (the lock is held); it waits and tries again without counting that as an exit. Task Scheduler's own "restart on failure" ignores exit codes, and a Windows service cannot show desktop toasts, so this small loop is the outermost guard. The task uses the absolute venv Python and the repo working directory, runs only while the owner is logged on, allows one instance and has no time limit. The owner installs it with `scripts/win/install-tasks.ps1`, which changes Windows configuration.

When the task is installed:
- `go2rtc-host.bat` starts the task instead of go2rtc;
- `go2rtc-restart.bat` (🔁) posts `/rearm?service=camera`;
- `down.bat` disables the task (so the repeating trigger does not undo a deliberate stop) and stops the supervisor; its children die with it. `up.bat` enables and starts the task again.

Without the task, these scripts keep today's standalone behaviour.

## Alerts

- **Outbox.** Table `alert_outbox(id, key, state, reason, created_at, toasted, sent_at, attempts, next_try_at)`. `service_state(service, kills, gave_up, latch, updated_at)` holds each budget and latch.
- **Writers:**
  - the supervisor: `<service>/down/restart_gave_up` and `<service>/up/recovered`;
  - keep.ps1 through `python -m leafi alert --insert supervisor down repeated_exits`;
  - the study session: `study-mic` on `ListenerLost` and `study-lease` on lease loss. These are events, one row each, and lease loss silences the Mouths first. The insert is a local write; the session never waits on the network.
- **`render(key, state, reason)`** (`leafi/core/alerts.py`) maps an allow-listed key and reason to one fixed English sentence; anything else renders as one fixed "unknown alert" sentence. Its inputs are codes, so no device name, IP, stream name, exception text or learner data can reach it.
- **`deliver(store, toast, notifier)`** (`leafi/ops/alerts.py`) is run by the supervisor every 10 s as its own task, and once by `alert --drain`:
  - it first shows a toast for every row not yet toasted, once each, through Windows PowerShell 5.1 WinRT with a 10 s limit, so local notice never waits behind a Telegram retry;
  - it then works on the oldest unsent row only; when that row is not yet due, no Telegram message is sent, so no newer row overtakes it;
  - it sends Telegram through `NotifierDevice.send()`, which raises on a transport error or a non-2xx status (10 s timeout);
  - on success it sets `sent_at`; on failure it sets `next_try_at` (30 s, 2 min, 10 min, then hourly) and stops;
  - without Telegram configured, a row counts as sent once its toast is shown.

## Logs

Rotating, 5 × 1 MB each:
- `data/logs/leafi.log`: WARNING and above, from every `leafi` command;
- `supervisor.log`: every observation that changes, and every action;
- one `<child>.log` per child process (`go2rtc.log`, `habit-agent.log`, `ollama.log`).

keep.ps1 rolls `keep-supervisor.log` at 1 MB. `health.ps1` prints each service's budget and latch, the unsent alerts, and only the tails of the logs.

## Egress (amends ADR-0011)

The Telegram row of the egress table gains operational alerts: text only, produced by `render()`. The session's wrap summary stays the one other Telegram sender. A new row adds the heartbeat: `GET HEARTBEAT_URL` to Healthchecks.io (`hc-ping.com`), no body, the URL holding only the check's id. Gatus is local (`127.0.0.1`) and has no outbound provider.

Enforcement:
- `tests/test_architecture.py` allows `NotifierDevice.send` only in `leafi/ops/alerts.py`.
- `tests/test_privacy.py` drives the session's `ListenerLost` path and the `--insert` path, both with hostile values, through `deliver` under the canary recorder, and asserts that each Telegram body is one catalog sentence.

## Accepted for v1

These cases were raised in review and judged too rare for one household:
- a rare duplicate message, when the supervisor and `--drain` deliver at the same moment, or when Telegram accepts a message but its reply is lost;
- a crash inside a recovery's short window, which may leave one attempt uncharged;
- a supervisor that hangs without exiting is not restarted by keep.ps1 (it only sees exits); it is *noticed*, because a hung poll loop stops the heartbeat and Healthchecks.io alerts the owner, and the dashboard's endpoints turn red;
- single-poll dips that page nobody;
- no supervision while logged off;
- an IDLE camera stream never alerting;
- the habit agent's own scheduling faults, which are not visible as a process exit.

Out of scope: TD-24, and autologon (the owner's open decision).
