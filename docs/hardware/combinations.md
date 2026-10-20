# Ear × Mouth combinations

What each pairing of a listening device (Ear) and a speaking device (Mouth) was measured to do. Device numbers live in the datasheets; this matrix says what follows for the pair. v1 reading is half-duplex on every path (ADR-0011, ADR-0014): the `ListeningGate` pauses the Listener while any Mouth plays, plus the largest `drain_s`.

| Ear ↓ / Mouth → | Camera (go2rtc talk) | PC (ffplay) |
|---|---|---|
| **PC + DJI headset** (v1 configuration, `study.listener: pc`) | **Measured.** The headset hears Leafi's camera line word for word, so the gate is load-bearing. End-to-audible 2.7–3.3 s (camera datasheet). The gate reopens `drain_s` 0.6 s after `play()` returns. | **Unmeasured** (`study --mouth pc`): echo exposure, end-to-audible, drain. |
| **Camera RTSP** (not built, TD-14) | **Measured.** No echo: the camera suppresses its microphone while its speaker sounds and recovers ≈ 0.2 s after the last sound. The gate's reopening is not yet safe for it (ADR-0014 invariant): RTSP lag and recovery must be covered by the Ear's own design. | **Unmeasured**: whether the camera hears the PC speaker, and from which distance. |

## Before relying on a cell

A cell marked unmeasured, or a cell whose devices changed version since the row was written, needs at least:

1. **Duplex**: does the Ear hear the Mouth's line, and does it hear a near voice while the line plays? `p27_duplex.py` is the pattern: two tracks (the Ear under test plus a reference microphone), one push at a known time, the owner counting aloud, 100 ms rms with `--keep --fine`.
2. **Latency**: push → accepted and end-to-audible for a word and a line, timed by a second microphone next to the Mouth (`p5_camera_latency.py --mic`).
3. **Recovery**: time from the line's last sound to the Ear hearing again.

Write the numbers into the device datasheets and the conclusion into this matrix in the same commit.
