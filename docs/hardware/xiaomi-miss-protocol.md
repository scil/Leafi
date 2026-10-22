# Xiaomi MISS protocol: static-analysis notes

What the Mi Home app's MISS library and its Java callers do, read by disassembly and decompilation. These are **not measurements**: nothing here was run against the camera, and no row may be relied on by a design until a probe or a client trace confirms it (`README.md` → Measure before relying). Decompiled Xiaomi code is not kept in this repository; only names, offsets and our own summary.

## Source

| Item | Value |
|---|---|
| APK | 米家 `com.xiaomi.smarthome` 11.7.709, from Xiaomi's app store (`app.mi.com`, appId 75542), 2026-10-20; sha256 `73335D3C17DFF3E73097DB7E2F86A373B7EB2C67611DC82749883AB2DA3F0B6E` |
| Library | `lib/arm64-v8a/libmiss.so` (1,050,360 bytes); siblings `libPPCS_API.so`, `libmiio_PPPP_API.so` (CS2), `libIOTCAPIs.so`, `libTUTKGlobalAPIs.so` (TUTK) |
| Tools | Ghidra 12.1.4 headless (default auto-analysis, full decompile dump) for `libmiss.so`; jadx 1.5.6 (`--no-res`) for `classes12.dex` + `classes2.dex` |
| Compared with | go2rtc master `pkg/xiaomi/miss/client.go`, `internal/xiaomi` (2026-10-20) |

## Layering

- `libmiss.so` is a transport: sessions, auth, encryption, command and media send/receive. It is driven from Java through `com.xiaomi.mistream.MIStream` (`Java_com_xiaomi_mistream_MIStream_*` exports: `missClientSessionOpen`, `missClientSessionLanOpen`, `missCmdSend`, `missSendAudioData`, …).
- Command ids and payloads are chosen by the Java caller: `missCmdSend` passes a command id and a byte buffer through to `miss_cmd_send` (0x11dfc0).
- Incoming commands go back up to Java in `miss_on_cmd` (0x1398ec) through a JNI callback. For 0x107 (speaker start response) and 0x10A (stream control response) it hands Java the payload's first `uint32` as a decimal string; every other command is passed as raw bytes.
- The command-name table `miss_get_cmd_info` (references at 0x12176c–0x1218bc) is the only place the strings `speaker start req`, `speaker start resp `, `speaker stop`, `get audio format`, `audio format response` are used: log names, not logic.
- The Java side is in the base APK (`classes12.dex` holds `missClientSessionLanOpen` and `missCmdSend`; `classes2.dex` holds `miss_get_vendor`), not only in the downloaded camera plugin.

## Speaker exchange (Q1)

| Finding | Where | Consequence for go2rtc |
|---|---|---|
| The speaker-start response 0x107 carries one `uint32`, forwarded to Java as a number (likely a status code; meaning not yet read) | `miss_on_cmd` 0x1398ec | go2rtc defines `cmdSpeakerStartRes` but never reads it and sleeps 1 s instead |
| `libmiss.so` has no speaker state machine: no wait, timeout, or ordering of 0x106 / 0x107 / 0x108 / 0x10B | whole library | — |
| The app's talk start (`XmStreamClient.streamStartCall`) sends speaker start 0x106 with the JSON payload `{"speakerStart":1}`, then immediately audio start (the camera microphone). Talk stop (`streamStopCall`) sends 0x108 with `{"speakerStop":1}` | `MIStream.speakerStart` / `speakerStop`, `XmStreamClient` | go2rtc sends 0x106 with no payload and never sends 0x108. Whether the camera treats the two differently is unmeasured |
| The Java layer does not wait for 0x107: `isCallStarted` (which gates `missSendAudioData`) turns true as soon as the 0x106 send returns 0 | `MIStream.lambda$missCommandSend$7`, `AnonymousClass3.onSuccess` | The base app has no fixed sleep either; its first audio is gated only by the send succeeding |
| 0x107 and every other incoming command are passed up unparsed to the React Native camera plugin (`on_command` → `onCtrlData`) | `MIStream.onMissOnCmd`, `XmStreamClient` `IStreamHandler.on_command` | Anything the app does with 0x107 (wait, retry, show "busy") lives in camera plugin 4433, which is downloaded at runtime and is not in the APK |
| A "call" in the base app is speaker start plus audio start on one session; no separate duplex or call-mode command exists in `MIStream` (the plugin can still send arbitrary command ids through `missCmdSend`) | `MIStream` constants and methods | Consistent with ADR-0014 option 2 finding no public call mode; not proof for the plugin |

## LAN session (Q2)

| Finding | Where |
|---|---|
| Normal path: the session key is `crypto_box_beforenm(device_public, client_private)` (libsodium X25519 precompute); auth is command 0x100 with the public key and sign | `generate_share_key` 0x126c40, `miss_authorized_send` 0x1245f0 |
| LAN path: `missClientSessionLanOpen` takes did, model, IP, `share_key`, `p2p_id` and `init_string` from Java and calls `cs2_client_connect` directly; no vendor fetch happens inside the library on this path | `Java_…missClientSessionLanOpen` 0x13a468, `miss_client_session_lan_open` 0x11be8c |
| LAN auth is command 0x100 carrying the raw 32-byte ChaCha20 `share_key` instead of public key and sign; the camera answers with "authorized lan" / "authorized lan failed" | `miss_authorized_lan_send` 0x1219d0, `miss_cmd_process` |
| When Java passes a LAN flag, a built-in CS2 init string replaces the cloud-supplied one | `miss_client_session_lan_open` |
| Keys expire: the cloud vendor reply has `p2p_id_expires` | `miss_cjson_get_p2pkey_expires` |

