# Device ports and adapters

How Leafi stays hardware-agnostic (ADR-0002). Port signatures live in `leafi/core/ports.py`, the adapter registry in `leafi/devices/__init__.py`, the build in `leafi/app.py`; this page only draws them. The runtime path of one spoken line is in [`flows/device-routing.md`](flows/device-routing.md).

## Which adapter provides which port

```mermaid
classDiagram
    direction LR
    class Eye
    <<Protocol>> Eye
    class Ear
    <<Protocol>> Ear
    class Mouth
    <<Protocol>> Mouth
    class Face
    <<Protocol>> Face
    class Listener
    <<Protocol>> Listener
    class Presence
    <<Protocol>> Presence
    class Notifier
    <<Protocol>> Notifier
    class Synthesizer
    <<Protocol>> Synthesizer

    class Hub {
        say()
        show()
        notify()
        listener()
        eye()
    }
    Hub o-- "0..*" Mouth
    Hub o-- "1..*" Face
    Hub o-- "0..*" Eye
    Hub o-- "1..*" Listener
    Hub o-- "0..*" Notifier
    Hub o-- "0..1" Synthesizer

    Go2rtcCamera ..|> Eye
    Go2rtcCamera ..|> Mouth
    LocalPcDevice ..|> Ear
    LocalPcDevice ..|> Mouth
    LocalPcDevice ..|> Face
    ConsoleDevice ..|> Listener
    ConsoleDevice ..|> Face
    NotifierDevice ..|> Notifier
    VoiceListener ..|> Listener
    VoiceListener --> Ear : reads
    VoiceListener --> Vad : end-points
    VoiceListener --> Recognizer : transcribes

    class FrigatePresence
    <<planned>> FrigatePresence
    FrigatePresence ..|> Presence
    class XiaozhiDevice
    <<planned>> XiaozhiDevice
    XiaozhiDevice ..|> Ear
    XiaozhiDevice ..|> Mouth
    XiaozhiDevice ..|> Face
```

- An adapter may implement more ports than `config/devices.yml` assigns it; the `capabilities` list decides which Hub slots it fills.
- `VoiceListener`, `Vad` and `Recognizer` live in `leafi/services/asr/`; any Ear can feed a `VoiceListener`, so a new microphone needs no Listener code.
- Multiplicities are what the Hub accepts: zero Mouths is valid (text on Faces only); a Listener and a Face always exist because the console is added when none is configured.
- Not drawn: the go2rtc camera's Ear (opt-in once measured, `docs/hardware/`) and the Wyoming adapter (ADR-0008).

## How the Hub is built at startup

```mermaid
flowchart TD
    Y["config/devices.yml + .env"] --> P{"schema valid?<br/>known adapter, known capability,<br/>unique name, version 1"}
    P -- no --> X["DevicesConfigError: stop"]
    P -- yes --> V{"every required ${VAR} set?"}
    V -- no --> D["device disabled + warning"]
    V -- yes --> C["registry factory(adapter)<br/>Adapter(name, options, settings)"]
    C -- raises --> D
    C --> I{"isinstance(obj, port)<br/>for each listed capability"}
    I -- no --> W["capability dropped + warning"]
    I -- yes --> S["Hub slots: eye · ear · mouth · face · listener · notifier"]
    S --> K{"any Listener and Face?"}
    K -- no --> CON["add console<br/>(typed Listener + Face)"]
    K -- yes --> T
    CON --> T{"--text?"}
    T -- yes --> TX["typed Listener only<br/>voice policy none"]
    T -- no --> A{"study.listener's Ear present<br/>and ASR model ok?"}
    A -- yes --> VL["VoiceListener = Ear + VAD + ASR<br/>(energy end-pointer if Silero is missing)"]
    A -- no --> FB["typed Listener + warning"]
    TX --> M
    VL --> M
    FB --> M
    M{"policy ≠ none<br/>and ≥ 1 Mouth?"}
    M -- yes --> SY["build Synthesizer (services/tts)"]
    M -- no --> H
    SY --> H["Hub(slots, synthesizer, policy,<br/>study_eye, study_listener)"]
```

- Only schema errors stop startup; a missing variable, a failing constructor or a false capability claim costs one device or one slot, with a warning `python -m leafi devices` prints.
- Adapters have no import-time side effects, so a dead device fails in its constructor, inside the `try` that disables it.
- Adding hardware = one adapter module, one line in `ADAPTERS`, one `devices.yml` entry, and a measurement before a design relies on it (`docs/hardware/README.md`).
