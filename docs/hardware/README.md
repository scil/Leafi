# Measured hardware facts

The one home for what a device or a combination of devices was **measured** to do. A device is an Ear (microphone), a Mouth (speaker), an Eye (camera) or several, behind an adapter (ADR-0002/0003). Each hardware and software combination differs in duplex behaviour and latency, so a number holds only for the versions it was measured on.

| File | Holds |
|---|---|
| [`xiaomi-camera-069a01.md`](xiaomi-camera-069a01.md) | Xiaomi camera `chuangmi.camera.069a01` through the host go2rtc (Ear, Mouth, Eye) |
| [`pc-dji-headset.md`](pc-dji-headset.md) | The desk PC with the DJI Mic Mini Bluetooth headset (Ear, Mouth) |
| [`combinations.md`](combinations.md) | Ear × Mouth matrix: duplex, echo exposure, end-to-audible, what the gate must cover |
| [`xiaomi-miss-protocol.md`](xiaomi-miss-protocol.md) | Static-analysis notes on Xiaomi's MISS library (not measurements) |

## Rules

- **Measure before relying.** A new device, a new Ear/Mouth combination, or a new path to an existing device (a different bridge, protocol or adapter) gets its duplex behaviour, latency and microphone recovery measured with a `scripts/probes/` probe, and its datasheet row written, before any design or ADR depends on it. Unmeasured fields stay in the datasheet's *Unmeasured* list; a design that needs one names the probe that will fill it.
- **Re-measure after an upgrade.** A camera firmware update, a go2rtc rebuild or upgrade (`tools/go2rtc/PATCHES.md`), a Bluetooth or driver change, or a new headset invalidates that device's rows until the probe is rerun. Record the new run as a new row; mark the old one superseded, do not delete it.
- **Audible probes need the owner.** A probe that plays sound on the camera runs only when the owner says they are present (`--i-am-present`); silent probes (`p2`, `p3`, `p6`) may run any time.

## Row format

Every measured fact carries: the date, the versions (camera firmware, go2rtc build, exe hash, OS device name), the probe command that reproduces it, and the evidence (plan Progress entry, commit, ADR section). A number without these is an observation, not a datasheet row.

Datasheets hold numbers; ADRs hold the decisions taken from them and link here; `docs/plans/tech-debt.md` rows hold the work and link here for the numbers; the plan's Progress keeps the dated narrative of each run.
