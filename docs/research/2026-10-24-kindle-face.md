# Kindle (7th generation) as a Face (reference collection)

Checked: 2026-10-24. Method: `tiered-research`. T1 = the owner's own docs and source (kindlemodding.org pages and its `jailbreaks.json` / `models.json`, the FBInk repository); T4 = press coverage, "reported" only. Every claim traces to a row of §5. Rows marked *(inferred)* or *(not verified)* were not confirmed against a primary source. Nothing was downloaded and no device was touched.

Decision it serves: a Face adapter (`leafi.core.ports.Face`, one method `async show(Display)`) that draws Leafi's text on the owner's Kindle 7th generation (KT2), firmware 5.12.2.2, after a software jailbreak. Owner's choices (2026-10-24): jailbreak directly, no browser-only stage; Face first, more Kindle features later; the Kindle can be registered to Amazon, so the method is **WinterBreak**.

## 1. Which jailbreak fits KT2 on 5.12.2.2

- kindlemodding.org maps device code `C6` ("KindleBasic") and `DD` ("KindleBasicKiwi") to the nickname `KT2`, "Kindle (7th Generation)" (S3).
- Its wizard data lists two software jailbreaks for KT2 (S2):

| Method | Firmware rule in `jailbreaks.json` | Needs Amazon registration | Needs lockscreen ads | How it runs |
|---|---|---|---|---|
| WinterBreak | 5.6.1.1 – 5.18.0.2 | **yes** | no | files copied to the Kindle root, then the Kindle Store opens Mesquito (S4) |
| WinterBreak2 | 5.6.1.1 – 5.16.3 (+ 5.16.5) | no | no | `winterbreak2` folder on the root, then the Experimental Browser opens the WinterBreak2 page; needs internet (S5) |

- **Disagreement (T1 vs T1):** the WinterBreak2 page tells devices with firmware *below 5.16.4* to use the original WinterBreak, "which requires Amazon registration" (S5), while `jailbreaks.json` accepts 5.12.2.2 for WinterBreak2 (S2). Moot for this device: it can be registered and both sources accept WinterBreak on 5.12.2.2.
- WinterBreak steps (S4): airplane mode on and reboot; extract the release archive on the PC and copy its files to the Kindle root (on Linux/macOS include the hidden `.active_content_sandbox`); eject; open the Kindle Store and accept turning airplane mode off; when Mesquito loads, open the WinterBreak icon; after ~30 s the GUI restarts, else retry.
- Popcorn (KT2 page) is a hardware method: open the case, bridge test pads TP1706–TM401, load via MFGTool / `imx_usb` (S6). The site advises against it where a software jailbreak exists. Fallback only.
- Both pages: fill the storage first so an OTA update cannot land mid-process; afterwards delete fillers and any `.bin` in the root; updates are then blocked (S4, S5).
- Bricked devices after failed attempts are *reported* (R1).
- 5.12.2.2 is the last firmware for KT2 *(not verified; recalled, not checked)* — if true, no future OTA can close the jailbreak by upgrade.

## 2. Drawing on the screen: FBInk

- FBInk claims "the full Kindle lineup, starting from the K2" (S7); KT2 is not named, support is *(inferred)*.
- It ships inside NiLuJe's packages (S7), so a post-jailbreak Kindle with KUAL/MRPI usually has it *(reported)*.
- CLI facts used by a design (S8): `-c` clear before printing, `-k` clear and stop, `-m`/`-M` centre horizontally/vertically, `-S N` font scale (1–~45), `-t regular=FILE,size=N,...` TrueType (only in `OPENTYPE` builds), `-f` flashing full refresh, `-W A2|DU|GL16|GC16|AUTO` waveform.
- **Daemon mode** (S8): `fbink -d NUM_LINES` reads text from the FIFO `/tmp/fbink-fifo` (override with `FBINK_NAMED_PIPE`); it does not abort on errors and sends stdout/stderr to `/dev/null`. A client only writes to the pipe.

