# Flow: how a line reaches the learner, and who owns listening

Composition: `leafi/app.py` is the composition root (overview.md). The Hub receives constructed adapters and a `Synthesizer` (core protocol implemented by `services/tts`); core never imports them.

```mermaid
sequenceDiagram
    participant T as study.session
    participant G as ListeningGate (session-owned)
    participant H as Hub.say(text, lang, slow)
    participant TTS as Synthesizer
    participant M1 as Mouth: desk_cam (go2rtc)
    participant M2 as Mouth: pc
    participant F as Faces
    T->>G: pause()            — capture stops; buffered audio discarded
    T->>H: say("Let's try 'through' once more.")
    H->>F: show(text)         — always first, never waits for audio
    alt policy != none and ≥1 Mouth
        H->>TTS: synth(text, lang, voice, speed) → clip (cache key = text+lang+voice+speed+model)
        par policy = all
            H->>M1: play(prepared clip)   — adapter pads/transcodes; returns at estimated playback end
            H->>M2: play(clip)
        and policy = primary
            H->>M1: play(clip)
        end
        H-->>T: returns when every Mouth returned or SAY_TIMEOUT_S hit (hung Mouth cancelled)
    else no Mouth
        H-->>T: returns at once
    end
    T->>G: resume(after=max drain_s over the Mouths that played)   — drain applied once, here
```

Rules:
- **Half-duplex in v1.** Listening is paused from `say()` start until every Mouth has returned, plus the largest `drain_s` among the Mouths that played (camera adapter 0.6 s, PC 0.2 s), applied once by the gate. Adapter AEC claims do not change this in v1 (ADR-0011).
- **Completion semantics.** `Mouth.play()` returns at the estimated playback end and nothing more: PC = process exit; go2rtc = HTTP accepted + head pad (0.9 s) + clip duration. `Mouth.stop()` cancels (go2rtc: `DELETE /api/streams?src=` of the pushed source; PC: kill ffplay). `drain_s` is a Mouth attribute the gate reads.
- **Cancel during playback.** Spoken `stop` works only while listening (the Listener is paused during playback); during playback the cancel path is the console/Face control (`/stop`, a key press), which calls `SpeechSerializer.stop()` → `Mouth.stop()` on each Mouth. Leafi says this once per session (ADR-0012 §8).
- **One speaker at a time.** A session-level `SpeechSerializer` queues `say()` calls; `stop` clears the queue and cancels the current clip.
- **Transitional two-process topology.** The study session holds an exclusive speech lease (`data/leafi.lock`, pid + expiry); the habit track's `agent/speaker.py` checks the lease and logs instead of speaking while it is held. Until the habit track moves onto the Hub this is the only arbitration (ADR-0011).
- **Selection.** `config/devices.yml` names `study.eye` and `study.listener` explicitly; the console listener always accepts control commands in parallel (`/stop`, `/skip`, `/page N`, `/fix`). If the selected Ear disappears, the session enters PAGE_UNCERTAIN-like `LISTENER_LOST`, tells the learner, and continues in text mode when the console is available.
- A Mouth or Face that fails is logged and skipped; `say()` never raises for a device error.
