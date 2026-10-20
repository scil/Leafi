---
status: accepted
date: 2026-10-20
amends: 0011
revised: 2026-10-20 (codex design rounds 1–4, gpt-6-astra high: claims narrowed to the evidence; camera Ear reduced to an invariant and known gaps; round 4 no findings)
---

# The camera mutes its microphone while it talks; v1 reading stays half-duplex

## Context

ADR-0011 and `docs/architecture/flows/device-routing.md` make v1 reading half-duplex: the session's `ListeningGate` (`leafi/core/hub.py`) pauses the Listener while any Mouth plays, whatever an adapter claims about echo cancellation. P-5 (2026-10-20) then found the camera's RTSP microphone track silent while a clip played through the camera speaker (TD-27), although the Mi Home app holds two-way conversations through the same camera. The question was whether our path or the camera silences the microphone, and whether Leafi could keep hearing the learner while it speaks through the camera.

## Evidence

**Source (go2rtc v1.9.14, the base of our patched build; upstream master checked 2026-10-20, unchanged in this respect).** The `xiaomi/miss` producer holds one P2P connection. Microphone packets arrive on cs2 channel 2 and `Producer.Start` forwards every one to the `recvonly` receiver unconditionally; speaker packets leave on channel 3. Talk is opened by `AddTrack` with a bare `cmdSpeakerStartReq` (0x106, no parameters) followed by a fixed 1 s sleep; `cmdSpeakerStop` (0x108) is never sent. Nothing in go2rtc mutes or drops the microphone. Our two local patches (`tools/go2rtc/PATCHES.md`) touch only cs2 payload copying and buffer overflow.

**Measurement (`scripts/proto/p27_duplex.py`, camera `chuangmi.camera.069a01`, owner counting aloud ~1 m from the camera, PC headset microphone as reference, 30 s pull, push at 12 s).** Resolution is about one second: the playback window is placed from HTTP acceptance and the adapter's sleep, the track offset is estimated from wall time minus decoded duration (which also counts teardown), and the muted track is not digitally zero (peak |x| 2–5, the same as the room floor between counted words), so mute edges show only where speech borders them.

| Run | Clip | Camera mic rms/s around playback | Camera transcript in the playback window | Headset in the same window | After playback |
|---|---|---|---|---|---|
| 1 | 1.7 s of digital silence (+0.9 s head, 0.6 s tail pad) | 572, 102, 76, **0, 10**, 33 (s 12–17) | nothing ("fourteen" lost) | "Fortune" (= fourteen) | camera hears "fifteen" (0.71) … "twenty-five" (0.92–1.00) |
| 2 | "Let's try that word once more." | 327, **1, 1**, 62, 321 (s 12–16) | nothing; none of Leafi's words | the whole line, word for word | camera hears speech again within about a second |

