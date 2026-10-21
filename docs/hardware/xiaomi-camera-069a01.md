# Xiaomi camera `chuangmi.camera.069a01` through the host go2rtc

Capabilities used: Eye (`frame.jpeg`), Mouth (go2rtc push → P2P talk), Ear (RTSP audio track; not built, TD-14). Adapter: `leafi/devices/go2rtc_camera.py`.

## Versions every row below was measured on

| Item | Value |
|---|---|
| Camera firmware | `5.3.1_0548`; Mi Home camera plugin version 4433 (read by the owner in the Mi Home app on 2026-10-20; assumed unchanged since the day's runs, as no update was applied) |
| go2rtc | `1.9.14+dev.b5948cf.dirty` = v1.9.14 + the two local patches in `tools/go2rtc/PATCHES.md`; `tools/go2rtc/go2rtc.exe` sha256 `E4E5FC2D75094FFA5034BCEAF00B4E06A643712E705646648169D5F7D73321C3` |
| Host | Windows 11 desk PC, host go2rtc via `scripts\win\go2rtc-host.bat`; RTSP `rtsp://127.0.0.1:2554/cam_xiaomi` |
| Talk path | push of a prepared clip (`audio_codec` opus), go2rtc `AddTrack`: bare `cmdSpeakerStartReq` (0x106) + fixed 1 s sleep; `cmdSpeakerStop` never sent |
| Microphone path | RTSP `audio recvonly OPUS/48000/2` (the SDP always says this for Opus; it says nothing about the real mic format) |

All runs: 2026-10-20, the owner (adult) ~1 m from the camera in its current wide-shot placement.

## Duplex

| Fact | Value | Probe | Evidence |
|---|---|---|---|
| Duplex class | **half-duplex, camera-side suppression** of its own microphone keyed to audible speaker output. Not a full-duplex echo canceller: the near voice (the owner) is lost too while a line sounds | `p27_duplex.py --i-am-present --mic DJI --clip 2 --keep --fine` | ADR-0014 Evidence, second measurement; commits 5976a3e, 46a1791 |
| Not go2rtc | go2rtc v1.9.14 `xiaomi/miss` forwards every microphone packet unconditionally; upstream master unchanged (checked 2026-10-20) | source reading | ADR-0014 Evidence |
| Silent talk stream | an open talk stream carrying 1.7 s of digital silence did **not** suppress the microphone in 4 of 4 runs (14:15–14:35); one morning run (≈ 1 s resolution) lost one word and did not reproduce | `p27_duplex.py --i-am-present --mic DJI --clip silence --keep` | ADR-0014 runs 1 and second measurement |
| Inside the 0.9 s silent head pad | the microphone still hears (a word inside the pad was heard) | same, `--clip 2` | ADR-0014 second measurement, run A |
| Level while suppressed | rms 0–4 per 100 ms, not digital zero (room floor between words is peak 2–5), so mute edges are visible only against speech | same | ADR-0014 |
| Recovery after a line | **≈ 0.2 s** after the line's last audible sound (2 runs, 100 ms rms on the headset clock). Superseded: "within about a second after the talk stream" (morning, ≈ 1 s resolution) | same | ADR-0014 second measurement |
| `cmdSpeakerStop` (0x108) 200 ms after the last packet | no measurable effect on suppression or recovery (test go2rtc build, not shipped) | same, test exe | Plan Progress 2026-10-20 14:15–14:35 |
| Two-way "call" talk mode | none found in public MISS clients | search | ADR-0014 option 2 |

## Mouth: latency and padding

| Fact | Value | Probe | Evidence |
|---|---|---|---|
| POST push → HTTP accepted | 1.21–1.34 s (12:20 run), 1.61–1.63 s (12:35), 2.23 s (12:45); variable, includes go2rtc's fixed 1 s sleep after `cmdSpeakerStartReq` | `p5_camera_latency.py --i-am-present --only N --mic DJI` (headset mic next to the camera) | Plan Progress P-5 12:20–12:45; commits 6252249, 4550f1a |
| End-to-audible (push → first sound) | 2.73 s ("Let's try that word once more.", 1.71 s clip); 2.71 s (2.65 s line); 3.34 s ("through", 0.79 s clip, accepted 2.23 s that run) | same | same |
| Camera's own decode delay | ≈ 0.2 s (residual after accepted + 0.9 s head pad; not measured on its own) | same | same |
| Head pad / tail pad in use | `PAD_HEAD_S` 0.9 s, `PAD_TAIL_S` 0.6 s (`go2rtc_camera.py`); these are settings, **not** measured needs | — | — |
| Short-clip tail loss | the 0.79 s word lost 0.2–0.3 s of its tail (heard 0.48–0.6 s; the owner heard "thrill" for "through") despite the 0.6 s tail pad; 1.71 s and 2.65 s lines heard whole by the owner (level-detected 1.44 s and 2.44 s) | same | Plan Progress P-5; TD-24 |
| Idle channel noise | none: rms 5–8 flat until the word (an earlier "hiss" was the Bluetooth headset fading) | same | Plan Progress P-5 12:45 |

## Ear: signal and recognition

| Fact | Value | Probe | Evidence |
|---|---|---|---|
| Stream | Opus, 25 packets/s (40 ms frames, 201–351 bytes ≈ 60 kbit/s), no DTX (packets flow in a silent room, so judge by decoded level only) | `p2_camera_mic.py --seconds 8` | Plan Progress P-2 11:55; commit c8ccd4a |
| SNR at ~1 m | speech rms 475 against a floor of 1.8, i.e. 20·log10(475/1.8) ≈ 48 dB (earlier notes say 45 or 49 dB; use the raw values); speech peaks 963–7368 (≈ −13 dBFS). The floor is measured after the camera's AGC and Opus, so this is not an acoustic room SNR; at 50 % words, SNR is not what limits recognition | same | same |
| ASR word accuracy at ~1 m | **50 %**: Parakeet TDT 0.6B v2 int8 matched 6 of 12 tokens of the fixture passage (adult reader); right words confidence 0.75–0.93, wrong 0.15–0.55. Target for the camera Ear: ≥ 80 % at the reading position (TD-14) | same | same |
| AGC | levels swing 5–10× between runs | `p27_duplex.py --keep` | ADR-0014 second measurement |
| RTSP pull start | 0.7 s (P-2); 0.6–1.9 s across P-2 and p27 pulls; the wall-time-minus-decoded estimate varied 0.9–3.3 s and is unusable for placing events | `p2_camera_mic.py`, `p27_duplex.py` | Plan Progress P-2; Surprises (TD-27) |
| RTSP lag vs the headset track | steady 0.3–0.4 s (camera behind the DJI headset), measured from the owner's syllables | `p27_duplex.py --keep` | ADR-0014 second measurement |

## Eye

| Fact | Value | Probe | Evidence |
|---|---|---|---|
| `frame.jpeg` latency | 2.9 s at 1920 the first time, then ≈ 1 s | `p3_ocr_compare.py --capture 3 --out cache/desk` | Plan Surprises (P-3 on the desk); commit 73e06bb |
| Frame-diff noise floor | 2.3–3.0 grey levels between stills 0.8 s apart (hands 37–66) | same | same |
| Overlay | burnt-in timestamp and a "mi" logo, read by OCR as confident lines | same | same |
| Page geometry (current placement) | page ≈ 20 % of the frame, text line ≈ 15 px at 1920 (TD-21) | same | same |

## Failure modes

| Mode | Symptom | Recovery | Evidence |
|---|---|---|---|
| Mi Home app viewing displaces go2rtc's P2P session (TD-25) | `cs2: unknown msg f1f00000`, EOF on every dial, push → HTTP 500 "can't find consumer", empty frames | `scripts\win\go2rtc-restart.bat`; `health.ps1` flags it (one silent frame per stream) | Plan Surprises (P-5) |
| Camera unreachable | P2P dial times out after 5 s and retries; `frame.jpeg` → HTTP 200 with an empty body after 5.2 s (TD-20). ICMP ping fails even when P2P works, so "no ping" is not "offline" | check the camera's DHCP address in `go2rtc-host.yaml` (do not print the file) | Plan Surprises (P-2, P-3) |
| No internet | P2P keys are fetched per connection; firewalling the camera breaks it | do not firewall | `AGENTS.md` Known traps |
| Stock go2rtc | static on the speaker and dropped connections | the patched exe only (`tools/go2rtc/PATCHES.md`) | PATCHES.md |

## Unmeasured

- The head pad the camera's fade-in actually needs, and whether a longer tail pad or a later teardown saves short clips (TD-24 steps 3–4).
- Whether a **long-lived** talk channel streaming idle silence keeps the microphone hearing and lets the next line skip the handshake (TD-24 step 2; only 1.7 s silent streams were measured).
- Recovery time with an acoustic marker rather than counting (ADR-0014 asks for it before a camera Ear).
- Steady-state absolute RTSP capture lag (only the pull start and the lag relative to the headset are known).
- ASR word accuracy with a child reading at the real reading position, and after the camera moves closer (TD-14, TD-21).
- Whether a second P2P session hears during talk (ADR-0014 option 3).
- Speaker loudness and intelligibility at the learner's position beyond the owner's judgement.
