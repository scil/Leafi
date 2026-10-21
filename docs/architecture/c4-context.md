# C4 L1 — system context

Mermaid is this repository's renderer (GitHub and Obsidian preview); see `engineering/conventions.md`.

```mermaid
flowchart LR
    Learner(["Learner (child, 10)"])
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
    Claude["Claude API (text only)"]
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
    Leafi -- page excerpts, miscues, summaries --> Claude
    Leafi -- status + one frame --> Push --> Parent
    Parent -- devices.yml, tasks.yml, books --> Leafi
```

Trust boundary: everything inside `LAN` may see pixels and audio. The two arrows that cross out carry text only (Claude) or text plus a single parent-addressed snapshot (push). The Xiaomi camera itself needs internet once per connection to fetch P2P keys from Xiaomi cloud; that traffic carries no media.
