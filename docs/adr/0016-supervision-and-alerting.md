---
status: accepted
date: 2026-10-20
amends: 0011
revised: 2026-10-20 (codex design round 1: one lifecycle owner for go2rtc, Leafi renders every outbound alert; round 2: one durable outbox with one deliverer, go2rtc in a Job Object, one restart budget reserved before acting, Frigate as demand evidence, session faults as events; round 3: Python keeper with its own job, single-instance watchdog, state + outbox in one transaction, latches as outage identity, exclusive per-channel delivery, explicit streak rules; round 4: bounded, isolated delivery, good_since instead of summed elapsed time, same-key ordering with supersession, events on the dashboard; round 5 (confirming, budget closed): Gatus as a third delivery channel, `recovered_unsent_down` as a catalog reason, `camera-probe` for dips — fixed without a sixth round; records under `.scratch/review/2026-10-20-adr-0016-*`)
---

# Supervision and alerting: the Leafi watchdog owns go2rtc and delivers every alert from one outbox; Gatus is the dashboard; Task Scheduler starts the watchdog

Nothing supervised Leafi's host processes. Viewing the camera in the Mi Home app kills the host go2rtc's P2P producer while the process keeps running (TD-25), so a restart was manual, and every fault ended in a console log nobody reads. The owner asked for automatic recovery that gives up after repeated failures and leaves a record, supervision of every service, and early notice of severe faults by Windows toast and Telegram; they chose Gatus and Task Scheduler over an all-Python supervisor and over Uptime Kuma (configuration in its database, not in git).

Three rules shape everything below; design rounds 1–2 traced every finding to the lack of one of them:
1. **Each process has exactly one lifecycle owner**, and a process dies with its owner.
2. **Every alert is a row in one durable outbox, and one function renders and delivers rows.** Writers only insert; nothing else sends.
3. **Every automatic restart passes one budget gate**, reserved in storage before the kill.

## Owners

| What | Owner | How it dies with its owner / is supervised |
|---|---|---|
| go2rtc (start, stop, restart, its output) | `python -m leafi watchdog`, single instance (an exclusive lock on `data/watchdog.lock`; a second instance exits at once) | started inside a Windows Job Object with kill-on-close, so go2rtc dies when the watchdog dies, however it dies. At watchdog start go2rtc is normally absent (it died with the previous watchdog) and is simply started; a `go2rtc.exe` at this repository's path that is not in our job (the standalone one from `go2rtc-host.bat`, on the first start after installing the tasks) is killed first. Neither is a *restart* and neither is charged: starting an absent process is not recovery. Watchdog deaths are paced by the keeper's backoff and paged by the keeper alert, which bounds how often this happens |
| watchdog, habit agent (`python -m agent.main`) | `python -m leafi keep <name>` (`leafi/ops/keep.py`): starts the child in its own Job Object with kill-on-close (so the child dies with the keeper; jobs nest on Windows 8+), waits, logs the exit code, starts again after 5 s, 30 s, 2 min, then every 5 min; three exits within 30 min insert one `keeper-<name>` down row and run `deliver` once itself, so this path does not need the watchdog; a 30-min run inserts up | Task Scheduler logon task per keeper (`leafi-watchdog`, `leafi-habit-agent`): absolute `.venv\Scripts\python.exe`, repo working directory, "run only when the user is logged on" (toasts need the desktop session; logged off means unsupervised, stated in `health.ps1`), one instance, no time limit, task restart every 1 min if the keeper exits |
| Frigate, mosquitto, Gatus | Docker, `restart: unless-stopped` | Docker Desktop starts at logon; Gatus unreachable is itself an outbox row from the watchdog |
| dashboard of every condition | Gatus (`ghcr.io/twin/gatus:v5.37.0`, `config/gatus/config.yaml` in git, `127.0.0.1:18080` only) | — |

Gatus never sends anything and never decides an alert: it shows active checks (go2rtc API, Frigate API, mosquitto TCP, AnkiConnect TCP) and the external endpoints the watchdog pushes from the outbox. `go2rtc-host.bat` and `go2rtc-restart.bat` call the watchdog (`POST 127.0.0.1:18771/rearm`) when the `leafi-watchdog` task exists, and keep today's behaviour otherwise. `install-tasks.ps1` / `uninstall-tasks.ps1` register and remove the tasks; the owner runs them (Windows configuration). Measured 2026-10-20: a Gatus container reaches a host listener bound to `127.0.0.1` through `host.docker.internal`; `${VAR}` substitution in its config works; its push API answers 200 with the Bearer token and 401 without.

## Watchdog: camera state machine

One poll every 60 s on the active stream (`STREAM_NAME`). State lives in the `watchdog_state` row of `data/leafi.db` (SQLite, the system of record, ADR-0004) and is committed before any action.

