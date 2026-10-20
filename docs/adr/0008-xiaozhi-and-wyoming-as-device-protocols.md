---
status: proposed
date: 2026-10-19
---

# ESP32 and satellite devices join through the xiaozhi WebSocket protocol and Wyoming, not a Leafi-specific protocol

## Context

The owner wants an ESP32 screen/speaker/mic as one possible device. Two open protocols already have firmware and hardware behind them: xiaozhi-esp32 (ESP32 boxes, Opus 16 kHz, JSON control, subtitles via `tts.sentence_start`) and Wyoming (Home Assistant satellites, JSONL + PCM).

## Decision

Leafi implements a **xiaozhi-compatible WebSocket server** adapter (`devices/xiaozhi_server.py`) providing Ear, Mouth and Face (subtitles, `alert`), and later a **Wyoming client** adapter for HA satellites. Leafi defines no new wire protocol. Firmware stays stock.

## Consequences

- Opus encode/decode in Python (`opuslib` or `pyogg`) and a `websockets` server; AEC flag from the device `hello` controls listen-while-speaking.
- Device tokens live in `devices.yml`; the server binds the LAN address (security.md).
- Status `proposed` until the first ESP32 is on the desk; accepted when `tests/test_xiaozhi_protocol.py` passes against a recorded handshake.
