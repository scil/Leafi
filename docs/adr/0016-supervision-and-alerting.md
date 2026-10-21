---
status: accepted
date: 2026-10-20
amends: 0011
revised: 2026-10-20 (codex design rounds 1–5, gpt-6-astra high, records under `.scratch/review/2026-10-20-adr-0016-*`); 2026-10-21 cut to v1 by the owner — the rounds had grown the design past one household's needs; the reviewed rules below are kept, the rare-case machinery is listed under "Accepted for v1"; one v1 round (medium) fixed delivery order, the scripts' fallback and rule 3's scope
---

# Supervision and alerting v1: the Leafi watchdog owns go2rtc and sends every alert from one outbox

Nothing supervised Leafi's host processes. Viewing the camera in the Mi Home app kills the host go2rtc's P2P producer while the process keeps running (TD-25), so recovery was a manual restart, and every fault ended in a console log nobody reads. The owner asked for automatic restarts that give up after repeated failures and leave a record, every service kept running, and early notice of severe faults by Windows toast and Telegram.

Three rules came out of the design review and hold everywhere below:
1. **go2rtc has exactly one lifecycle owner, and it dies with that owner.**
2. **Every alert is a row in one SQLite outbox, rendered by one function from a fixed catalog.** Writers only insert.
3. **Every automatic restart of go2rtc passes one budget**, written to storage before the kill. (A keeper starting a process that has exited is keeping it alive, not recovering it, and is paced by its backoff instead.)

## Who keeps what running

| Process | Owner | Notes |
|---|---|---|
| go2rtc | `python -m leafi watchdog` | Started inside a Windows Job Object with kill-on-close, so it dies with the watchdog. The watchdog is single-instance (exclusive lock on `data/watchdog.lock`). At start it kills a `go2rtc.exe` at this repository's path that is not its own (the standalone one from `go2rtc-host.bat`) and starts its own; starting an absent process is not a restart and is not charged. The child's output goes to `data/logs/go2rtc.log`. |
| watchdog, habit agent | `scripts/win/keep.ps1 <name>`, a loop under a Task Scheduler logon task (`leafi-watchdog`, `leafi-habit-agent`) | Starts the process; after it exits, logs the code and starts it again after 5 s, 30 s, 2 min, then every 5 min. Three exits within 30 min insert one `keeper-<name>` row and run `python -m leafi alert --drain`. Absolute venv Python, repo working directory, "run only when the user is logged on" (toasts need the desktop session), one instance, no time limit. The owner installs the tasks with `scripts/win/install-tasks.ps1` (Windows configuration). |
| Frigate, mosquitto | Docker, `restart: unless-stopped` | unchanged |

When the `leafi-watchdog` task is installed, `go2rtc-host.bat` starts that task instead of go2rtc, and `go2rtc-restart.bat` only calls the watchdog (`POST 127.0.0.1:18771/rearm`); neither ever starts go2rtc itself. Without the task (a PC where the owner has not installed it) they keep today's standalone behaviour. A dashboard (Gatus) is deferred; `health.ps1` shows the watchdog state, unsent alerts and log tails.

## Camera state machine (watchdog, one poll every 60 s)

State lives in the `watchdog_state` row of `data/leafi.db` and is committed before any action.

```
observe, in order:
  1. GET go2rtc /api/streams (3 s) fails                                   -> BAD
  2. demand = the active stream (STREAM_NAME) has consumers, or Frigate /api/stats answers and lists that camera
     no demand                                                             -> IDLE   (no frame is fetched, so the watchdog never causes a P2P dial)
  3. no live producer                                                      -> BAD
  4. GET frame.jpeg (15 s) is a JPEG >= 1 KiB                              -> GOOD, else BAD

grace: BAD is ignored for 90 s after any go2rtc start and 120 s after a resume (a poll whose wall-clock gap is > 180 s)
BAD  -> streak += 1, good_since = none
GOOD -> streak = 0, good_since = good_since or now
IDLE, any go2rtc start, resume -> streak = 0, good_since = none
streak == 2 -> want_restart:
    gave_up       -> nothing
    kills < 3     -> commit kills += 1; kill go2rtc; start it in a new job
    otherwise     -> commit gave_up = true and, if latch is up, latch = down + insert (camera, down, restart_gave_up)
GOOD for 10 min (now - good_since) -> commit kills = 0, gave_up = false and, if latch is down, latch = up + insert (camera, up, recovered)
POST /rearm (🔁) -> commit kills = 0, gave_up = false; want_restart     (its restart is attempt 1 of 3; the latch is kept)
```