```
observe (in this order; later steps run only when reached):
  1. GET go2rtc /api/streams (3 s)  fail                                  -> BAD(api)
  2. demand = stream has consumers, OR Frigate /api/stats answers and lists the active camera
     no demand                                                            -> IDLE   (no frame is ever fetched without demand, so the watchdog causes no P2P dial)
  3. no live producer                                                     -> BAD(video)   (Frigate up, camera at 0 fps, no producer lands here)
  4. GET frame.jpeg (15 s): a decodable JPEG >= 1 KiB                     -> GOOD, else BAD(video)

grace: for 90 s after any go2rtc start and 120 s after a resume, BAD is ignored (not counted)
resume: a poll whose wall-clock gap is > 180 s
streak (consecutive counted BADs) and good_since (monotonic time of the first GOOD of the current run, or none):
  BAD  -> streak += 1, good_since = none
  GOOD -> streak = 0; if good_since is none: good_since = now        run = now - good_since (0 on the first GOOD)
  IDLE -> streak = 0, good_since = none   (no demand is no evidence either way)
  any go2rtc start or resume -> streak = 0, good_since = none        (so a sleep is never counted as healthy time)
streak == 2 -> want_restart

each "commit {…}" below is one SQLite transaction; an outbox insert written next to it is in the same transaction
want_restart:
  if gave_up                    -> nothing
  elif kills < 3                -> commit {kills += 1, restart_at = now}; kill job; start go2rtc in a new job
  else                          -> commit {gave_up = true} + raise_latch(camera, restart_gave_up)
run >= 10 min                   -> commit {kills = 0, gave_up = false} + clear_latch(camera)
POST /rearm (the button)        -> commit {kills = 0, gave_up = false}; want_restart   (the button's restart is attempt 1 of 3; the latch is kept)

raise_latch(key, reason): if latch[key] is not down: set latch[key] = down and insert (key, down, reason)
clear_latch(key):         if latch[key] is down:     set latch[key] = up   and insert (key, up)
```

A watchdog that dies between the kill and the start leaves go2rtc absent (the job killed it); the next watchdog simply starts it, and the attempt stays charged because it was committed first. Latches, not budget flags, are the outage identity: a rearm or a second exhausted budget inside one outage never inserts a second down row, and only ten GOOD minutes insert the up row. `monitoring` (Gatus unreachable for 3 polls, cleared after 3 good polls) and `keeper-<name>` use the same latches.

Consequences, hand-checked on the traces of round 2:
- **Mi Home for 3 minutes, Frigate running:** BAD, BAD, then restart 1 and 90 s grace. If the app is still open: BAD, BAD, restart 2. After it closes: GOOD, and 10 minutes later the budget resets.
- **Camera off for 2 hours:** with polls at minutes 0, 1, 2, …: restart 1 at minute 1; grace to 2.5; BADs at 3, 4 → restart 2 at 4; BADs at 6, 7 → restart 3 at 7; BADs at 9, 10 → `restart_gave_up` once and no more kills. Polling continues. When power returns, go2rtc redials on its own because Frigate still consumes the stream; 10 GOOD minutes send the up row, and nothing else would.
- **API hangs:** two BADs, then the same budget gate. A fourth hang with no ten-minute GOOD run in between finds `kills = 3` and gives up.
- **Frigate stopped, no session, producer dies:** IDLE; nothing happens until something wants the stream.
- **Sleep and resume:** handled by the resume rule. The keeper has no staleness rule that could kill the watchdog on resume.
- **Crash between kill and start:** go2rtc is absent; the next watchdog starts it; the attempt stays charged.
- **Button pressed while gave up:** the budget rearms and the button's restart is attempt 1. The latch stays down, so neither the rearm nor a second exhausted budget inserts a row; only 10 GOOD minutes insert the up row.
- **9 minutes good, 1 minute bad, repeating:** at most one BAD in a row, so no restart and no alert. The dashboard shows the dips. This is accepted as below the paging threshold.

A restart cuts any clip that is being pushed. A session already survives a failed push: it is logged and the line is shown on the Faces. Waiting for the speech lease would delay recovery for a whole session, so the watchdog does not wait. The watchdog's own event loop is guarded by a thread that `os._exit(3)`s when the loop has not ticked for 3 min, unless the thread itself saw the same wall-clock gap (resume). A hung watchdog therefore becomes an exit, which its keeper counts.

## Alerts: one outbox, one deliverer

- **Rows.** The `alert_outbox` table in `data/leafi.db` holds `id, key, state (down|up|event), reason, origin, created_at, toast_at, telegram_at, attempts, next_try_at`; the `alert_latch` table holds each state key's last reported state. A schema migration adds both.
- **Writers only insert:**
  - the watchdog: `camera`, and `monitoring` when Gatus fails 3 polls;
  - the keeper (`leafi/ops/keep.py`): `keeper-<name>`, through the same latch;
  - the study session through `Hub.alert()`: `study-mic` and `study-lease`, as `event` rows tagged with the session id. These are events, not states, so no later session can "recover" them and two sessions never race over one key.
  - The insert is a local SQLite write. The fault path never waits on the network, and lease loss silences the Mouths before it inserts.
