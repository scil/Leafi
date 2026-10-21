# C4 L2 — containers

```mermaid
flowchart TB
    subgraph Host["Windows PC (RTX 5070 Ti)"]
        subgraph Proc["leafi process (Python 3.12, asyncio)"]
            Hub["core.hub\n+ devices adapters"]
            Study["study track\n(session, alignment, coach, knowledge)"]
            Habits["habits track\n(agent/ legacy)"]
            Svc["services\nasr · tts · ocr · pronunciation · brain · vision"]
            DB[("SQLite data/leafi.db\n+ data/sessions.db (habits)")]
            Cache[("cache/tts, cache/pages")]
        end
        Go2rtc["host go2rtc.exe\n(patched 1.9.14) :2984 api :2554 rtsp"]
        OllamaC["Ollama :11434"]
        AnkiC["Anki + AnkiConnect :8765"]
        subgraph Docker["Docker Desktop"]
            FrigateC["Frigate :15000\n(+ embedded go2rtc :1984)"]
            Mqtt["mosquitto :18830"]
            GatusC["Gatus :18080\nread-only dashboard"]
        end
        subgraph Guard["supervision (ADR-0016)"]
            Tasks["Task Scheduler\nlogon task leafi-supervisor\n(+ every 5 min, IgnoreNew)"]
            Keep["keep.ps1\nrestarts the supervisor"]
            Sup["leafi supervisor\n:18771 POST /rearm\nchecks every 15 min"]
            Toast["Windows toast\n(PowerShell 5.1)"]
        end
    end
    Xiaomi["Xiaomi camera (cs2 P2P)"]
    ESP32["ESP32 (xiaozhi ws) — planned"]
    Cloud["Claude API"]
    HC["Healthchecks.io\n(heartbeat)"]
    TG["Telegram"]

    Study --> Hub
    Habits -. T2 migration .-> Hub
    Study --> Svc
    Habits --> Svc
    Study --> DB
    Svc --> Cache
    Hub -- "GET /api/frame.jpeg, POST /api/streams" --> Go2rtc
    Go2rtc --> Xiaomi
    FrigateC -- rtsp relay --> Go2rtc
    FrigateC -- events --> Mqtt -- frigate/events --> Hub
    Svc -- /api/chat (images stay local) --> OllamaC
    Svc -- messages (text only) --> Cloud
    Study -- addNote / findCards / answerCards --> AnkiC
    Hub -- ws: opus + json --> ESP32

    Tasks -- "at logon, relaunch if dead" --> Keep
    Keep -- "start, restart with backoff" --> Sup
    Sup -. "child in a Job Object" .-> Go2rtc
    Sup -. "opt-in children" .-> Habits
    Sup -. "opt-in child" .-> OllamaC
    Sup -- "probe; restart Docker Desktop" --> Docker
    Sup -- "probe; compose up -d + restart" --> FrigateC
    Sup -- "push states" --> GatusC
    Study -- "study-mic / study-lease rows" --> DB
    Sup -- "alert outbox" --> DB
    Sup -- "catalog sentence" --> Toast
    Sup -- "catalog sentence (text only)" --> TG
    Sup -- "bodyless GET every minute" --> HC
    HC -. "alarm when pings stop" .-> TG
```

Port roster (host): go2rtc api 2984 / rtsp 2554, Frigate 15000, MQTT 18830, Ollama 11434, AnkiConnect 8765, task editor 8770, supervisor rearm 18771, Gatus 18080 (loopback), xiaozhi ws 8800 (planned).

The supervision layer's state machine and alert path are drawn in `flows/supervision.md`; ADR-0016 owns its rules.
