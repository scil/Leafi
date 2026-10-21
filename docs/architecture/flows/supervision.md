# Flow: how Leafi keeps its services running and tells the owner

ADR-0016 owns every rule drawn here; this page only illustrates it. Numbers are settings (`SUPERVISOR_*`, `CHECKS_EVERY_S`, `KEEP_*`, `TASK_REPEAT_MIN`) with their defaults in brackets; the ADR's "Timing settings and their invariants" says which combinations are valid.

## Who keeps whom running

```mermaid
flowchart TB
    Tasks["Task Scheduler: logon task leafi-supervisor<br/>at logon, and every TASK_REPEAT_MIN [5] min with IgnoreNew"]
    Keep["keep.ps1<br/>restarts the supervisor after KEEP_BACKOFF_S [5, 30, 120, 300 s]<br/>KEEP_CRASH_EXITS [3] exits in KEEP_CRASH_WINDOW_MIN [30] min → one alert"]
    Sup["leafi supervisor (single instance)<br/>poll every SUPERVISOR_POLL_S [60 s] · checks every CHECKS_EVERY_S [15 min]"]
    subgraph Children["children: Job Object, die with the supervisor"]
        Go2rtc["go2rtc (camera)"]
        Agent["habit agent (opt-in)"]
        Ollama["Ollama (opt-in)"]
    end
    subgraph Docker["Docker Desktop (restarted by the supervisor)"]
        Frigate["Frigate"]
        Mqtt["mosquitto"]
        Gatus["Gatus (read-only dashboard)"]
    end
    Tasks --> Keep --> Sup
    Sup --> Children
    Sup -- "probe; compose up -d + restart" --> Docker
```

Docker's own `restart: unless-stopped` restarts a container that exits; the supervisor recovers one that runs but does not answer. Containers are not probed while Docker is down, so one Docker outage is one alert.

## One service's policy

```mermaid
stateDiagram-v2
    [*] --> Grace: supervisor starts (initial start, not charged)
    Grace --> Watching: grace ends (SUPERVISOR_GRACE per service)
    Watching --> Watching: GOOD or IDLE
    Watching --> Watching: GOOD for SUPERVISOR_HEALTHY_S [10 min] resets the budget (and sends "up" if the latch was down)
    Watching --> Recovering: SUPERVISOR_BAD_STREAK [2] BADs in a row and budget left (commit kills + 1 first)
    Watching --> GaveUp: BAD streak with no budget left (one "down" alert, latch down)
    Recovering --> Grace: background recovery task ends (success or failure)
    GaveUp --> GaveUp: BAD (nothing is restarted)
    GaveUp --> Watching: GOOD for SUPERVISOR_HEALTHY_S (budget reset, "up" alert)
    GaveUp --> Recovering: rearm button (fresh budget, this is attempt 1, latch kept)
    Watching --> Grace: resume from sleep (wall-clock gap over SUPERVISOR_RESUME_GAP_S)
```

- While **Recovering**, the service is reported RECOVERING and not observed, so no second recovery starts; other services and the heartbeat carry on (the recovery is a background task).
- **IDLE** (nothing wants the camera stream, or Docker is down for a container) clears both the BAD streak and the GOOD run.
- The budget and the latch are in `service_state`, so they survive a supervisor restart. One outage sends one "down" row whatever the button does.

## From a fault to the owner

```mermaid
sequenceDiagram
    participant W as writer (supervisor policy · configuration check · study session · keep.ps1)
    participant O as alert_outbox (SQLite)
    participant D as deliver() every 10 s
    participant T as Windows toast
    participant TG as Telegram
    participant G as Gatus (dashboard)
    participant HC as Healthchecks.io
    W->>O: insert (key, state, reason) as codes, in the same transaction as the state change
    D->>O: every row not yet toasted
    D->>T: render(key, state, reason): one fixed catalog sentence, shown once
    D->>O: oldest unsent row only
    alt due and Telegram configured
        D->>TG: the same sentence (text only)
        alt accepted
            D->>O: sent_at = now
        else failed
            D->>O: next_try_at = 30 s, 2 min, 10 min, then hourly (newer rows wait)
        end
    end
    Note over W,G: after every poll and check run, independent of delivery
    W->>G: push each observation or check result (Bearer GATUS_TOKEN), a failed push is dropped
    W->>HC: bodyless GET HEARTBEAT_URL every poll
    Note over HC,TG: when the pings stop (PC off, asleep, frozen, logged off),<br/>Healthchecks.io alerts the owner on its own channel
```

- Writers pass codes only; `render()` turns them into sentences from `leafi/core/alerts.py`, so no device name, exception text or learner data reaches Telegram (egress table, `tests/test_privacy.py`).
- Configuration checks never repair anything; each has its own latch: one alert when a setting drifts, one when it passes again.
- Gatus has no alerting provider; it shows history only. The outbox is the record.