- **One deliverer at a time.** `deliver(store, toast, notifier)` in `leafi/ops/alerts.py` first takes an exclusive non-blocking lock on `data/deliver.lock`; if another process holds it, it returns (that process is delivering). Holding it:
  - each row has one mark per channel (`toast_at`, `telegram_at`, `gatus_at`); for each row missing a mark, `render()` it (Gatus gets the key and success flag only) and send on that channel only, then set that mark. A failed Telegram send never repeats a toast that was already shown, and an event pushed while Gatus is down reaches it when Gatus returns;
  - a failure increments `attempts` and sets `next_try_at` (30 s, 2 min, 10 min, then hourly); rows of other keys are still tried, so one stuck key never blocks another;
  - within one key, rows go out in `id` order per channel: a row waits while an older row of the same key is unsent on that channel. When an `up` row is due and the older `down` of the same key is still unsent on that channel, the `down` is marked superseded on that channel and the `up` is sent with reason `recovered_unsent_down`, whose catalog sentence says the key went down and has recovered (the channel's own timestamp dates it), so a late "down" never follows its own recovery;
  - every send is bounded (Telegram 10 s HTTP timeout; the toast subprocess 10 s) and the watchdog runs `deliver` as its own asyncio task, so a stalled channel never delays a poll or trips the loop guard;
  - the watchdog runs it every 10 s; the keeper runs it once after inserting its row; `python -m leafi alert --drain` runs it once by hand.
  - **Telegram is at-least-once:** a message accepted by Telegram whose reply is lost is sent again. Telegram has no idempotency key, so a rare duplicate is accepted, never a loss.
- **Dashboard, independent of Telegram.** Gatus is the third channel of the same deliverer, so a row reaches the dashboard even while Telegram is down. An `event` row (`study-mic`, `study-lease`) arrives as one failed result, and the deliverer pushes success for that key once the failure is marked, so the history shows a red mark at the event. Each poll's raw observation also goes to a dashboard-only `camera-probe` endpoint (GOOD and IDLE as success, BAD as failure, never latched, never paged), which is where single-poll dips show.
- **Rendering.** `render(key, state, reason)` maps an allow-listed key and a reason from `leafi/core/alerts.py`'s catalog to one fixed English sentence, for example "Camera: go2rtc restarted 3 times and the camera still sends no video; restarts paused — press 🔁 or check the camera." Anything outside the catalog renders as one fixed "unknown alert" sentence. No device name, IP, stream name, exception text or learner data can reach it, because its inputs are codes.
- **Delivery channels.**
  - Toast: Windows PowerShell 5.1 WinRT (the API call succeeded on this PC on 2026-10-20; that the pop-up is visible is for the owner to confirm). PowerShell 7 cannot load it.
  - Telegram: a new `NotifierDevice.send(text)` that raises on a transport error or a non-2xx status, used only by `deliver`. The existing `notify()` keeps swallowing errors for the session's wrap summary.
- **Duplicates.** One camera outage produces one `camera` row, because Frigate's frame rate is an input to the watchdog and not a separate alert.

## Logs

Rotating, 5 × 1 MB each:
- `data/logs/leafi.log`: WARNING and above, from every `leafi` command;
- `watchdog.log`: every observation and action;
- `go2rtc.log`: the child's output, replacing `tools/go2rtc/host.log` when supervised;
- `keep-<name>.log`: each keeper's starts and exit codes.

`health.ps1` prints Gatus statuses, undelivered outbox rows and `Get-Content -Tail` of each log, never a whole file.

## Egress (amends ADR-0011)

The egress table's Telegram row gains operational alerts. Their payload is text only and produced by `render()`. Gatus has no outbound provider. The session's wrap summary (counts only, already in the table and covered by the existing privacy run) is the one other Telegram sender, and it is not an alert.

Enforcement:
- `tests/test_architecture.py`: `NotifierDevice.send` is called only from `leafi/ops/alerts.py::deliver`; `Hub.notify` only from the session's wrap.
- `tests/test_privacy.py` drives every writer through `deliver` under the canary recorder, with canaries in every field a writer could fill:
  - the session's `ListenerLost` path (its message carries a device name) and lease-loss path;
  - the watchdog's `camera` and `monitoring` transitions;
  - the keeper's insert, fed hostile keys and reasons.

  It asserts that every operational Telegram body is exactly one catalog sentence. The watchdog's HTTP listener accepts only `POST /rearm`, so nothing outside Leafi can insert a row.

Out of scope:
- restarting Frigate (Docker owns it);
- alerts from the habit track's own logic (`agent/` change budget);
- the speaker latency of TD-24;
- a camera Eye fault seen only by a session when nothing else demands the stream (the session shows it on the Faces, TD-20);
- supervision while the owner is logged off.
