# Deployment

One Windows 11 PC runs everything. Containers hold Frigate and mosquitto; the host runs go2rtc, Ollama, Anki and the Leafi process. See `c4-container.md` for ports.

## Why go2rtc runs on the host

The Xiaomi camera's cs2 P2P handshake is UDP hole punching whose return packets change port; Docker NAT drops them. The host binary is a patched build (`tools/go2rtc/PATCHES.md`); upgrading it without the patches brings back speaker noise and 5-minute disconnects.

## Processes and how they start

| Process | Start | Needed for |
|---|---|---|
| leafi supervisor | logon task `leafi-supervisor` → `scripts\win\keep.ps1` → `python -m leafi supervisor` (ADR-0016): starts go2rtc and the habit agent as children in Job Objects, watches Docker Desktop, Frigate and mosquitto (and Ollama when listed in `SUPERVISE`), recovers what stops answering, alerts by toast + Telegram; the owner installs the task once with `scripts\win\install-tasks.ps1` | keeping every service running, alerts |
| host go2rtc | the supervisor when the task is installed; otherwise `scripts\win\go2rtc-host.bat` (also from `up.bat`) | camera Eye/Mouth/Ear |
| Frigate + mosquitto | `docker compose up -d` (`restart: unless-stopped`) | habit presence; study does not need them |
| Gatus (read-only dashboard) | `docker compose up -d gatus` (`127.0.0.1:18080`); fed by the supervisor's pushes, sends nothing (ADR-0016) | seeing every service and configuration check at a glance |
| Ollama | `ollama serve` (scoop install present; add to startup when the vision judge is used daily) | vision judge, OCR second opinion, local brain fallback |
| Anki | user opens Anki desktop | card push, review turn (optional; Leafi queues when absent) |
| leafi study | `python -m leafi study [--text]` | the study loop |
| agent (habits) | the supervisor when the owner adds `habit-agent` to `SUPERVISE` (opt-in: it speaks through the camera on schedule); otherwise `python -m agent.main` | scheduled tasks |

Supervision runs only while the owner is logged on (toasts need the desktop session). Every 15 min the supervisor also checks the configuration it depends on (the logon task, Docker autostart, the patched go2rtc, Windows' reserved ports, the power plan, toasts, Windows Update active hours, disk, models, `REDACT_TERMS`, Telegram, the heartbeat, `devices.yml`) and alerts on a failure; `python -m leafi checks` prints them. When the PC itself stops, the Healthchecks.io heartbeat (`HEARTBEAT_URL`) is what tells the owner. Logs: `data/logs/` (`leafi.log`, `supervisor.log`, `go2rtc.log`, `habit-agent.log`, `keep-supervisor.log`); `scripts\win\health.ps1` prints each service's recovery budget, unsent alerts and log tails.

Trust boundaries: the Leafi process and go2rtc see raw frames and audio; Ollama sees frames; Anki sees text; the Claude API sees text; push services see text plus a parent-addressed frame.

Model files live under `models/` (gitignored); `python -m leafi doctor` reports which are missing and prints the download command for each.
