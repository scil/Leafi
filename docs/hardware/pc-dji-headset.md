# Desk PC with the DJI Mic Mini Bluetooth headset

Capabilities used: Ear (`sounddevice` capture), Mouth (ffplay). Adapter: `leafi/devices/local_pc.py`; `config/devices.yml` device `pc`.

## Versions every row below was measured on

| Item | Value |
|---|---|
| OS | Windows 11 Pro for Workstations, desk PC (RTX 5070 Ti) |
| Input device | DJI Mic Mini, Bluetooth hands-free profile; MME device 1, nominal 44.1 kHz; a WASAPI twin exists |
| Audio stack | sounddevice 0.5.6, PortAudio 19.7 |
| Output device | **not recorded** |

All runs: 2026-10-20.

## Ear

| Fact | Value | Probe | Evidence |
|---|---|---|---|
| Format delivered | 16 kHz mono int16 from PortAudio without our resampling (MME and WASAPI) | `p6_capture.py --device DJI --seconds 3` | Plan Surprises (P-6); commit 8298ef4 |
| Device naming | the fragment `DJI` matches the same device under four host APIs; `local_pc` prefers WASAPI, then MME | same | same |
| Capture start | ≈ 1.2 s after opening (Bluetooth) | same | same |
| Callback cadence | every 96–112 ms, no overflow flag, also under a CPU burn | `p6_capture.py --load` | same |
| Unplug / Bluetooth drop | nothing raised; callbacks stop (hence the 3 s watchdog → `ListenerLost`) | `p6_capture.py` | same |
| Bluetooth start-up noise | the first capture after connecting can carry start-up noise | `p5_camera_latency.py --mic` | Plan Progress P-5 12:35 |
| Hears the camera speaker | yes: in p27 run 2 the headset transcribed the camera's line word for word, so this Ear depends on the listening gate | `p27_duplex.py --i-am-present --mic DJI --clip 2` | ADR-0014 run 2 |
| Other microphones | the Realtek USB microphone is exposed only under WDM-KS (not openable as a default device) | `p6_capture.py` | Plan Surprises (P-6) |

## Mouth

| Fact | Value | Probe | Evidence |
|---|---|---|---|
| `drain_s` | 0.2 s — a setting in `local_pc.py`, **not** measured | — | — |

## Failure modes

| Mode | Symptom | Recovery | Evidence |
|---|---|---|---|
| Silent default device (TD-26) | when the headset drops off Bluetooth the OS default input becomes "Voicemeeter Out A1", a virtual device delivering zeros; capture "works" and hears nothing | name the microphone in `devices.yml`; TD-26 fix path | Plan Progress P-5 12:35 |

## Unmeasured

- PC Mouth end-to-audible latency and the drain it needs.
- Whether the headset microphone hears the PC's own output (echo exposure for PC Ear + PC Mouth).
- ASR word accuracy on this Ear at the reading position (adult or child); SNR.
- Behaviour on the WASAPI twin versus MME beyond the delivered format.
