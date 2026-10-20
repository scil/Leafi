# Flow: how a line reaches the learner (voice policy)

```mermaid
sequenceDiagram
    participant T as track (study/habits)
    participant H as Hub.say(text, lang)
    participant TTS as services.tts
    participant M1 as Mouth: desk_cam (go2rtc)
    participant M2 as Mouth: pc
    participant F as Faces (console, esp32 subtitle)
    T->>H: say("Nice. Let's try 'through' once more.", lang=en)
    H->>F: show(text)  — always, before audio
    alt mouths available and policy != none
        H->>TTS: synth(text, lang) → cached clip
        par policy = all
            H->>M1: play(clip)
            H->>M2: play(clip)
        and policy = primary
            H->>M1: play(clip)
        end
        H-->>T: returns when the slowest Mouth reports done (or timeout)
    else no mouth
        H-->>T: returns immediately; the text on Faces is the output
    end
```

Rules:
- Faces get the text before any audio so a slow TTS never hides the message.
- A Mouth that fails is logged and skipped; `say()` never raises for a device error.
- `say()` has a per-call timeout (`SAY_TIMEOUT_S`, default 20) so a dead camera does not stall a session.
- Listening is paused while Leafi speaks unless the adapter declares echo cancellation (`capabilities: [ear, mouth]` with `aec: true`, e.g. the ESP32).
