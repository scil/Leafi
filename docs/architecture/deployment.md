# Deployment

One Windows 11 PC runs everything. Containers hold Frigate and mosquitto; the host runs go2rtc, Ollama, Anki and the Leafi process. See `c4-container.md` for ports.

## Why go2rtc runs on the host

The Xiaomi camera's cs2 P2P handshake is UDP hole punching whose return packets change port; Docker NAT drops them. The host binary is a patched build (`tools/go2rtc/PATCHES.md`); upgrading it without the patches brings back speaker noise and 5-minute disconnects.

## Processes and how they start

| Process | Start | Needed for |
|---|---|---|
| leafi watchdog (owns host go2rtc) | logon task `leafi-watchdog` → `scripts\win\keep.ps1 watchdog` → `python -m leafi watchdog`, which starts go2rtc in a Job Object and restarts it when the camera sends no video (ADR-0016); the owner installs the tasks once with `scripts\win\install-tasks.ps1` | camera recovery, alerts (toast + Telegram) |
| host go2rtc | the watchdog when the task is installed; otherwise `scripts\win\go2rtc-host.bat` (also from `up.bat`) | camera Eye/Mouth/Ear |
| Frigate + mosquitto | `docker compose up -d` (`restart: unless-stopped`) | habit presence; study does not need them |
| Ollama | `ollama serve` (scoop install present; add to startup when the vision judge is used daily) | vision judge, OCR second opinion, local brain fallback |
| Anki | user opens Anki desktop | card push, review turn (optional; Leafi queues when absent) |
| leafi study | `python -m leafi study [--text]` | the study loop |
| agent (habits) | `python -m agent.main`, or the logon task `leafi-habit-agent` (`install-tasks.ps1 -HabitAgent`) | scheduled tasks |

Supervision runs only while the owner is logged on (toasts need the desktop session). Logs: `data/logs/` (`leafi.log`, `watchdog.log`, `go2rtc.log`, `keep-<name>.log`); `scripts\win\health.ps1` prints the watchdog state, unsent alerts and log tails.

Trust boundaries: the Leafi process and go2rtc see raw frames and audio; Ollama sees frames; Anki sees text; the Claude API sees text; push services see text plus a parent-addressed frame.

Model files live under `models/` (gitignored); `python -m leafi doctor` reports which are missing and prints the download command for each.
