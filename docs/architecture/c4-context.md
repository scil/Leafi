# C4 L1 — system context

Mermaid is this repository's renderer (GitHub and Obsidian preview); see `engineering/conventions.md`.

```mermaid
flowchart LR
    Learner(["Learners (the household's children)"])
    Parent(["Parent"])
    subgraph LAN["Home LAN — images and audio stay here"]
        Leafi["Leafi agent"]
        Cam["Cameras with speakers<br/>(Xiaomi 3 PTZ today, Tapo later)"]
        PC["PC mic / speakers / terminal"]
        ESP["ESP32 box with mic, speaker, screen (planned)"]
        Frigate["Frigate + mosquitto"]
        Ollama["Ollama (local vision judge / fallback brain)"]
        Anki["Anki desktop + AnkiConnect"]
    end
    Claude["Claude API · edge-tts · Open Library<br/>(text only, pseudonymised)"]
    Push["Bark / Telegram"]

    Learner -- reads aloud, talks, corrects --> Cam
    Learner --> PC
    Learner --> ESP
    Cam -- frames, audio, speaker --> Leafi
    PC --> Leafi
    ESP --> Leafi
    Frigate -- person events --> Leafi
    Leafi -- frames --> Ollama
    Leafi -- notes, due cards --> Anki
    Leafi -- "page text, counts; a learner's words only if allowed" --> Claude
    Leafi -- "counts + surrogate name; alerts (habit track: + one frame)" --> Push --> Parent
    Parent -- devices.yml, tasks.yml, books --> Leafi
```

Trust boundary: everything inside `LAN` may see pixels and audio. Every arrow that crosses out leaves through `leafi.privacy.egress` (ADR-0018): text only, every household name, school and listed term replaced, a learner's words redacted like any text (ADR-0021: by content, never by source); the socket guard refuses any other connection. The habit track's push may add a single parent-addressed snapshot (`NOTIFY_WITH_SNAPSHOT`, ADR-0011). The Xiaomi camera itself needs internet once per connection to fetch P2P keys from Xiaomi cloud; that traffic carries no media.