| The app calls `missClientSessionLanOpen` only when a network flag equals 2 **and** the model is `careco.camera.650` (a car camera) and cached LAN parameters exist; every other model, `chuangmi.camera.069a01` included, opens the normal cloud-vendor session | `MIStream` session open (`MissLanUtils.get`, model check) |
| The LAN `p2p_id`, `init_string` and `expires` are copied from an earlier cloud vendor reply and cached per device id in the SharedPreferences file `sp_miss_lan_params`; the `share_key` and remote IP come in through `setLanInfo` from `XmStreamClient` | `MissLanParams`, `MissLanUtils`, `MIStream.setLanInfo` |

Conclusion: the app gives our camera no LAN session; the cloud round-trip per connection is how the official client works too. Whether the camera firmware would accept a LAN session anyway is unknown and not worth a probe without a reason. go2rtc has no LAN path; every connection calls `/v2/device/miss_get_vendor`.

## Key expiry and cloud dependency (Q3)

Motivation: the camera fetches session keys from the cloud on every connect (`AGENTS.md` Known traps), so an unstable internet link breaks reconnects. The question was whether a key can be cached and reused to survive outages.

| Finding | Where |
|---|---|
| The cloud reply carries `vendor.vendor_params.expires`, read as a Java `long` and cached on disk with `p2p_id` and `init_string`. So a key is reusable across connections — the app does reuse it | `MIStream` `onSuccess` (`optLong("expires")`), `MissLanParams`, `MissLanUtils` |
| `libmiss.so` treats the expiry as opaque: `miss_set_p2p_id_expires` stores up to 9 bytes in a global, `miss_get_p2p_id_expires` returns them, never compared to a clock. The value is passed to the camera during auth, so the **camera** enforces expiry, not the client | `miss_set_p2p_id_expires` 0x124160, `miss_get_p2p_id_expires` 0x12421c |
| No clock comparison of the MISS `expires` exists in the decompiled `classes12.dex` / `classes2.dex`; any validity check lives in camera plugin 4433 (not in the APK) | jadx scan (only OAuth-token expiries compare to `currentTimeMillis`) |
| go2rtc reads only the vendor id and TUTK uid from `vendor_params`; it never reads `expires` and never caches the response, so it re-fetches every connection | go2rtc `internal/xiaomi` vendor parse |

Two internet dependencies per connection, not one: (1) the Xiaomi cloud key fetch; (2) the CS2 P2P rendezvous to locate the camera (CS2 supernodes over WAN; avoided by a direct-IP LAN connection, which `miss_client_session_lan_open` supports via `Remote_ip`). Caching the vendor response removes only (1); a LAN direct session removes both. The host and camera share a LAN, so the LAN path is the stronger answer to an unstable uplink — but it is untested on `chuangmi.camera.069a01`, go2rtc has no LAN path, and it still needs one cloud handshake to seed the key.

Unknown until measured: the numeric `expires` window (a server-set value; never captured), whether it is an absolute epoch or a TTL, and how strictly the camera enforces a reused key past it.

## Next

- Read the real `expires` value first (read-only, no camera change). Options, cheapest first: (a) intercept go2rtc's own `miss_get_vendor` HTTPS on the host with mitmproxy, trusting mitmproxy's CA on the host only — go2rtc is our process, no app and no eMudhra key involved; (b) add one debug log line to the go2rtc vendor parse in a throwaway build; (c) read `sp_miss_lan_params.xml` from the phone (`did;p2p_id;init_string;expires`) if root or an app-data backup is available; (d) Frida-hook `miss_json_get_p2pkey_expires` or the Java `optLong("expires")`. Record only the `expires` field — the response also holds the session key and sign, which are secrets.
- Then measure camera-side enforcement: reuse a captured vendor response after the window and see whether the camera still authorizes. Needs the camera; a go2rtc caching or LAN change then goes through plan mode (it touches `tools/go2rtc/`) and codex review.
- The meaning of the 0x107 status value and any wait-for-0x107 logic are in camera plugin 4433; reading it needs the plugin bundle from a phone (root or app-data backup) or a Frida trace of the running app.
- Cheapest go2rtc experiment suggested by these notes: send `{"speakerStart":1}` with 0x106, wait for 0x107 instead of the fixed 1 s sleep, and send `{"speakerStop":1}` with 0x108 at the end. It plays on the camera speaker, so it runs only with the owner present, through plan mode (it touches `tools/go2rtc/`) and codex review, and is measured with `p5_camera_latency.py` and `p27_duplex.py`.

- The meaning of the 0x107 status value and any wait-for-0x107 logic are in camera plugin 4433; reading it needs the plugin bundle from a phone (root or app-data backup) or a Frida trace of the running app.
- Cheapest go2rtc experiment suggested by these notes: send `{"speakerStart":1}` with 0x106, wait for 0x107 instead of the fixed 1 s sleep, and send `{"speakerStop":1}` with 0x108 at the end. It plays on the camera speaker, so it runs only with the owner present, through plan mode (it touches `tools/go2rtc/`) and codex review, and is measured with `p5_camera_latency.py` and `p27_duplex.py`.