Traces (from the review): the Mi Home app open for 3 minutes with Frigate running gives one or two restarts, then GOOD. A camera that is off gives restarts at about minutes 1, 4 and 7, then one `restart_gave_up` alert and no more kills. A hung API takes the same budget. A sleep is never counted as healthy time. One outage sends one down row, whatever the button does, and only ten GOOD minutes send the up row. A restart can cut a clip being pushed; a session already survives a failed push (logged, line shown on the Faces).

## Alerts

- **Outbox.** Table `alert_outbox(id, key, state, reason, created_at, toasted, sent_at, attempts, next_try_at)`; `watchdog_state` holds the camera latch.
- **Writers:**
  - the watchdog: `camera`;
  - keep.ps1 through `python -m leafi alert --insert keeper-<name> down repeated_exits`;
  - the study session: `study-mic` on `ListenerLost` and `study-lease` on lease loss. These are events, one row each, and lease loss silences the Mouths before inserting. The insert is a local write; the session never waits on the network.
- **`render(key, state, reason)`** (`leafi/core/alerts.py`) maps an allow-listed key and reason to one fixed English sentence; anything else renders as one fixed "unknown alert" sentence. Its inputs are codes, so no device name, IP, stream name, exception text or learner data can reach it.
- **`deliver(store, toast, notifier)`** (`leafi/ops/alerts.py`), run by the watchdog every 10 s as its own task, and once by `alert --drain`:
  - works on the oldest unsent row only; when it is not yet due, nothing is sent this run, so no newer row overtakes it;
  - shows the toast once per row, through Windows PowerShell 5.1 WinRT with a 10 s limit;
  - sends Telegram through a new `NotifierDevice.send()` that raises on a transport error or a non-2xx status (10 s timeout);
  - on success sets `sent_at`; on failure sets `next_try_at` (30 s, 2 min, 10 min, then hourly) and stops, so later rows wait and a recovery is never sent before its outage;
  - without Telegram configured, a row is sent once its toast is shown.

## Logs

Rotating, 5 × 1 MB: `data/logs/leafi.log` (WARNING and above from every `leafi` command), `watchdog.log` (every observation and action), `go2rtc.log`. keep.ps1 rolls `keep-<name>.log` at 1 MB. `health.ps1` reads only tails.

## Egress (amends ADR-0011)

The Telegram row of the egress table gains operational alerts, text only, produced by `render()`. The session's wrap summary stays the one other Telegram sender. `tests/test_architecture.py` allows `NotifierDevice.send` only in `leafi/ops/alerts.py`. `tests/test_privacy.py` drives the session's `ListenerLost` path (its message carries a device name) and the `--insert` path with hostile values through `deliver` under the canary recorder, and asserts each Telegram body is one catalog sentence.

## Accepted for v1

These cases were raised in review and are judged too rare for one household:
- a rare duplicate message when the watchdog and `--drain` deliver at the same moment, or when Telegram accepts a message but the reply is lost;
- a crash inside the restart's one-second window, which may leave one attempt uncharged;
- a watchdog that hangs without exiting (its keeper only sees exits);
- a keeper that dies while its child lives on;
- single-poll dips that page nobody;
- no supervision while logged off;
- an IDLE stream never alerting.

Deferred: Gatus as a dashboard, and restarting Frigate from the watchdog (Docker owns it). Out of scope: alerts from the habit track's own logic (`agent/` change budget) and TD-24.
