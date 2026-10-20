# Deployment

One Windows 11 PC runs everything. Containers hold Frigate and mosquitto; the host runs go2rtc, Ollama, Anki and the Leafi process. See `c4-container.md` for ports.

## Why go2rtc runs on the host

The Xiaomi camera's cs2 P2P handshake is UDP hole punching whose return packets change port; Docker NAT drops them. The host binary is a patched build (`tools/go2rtc/PATCHES.md`); upgrading it without the patches brings back speaker noise and 5-minute disconnects.

## Processes and how they start

| Process | Start | Needed for |
|---|---|---|
| host go2rtc | `scripts\win\go2rtc-host.bat` (also from `up.bat`) | camera Eye/Mouth/Ear |
| Frigate + mosquitto | `docker compose up -d` | habit presence; study does not need them |
| Ollama | `ollama serve` (scoop install present; add to startup when the vision judge is used daily) | vision judge, OCR second opinion, local brain fallback |
| Anki | user opens Anki desktop | card push, review turn (optional; Leafi queues when absent) |
| leafi study | `python -m leafi study [--text]` | the study loop |
| agent (habits) | `python -m agent.main` | scheduled tasks |

Trust boundaries: the Leafi process and go2rtc see raw frames and audio; Ollama sees frames; Anki sees text; the Claude API sees text; push services see text plus a parent-addressed frame.

Model files live under `models/` (gitignored); `python -m leafi doctor` reports which are missing and prints the download command for each.
