---
status: accepted
date: 2026-10-19
amends: 0003
---

# One egress policy for every network call; v1 is the smallest loop that tutors

## Context

Codex review round 1 found the privacy boundary stated three ways (images never leave the LAN; notifier contract with a frame; two-module internet allow-list that edge-tts and Open Library already break), the legacy habit track able to upload a snapshot to Telegram, OpenPronounce defaulting to gTTS, and v1 carrying ESP32/Wyoming/Tapo, habit consolidation, a local Brain fallback, a vision OCR fallback and automatic phoneme judgement before the core loop exists.

## Decision outcome

### Egress policy (security.md is the owner; this ADR records the decision)

| Destination | Allowed payload | Module | Switch |
|---|---|---|---|
| Claude API | selected book text (≤ 3 sentences), miscue words, intent minimised to an enum + target word, session summary (counts only), coach instructions | `leafi/services/brain/claude.py` | `ANTHROPIC_API_KEY` empty → static phrases |
| Microsoft edge-tts | the text to be spoken | `leafi/services/tts/edge.py` | `TTS_BACKEND_ZH=edge` |
| Open Library | ISBN digits only | `leafi/study/books.py` via `services/catalog` | `BOOK_LOOKUP=openlibrary|off` |
| Bark / Telegram | text only in the study track | `leafi/devices/notifiers.py` | `NOTIFY_*` |
| Xiaomi cloud | P2P keys (go2rtc, outside Leafi) | — | — |
| Model downloads | none from Leafi at runtime; `python -m leafi doctor --download` only | `leafi/doctor.py` | explicit flag |

Everything else is LAN-only. Enforcement: `tests/test_privacy.py` installs an `httpx` transport that records every request from the study loop under a synthetic sensitive canary (learner name, school, handwritten label text, audio bytes) and asserts canaries never appear in any outbound body, plus a subprocess test with networking denied (`LEAFI_NO_NETWORK=1` makes any non-loopback connect raise) that must still complete a text-mode session.

Identity redaction: `REDACT_TERMS` (set by the parent with `python -m leafi setup --redact`; empty until then, `doctor` warns) are replaced locally in the page window before any cloud payload. Learner free text never goes to the Brain in v1 (see below).

**Habit-track parent snapshot.** The repository boundary (AGENTS.md) governs: images do not leave the LAN. `agent/notify.py` attaches a frame to the parent's Telegram only when the owner sets `NOTIFY_WITH_SNAPSHOT=true` in `.env` (default `false`, a 3-line change plus a test in S1). The owner's 2026-08 design is thereby kept as an explicit opt-in on their own phone, not as a default. The `Notifier` port has no frame parameter; the study track never attaches one.

**Learner text never reaches the cloud in v1.** Intents are rule-based; explanation targets are words/phrases of the page or "this sentence"; comprehension answers are compared locally with the Brain-generated keywords; the exhaustive outcome partition (`correct` / `incorrect` / `unavailable`) is ADR-0013 → CHECK outcomes. The Claude payload is therefore: the redacted page window (≤ 3 sentences), candidate words, an intent enum + target, counts-only summary, and the fixed coach instructions. `REDACT_TERMS` is defence in depth against identity inside page text (a handwritten name) and is populated by `python -m leafi setup --redact "<name>,<school>"`; `doctor` warns when it is empty.

Pronunciation backend: reference synthesis is Kokoro (offline); gTTS is disabled by configuration; model checkpoints are provisioned by `doctor`, never downloaded at inference; inference must pass with `LEAFI_NO_NETWORK=1`.

### v1 scope (amends ADR-0003 and the plan)

- Devices: console, PC mic/speaker/terminal, Xiaomi camera Eye + Mouth. ESP32 (ADR-0008), Wyoming, Tapo and habit consolidation (S4/S5) move to their own future plans.
- Services: Brain = Claude with application-owned fallback to static phrases; the Ollama Brain fallback and the qwen3-vl OCR second opinion keep their ports but are **deferred** (not installed, not configured by default). OCR failure asks for a recapture, then for the learner to read the first line, then offers typed page text.
- S1 uses static/mock speech plus cloud explanations; real TTS arrives with S3.
- Automatic pronunciation judgement is gated: `PRON_AUTO_JUDGE=false` until a held-out, parent-labelled child-speech evaluation (≥ 40 flagged words) shows a false-correction rate ≤ 15 %; the threshold and the result are recorded in the plan when measured.
- Lexicon loops are advisory in v1: raw OCR and ASR observations are always stored; OCR snapping proposes candidates shown to the learner/parent; ASR hotword biasing is off (`ASR_HOTWORDS=off`) until a biased-vs-unbiased miscue comparison is recorded.

## Consequences

- Fewer moving parts before the loop is proven; the ports stay so nothing is thrown away.
- The habit track keeps one behaviour (snapshot to Telegram) that the study track forbids; the owner owns that decision.

## Confirmation

Privacy tests above; `python -m leafi doctor` shows deferred backends as `deferred`, not `missing`.
