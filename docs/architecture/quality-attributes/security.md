# Security and privacy

## Red lines (from the first track, extended for study)

1. **Images, faces, poses never leave the LAN.** Book pages are images. OCR, vision judge and barcode decoding run locally. Enforced by: `tests/test_privacy.py` import allow-list; the only module that may build a cloud request is `leafi/services/brain/claude.py`, and its request builder accepts text only (typed signature, test-asserted).
2. **The learner's voice stays local by default.** ASR and pronunciation scoring are local. Audio clips are not persisted unless `AUDIO_KEEP_CLIPS=true`, and then only under `cache/audio/` with `PAGES_RETAIN_DAYS` cleanup. Enforced by: config default + `tests/test_storage.py` retention test.
3. **Cloud prompts carry no identity.** No names from Frigate labels, no learner name, no device names in Brain prompts; the learner's chosen name for Leafi is allowed. Enforced by: `coach.build_prompt` schema test.
4. **Cameras never enter the bathroom**; the study camera points at the desk. Enforced by: advisory (physical).
5. **Child-transparent.** Leafi tells the child when it is listening and when it is looking; the Face shows a listening indicator. Enforced by: advisory, review.

## Secrets

`.env` is gitignored; `.env.example` holds placeholders only. API keys are read by pydantic-settings; never logged. Enforced by: `.gitignore` + review.

## Network exposure

Every Leafi server binds `127.0.0.1` except the planned xiaozhi WebSocket server, which binds the LAN address and requires the device token from `devices.yml`. Frigate/MQTT ports are host-mapped without auth today (tech-debt item TD-3).

## Third parties and what they receive

| Party | Receives | Why |
|---|---|---|
| Anthropic (Claude API) | page excerpts (≤ 3 sentences), miscue words, session summaries, coach instructions | tutoring lines, explanations, questions |
| Xiaomi cloud | P2P key exchange per camera connection | camera protocol requirement; no media |
| Microsoft (edge-tts) | the text to be spoken | Chinese TTS; can be disabled with `TTS_BACKEND_ZH=kokoro` once a zh voice is set |
| Bark / Telegram | parent notification text, optional one frame | parent asked for it |

Anthropic's usage policy forbids using the API for face or identity recognition; the design never sends images, so the question does not arise.