## 3. Getting `Display` from Leafi to the Kindle (options for the design)

None of these is measured yet; each is a candidate for `derive-project-plan`.

| Option | Kindle side | Leafi side | Notes |
|---|---|---|---|
| A. Pull, HTTP long-poll | shell loop: fetch next message, pipe to FBInk | small LAN HTTP endpoint fed by `KindleFace.show()` | survives Kindle sleep/reconnect by re-polling; needs an HTTP client on the Kindle *(curl/wget availability not verified)* |
| B. Push over SSH | dropbear from USBNetwork *(not verified for KT2)* | `ssh kindle fbink …` per message | key setup; one connection per message unless kept open |
| C. MQTT | an MQTT client binary *(none confirmed on Kindle)* | publish to the existing broker (host port 18830) | reuses Leafi's broker; client must be cross-built |

Open questions to measure on the device: Wi-Fi reconnect after screensaver, how to keep the screensaver off while studying *(a `powerd` `lipc` property is reported, not verified)*, full-refresh ghosting vs partial refresh speed for a 1–3 line `say`, CJK glyphs (needs a TrueType font with Chinese).

## 4. Constraints from this repository

- Face is a port with one method; adding hardware = one adapter module, one `ADAPTERS` line, one `devices.yml` entry, and a measurement first (`docs/architecture/device-ports.md`).
- `Hub.show()` wraps each Face in `wait_for(face_timeout_s)` and logs failures (`leafi/core/hub.py`), so a slow or offline Kindle must not block; `show()` should enqueue and return.
- Display text crosses the LAN only; it is not a cloud egress, but plaintext LAN delivery of a child's study text should be stated in the design against `docs/architecture/quality-attributes/security.md`.

## 5. Sources

| ID | Tier | Source | source-date | checked | Used for |
|---|---|---|---|---|---|
| S1 | T1 | kindlemodding.org jailbreak wizard — https://kindlemodding.org/jailbreak-wizard.html (logic: https://kindlemodding.org/jailbreakFinder.js) | undated (living) | 2026-10-24 | filter rules: model, registration, ads, firmware min/max/outliers |
| S2 | T1 | kindlemodding.org `jailbreaks.json` — https://kindlemodding.org/jailbreaks.json | undated (living) | 2026-10-24 | WinterBreak / WinterBreak2 KT2 rules |
| S3 | T1 | kindlemodding.org `models.json` — https://kindlemodding.org/models.json | undated (living) | 2026-10-24 | KT2 = device codes C6, DD |
| S4 | T1 | WinterBreak — https://kindlemodding.org/jailbreaking/WinterBreak/ | undated (living) | 2026-10-24 | steps; "does NOT work on firmware 5.18.1 and beyond" |
| S5 | T1 | WinterBreak2 — https://kindlemodding.org/jailbreaking/WinterBreak2/ | undated (living) | 2026-10-24 | steps; "below 5.16.4" → WinterBreak |
| S6 | T1 | Popcorn KT2 — https://kindlemodding.org/jailbreaking/Legacy/Popcorn/KT2.html | undated (living) | 2026-10-24 | hardware fallback |
| S7 | T1 | FBInk README — https://github.com/NiLuJe/FBInk | master, undated | 2026-10-24 | device coverage, packaging |
| S8 | T1 | FBInk CLI.md — https://github.com/NiLuJe/FBInk/blob/master/CLI.md | master, undated | 2026-10-24 | flags, daemon FIFO |
| R1 | T4 | Liliputing on WinterBreak — https://liliputing.com/?p=175028 ; Notebookcheck guide — https://www.notebookcheck.net/A-guide-to-jailbreaking-and-installing-apps-on-your-Kindle.1207399.0.html | 2025 | 2026-10-24 | brick reports; "firmware 5.18.0.1.0.1 or earlier" |