Run 1 rules out simple echo subtraction: an echo canceller has nothing to subtract from digital silence, yet a voice the headset caught did not reach the camera track. The likely explanation is a camera-side hold-to-talk suppression that holds while the talk stream runs, whatever it carries, and releases on its own within about a second after it ends, without `cmdSpeakerStop`. The exact trigger (speaker-start command, packet arrival, or suppression inside the camera's audio processing) is not identified; separating them needs start-without-packets and interrupted-packet runs, which the decision below does not depend on. Run 2: in the playback window the camera track is at the room floor and carries none of Leafi's words.

## Options considered

1. **Patch go2rtc to keep the microphone open.** Nothing to patch: go2rtc already forwards every packet; the mute is in the camera firmware.
2. **A different talk command (a two-way "call" mode).** The Mi Home app may request one; its parameters are unknown and would need a capture of the app's P2P traffic. Out of v1 scope; recorded as the reopening condition.
3. **A second P2P session for the microphone.** Untested. The only evidence is that the Mi Home viewer displaces go2rtc's session (TD-25), which suggests but does not prove a one-client limit; whether suppression is per session is unknown. Deferred: it would need a second credentialed P2P client and a new measurement.
4. **The PC microphone as Ear with our own echo guard** (drop Listener segments that overlap playback and match the spoken text). The headset heard Leafi's line word for word (run 2), so the guard would be load-bearing, and a learner word that overlaps or matches the coach line (the line often repeats the target word) would be dropped or mistaken. No product requirement asks for barge-in (`docs/product.md` H7: reading is half-duplex). Rejected for v1.

## Decision outcome

v1 reading stays half-duplex on every path; the `ListeningGate` is unchanged and no setting is added. ADR-0011's rule now has a measured reason for the camera:

- **PC Ear + camera Mouth (the v1 configuration):** the PC microphone hears every line Leafi speaks; the gate is what keeps Leafi's voice out of the transcript. Nothing changes.
- **Camera Ear + camera Mouth (not built; TD-14):** the camera suppresses its own microphone during talk, so there is no echo to keep out, but the gate's reopening is not yet safe for it. `play()` returns before the 0.6 s tail pad is streamed and `drain_s` is that same 0.6 s, so the gate reopens at about the last talk packet, while the camera microphone needs up to about a second more to come back. This ADR fixes the requirement, not the mechanism; the camera Ear's own design (TD-14) owns the mechanism and gets its own codex design round before code.
  - **Invariant:** no audio captured before the camera microphone has recovered from a talk stream reaches VAD/ASR, and listening is never reported open to the session before that point.
  - **Known gaps the design must close:** `ListeningGate.speak()` owns `resume(after_s)` and learns only the largest `drain_s`, not which Mouth played or which Ear listens, so a recovery allowance needs a path through the gate (or must live in the Listener); `VoiceListener` discards by *arrival* time, while RTSP delivery lags capture by a variable 0.6–1.9 s (pull start in P-2/p27; steady state unmeasured), so a capture-time rule needs a measured upper bound on that lag and a conservative choice when it is exceeded. The recovery time itself must be measured with sub-second resolution (an acoustic marker, not counting).
  - **Failure:** a microphone that does not come back cannot be told from a quiet room by level (P-2: silence is not a fault), so it is not a `ListenerLost` condition; `ListenerLost` stays "the pull ended or failed". The guard against a non-recovering microphone is the repeated speak → listen check below, and the Confirmation run after firmware or go2rtc changes.
- **Consequence for TD-24's fix path** (a talk channel held open for a whole Practice/CHECK turn to pay the handshake once): streaming idle silence keeps the camera microphone suppressed (run 1), so that variant works only with a PC Ear. Keeping the go2rtc source alive while sending no packets during listening windows is a different, untested option; it must be measured (does the microphone come back, and does the next line skip the handshake?) before a camera Ear relies on it.

Reopen this ADR when: a two-way talk mode is found that keeps the camera microphone live (then measure camera-side echo cancellation with run 2's protocol before trusting it), a second session is shown to hear during talk, or a product requirement for barge-in appears.

## Consequences

- No code change in v1: the only Ear that exists is the PC's, and the gate already covers it. `device-routing.md` states the measured camera behaviour next to the half-duplex rule.
- TD-14's trigger for the camera Ear gains the reopening requirement above and a repeated speak → listen check (several coach lines in a row, the learner's first word after each line transcribed), not only isolated intelligibility.
- go2rtc never sending `cmdSpeakerStop` does not keep the microphone suppressed (it comes back on its own); it stays noted under TD-24 as part of the talk-session lifecycle.

## Confirmation

Rerun `scripts/proto/p27_duplex.py --i-am-present --mic DJI --clip silence` after any go2rtc upgrade or camera firmware update, owner counting throughout. All three must hold: the camera transcript has the counting before the push, nothing in the playback window while the headset has a word there, and the counting again after it. A camera track silent throughout is a broken microphone, not a confirmation. `tests/test_hub.py` keeps enforcing the gate.
