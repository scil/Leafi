# Session panel: research and reference collection

- Checked: 2026-10-25 (all rows). Method: tiered-research (T1 owner docs decide; T3 exemplars illustrate, verified on the repo file; T4 points only).
- Next re-check: 2026-11-24 (standards/docs, gate 30 d); Chrome LNA rows gate 7 d.

## 1. Question and decision served

Question: how should a running `python -m leafi study` process (anyio on asyncio) expose a loopback-only endpoint that (a) shows live session state to a parent's page and (b) accepts typed commands (/skip, /stop, /next, /yes, free text) as non-voice utterances, with the existing stdlib web UI (`agent/webui`, port 8770) proxying to it?

Decisions served:
- D1 server mechanism inside the study process;
- D2 security controls on both hops (browser -> webui, webui -> study endpoint);
- D3 status transport (poll / SSE / websocket);
- D4 how the webui discovers the study endpoint's port and token;
- D5 how injected input is tagged, so it never counts as acoustic evidence (ADR-0013: `confirmed` needs acoustic evidence).

Repo facts used (read-only check): `leafi/devices/console.py:71` already bridges a stdin daemon thread with `loop.call_soon_threadsafe(q.put_nowait, ...)`; `agent/webui/__main__.py:225-228` subclasses `ThreadingHTTPServer` with `allow_reuse_address = os.name != "nt"`; `tests/test_go2rtc_camera.py:62` binds `("127.0.0.1", 0)`.

## 2. Sources

| # | Source | Tier | source-date | Taken | Not taken |
|---|---|---|---|---|---|
| S1 | https://docs.python.org/3.12/library/asyncio-dev.html (Concurrency and Multithreading) | T1-vendor | living page, 3.12 | asyncio objects are not thread-safe; use `call_soon_threadsafe` / `run_coroutine_threadsafe` from other threads | - |
| S2 | https://docs.python.org/3/library/asyncio-eventloop.html | T1-vendor | living page | `call_soon_threadsafe` must be used cross-thread; raises `RuntimeError` on a closed loop (shutdown race); `reuse_port` not supported on Windows; `reuse_address` auto-True only on Unix | Windows default for reuse_address (not stated on page) |
| S3 | https://docs.python.org/3/library/http.server.html | T1-vendor | living page | "not recommended for production"; `ThreadingHTTPServer` exists for browsers pre-opening sockets; header-injection warning for unsanitised `send_header` input | - |
| S4 | https://docs.python.org/3/library/socketserver.html | T1-vendor | living page | `shutdown()` must be called from another thread than `serve_forever()` or it deadlocks; `poll_interval` 0.5 s; `daemon_threads`; `block_on_close`; `allow_reuse_address` default False on TCPServer | - |
| S5 | https://raw.githubusercontent.com/python/cpython/3.12/Lib/http/server.py and .../socketserver.py | T1-vendor (source) | branch 3.12 | `HTTPServer.allow_reuse_address = 1`; `ThreadingHTTPServer.daemon_threads = True`; `protocol_version = "HTTP/1.0"`; SO_REUSEADDR set with no Windows guard | - |
| S6 | https://learn.microsoft.com/en-us/windows/win32/winsock/using-so-reuseaddr-and-so-exclusiveaddruse | T1-vendor | ms.date 2018-05-31, updated 2025-03-11 | SO_REUSEADDR on Windows lets a second socket hijack a bound port; servers should set SO_EXCLUSIVEADDRUSE; bind port 0 for ephemeral ports | Server-2003-era tables in detail |
| S7 | https://docs.aiohttp.org/en/stable/web_advanced.html (Application runners, Graceful shutdown) | T1-vendor | living page (section added 3.0) | `AppRunner` -> `setup()` -> `TCPSite(...).start()`; `runner.cleanup()` does graceful steps 1-6 (not "cancel remaining tasks") | - |
| S8 | https://docs.aiohttp.org/en/stable/web_reference.html (TCPSite, AppRunner) | T1-vendor | page names 3.14.4 | `TCPSite(host=None` = all interfaces, `port=0` ephemeral, `shutdown_timeout=60.0`, reuse_port not on Windows); `AppRunner(handle_signals=False)` default | - |
| S9 | https://anyio.readthedocs.io/en/stable/api.html | T1-vendor | living page (4.x) | `create_tcp_listener(local_host=None` = all v4+v6 interfaces, `reuse_port` not on Windows) returns `MultiListener`; `from_thread.run_sync(token=)` added 4.11; `to_thread.run_sync` | - |
| S10 | https://anyio.readthedocs.io/en/stable/basics.html | T1-vendor | living page | native asyncio libraries run under the asyncio backend; native tasks are not subject to AnyIO cancellation rules; threads started outside AnyIO cannot use `from_thread.run()` | - |
| S11 | https://anyio.readthedocs.io/en/stable/cancellation.html | T1-vendor | living page | level vs edge cancellation; cleanup awaits need `CancelScope(shield=True)` / `move_on_after(..., shield=True)` | - |
| S12 | https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html | T1-standard | living page | synchronizer token in header not cookie, not in URL/logs; custom header forces preflight; Origin check, `Origin: null` / missing is not same-origin evidence; `Sec-Fetch-Site` reject cross-site unsafe methods, sent to localhost; reject simple content types for JSON APIs | Double-submit cookie detail |
| S13 | https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html | T1-standard | living page | allowlist Origin on every handshake; CSWSH; token in first message, never in query string | - |
| S14 | https://jupyter-server.readthedocs.io/en/latest/other/full-config.html | T1-vendor | latest | `allow_remote_access=False` -> 403 for non-local Host (DNS rebinding); `local_hostnames=['localhost']`, loopback IPs accepted; `allow_origin` default empty; `disable_check_xsrf` | - |
| S15 | https://jupyter-server.readthedocs.io/en/latest/operators/security.html | T1-vendor | latest | token auth on by default, token accepted in `Authorization` header | Notebook trust, kernel encryption |
| S16 | https://raw.githubusercontent.com/jupyter-server/jupyter_server/main/jupyter_server/base/handlers.py | T3-exemplar (verified file) | main, 2026-10-25 | `check_host`: strip port, loopback IP or `local_hostnames`, else 403; `check_origin` allows missing Origin (scripts) and Origin==Host; token-authenticated requests skip XSRF | - |
| S17 | https://raw.githubusercontent.com/jupyter-server/jupyter_server/main/jupyter_server/serverapp.py | T3-exemplar (verified file) | main, 2026-10-25 | `jpserver-<pid>.json` in runtime dir, written via `secure_write`; removed in `_cleanup()` on shutdown (ENOENT ignored); `list_running_servers` skips JSONDecodeError (partial write), yields only if `check_pid(pid)`, else unlinks stale file | - |
| S18 | https://raw.githubusercontent.com/jupyter/jupyter_core/main/jupyter_core/paths.py | T3-exemplar (verified file) | main, 2026-10-25 | `secure_write` deletes then creates with 0o600; on Windows `win32_restrict_file_to_user` sets an ACL (current user + Administrators) via pywin32 or ctypes; opt-out env `JUPYTER_ALLOW_INSECURE_WRITES` | - |
| S19 | https://wicg.github.io/local-network-access/ | T1-standard (CG draft) | Draft CG Report 2026-08-07 | address spaces public/local/loopback; a request is gated only when target is "less public" than the initiator; loopback->loopback is not a local network request | Future scope (open issue) |
| S20 | https://developer.chrome.com/blog/local-network-access | T1-vendor | 2025-06-09, updated 2025-09-29 | Chrome gates public->local/loopback behind a permission prompt; prompt launched in Chrome 142; future: extend to local->localhost | - |
| S21 | Search results: blink-dev "Intent to Ship: Local network access restrictions"; localtonet.com, piunikaweb.com | T4-report | 2025-2026 | pointers: Chrome 141/142 rollout; reported WebSocket coverage from Chrome 147 (one secondary source) | Not admitted as fact |
| S22 | https://html.spec.whatwg.org/multipage/server-sent-events.html | T1-standard | living standard | per-server connection-limit problem for multiple EventSources; `retry`, `Last-Event-ID`; comment line ~15 s for idle proxies | - |
| S23 | https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events | T4-report (reference, points to S22) | modified 2026-09-03 | limit of 6 per browser per domain without HTTP/2; auto-reconnect until `.close()` | - |
| S24 | https://github.com/pipecat-ai/whisker (README) | T3-exemplar (verified README) | main, 2026-10-25 | `WhiskerObserver` per pipeline + `WhiskerServer` owns a WebSocket to the UI at `ws://localhost:9090`; observe-only, file sink option | No auth documented; hosted UI via ngrok |
| S25 | https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/processors/frameworks/rtvi/processor.py and .../observer.py | T3-exemplar (verified files) | main, 2026-10-25 | client `send-text` -> `LLMMessagesAppendFrame` with role `user`; `run_immediately` interrupts bot first; `client-message` -> `RTVIClientMessageFrame` for app handlers; observer pushes `user-transcription`, `bot-output`, `bot-llm-text`, `metrics` per frame | - |
| S26 | https://raw.githubusercontent.com/livekit/agents/main/livekit-agents/livekit/agents/voice/room_io/types.py and .../agent_session.py; https://docs.livekit.io/agents/server/startup-modes/ | T3-exemplar (verified files) + T1 doc | main, 2026-10-25 | default text-input callback: claim user turn, `interrupt()`, `generate_reply(user_input=text)`; string becomes `ChatMessage(role="user")`; modality carried in `InputDetails(modality="text"|"audio")`; console mode `lk agent console --text`, Ctrl+T toggle | Whether modality is persisted on the chat message (truncated) |
| S27 | https://raw.githubusercontent.com/openai/openai-realtime-console/main/client/components/App.jsx | T3-exemplar (verified file) | main, 2026-10-25 | push over WebRTC data channel; every client and server event logged in one list; typed text sent as `conversation.item.create` role `user` + `response.create` | - |
| S28 | https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/assist_pipeline/websocket_api.py and .../run.py | T3-exemplar (verified files) | dev, 2026-10-25 | `assist_pipeline/run` pushes events live over the HA websocket; `start_stage: intent` takes `input.text` (typed text enters mid-pipeline, skipping STT); admin-only `pipeline_debug/list|get` reads last `STORED_PIPELINE_RUNS = 10` runs held in memory | - |
| S29 | https://legacy-docs-oss.rasa.com/docs/rasa/writing-stories/ | T1-vendor (legacy OSS docs) | legacy, undated | `rasa interactive`: operator corrects predictions and exports them as training stories | Human handoff (not verified) |

## 3. Findings per question

### Q1. Serving HTTP from inside the running anyio/asyncio app

Thread-safety rule (S1, S2): asyncio objects are not thread-safe; any call from a non-loop thread goes through `loop.call_soon_threadsafe(cb, *args)` or `asyncio.run_coroutine_threadsafe(coro, loop)`. `call_soon_threadsafe` raises `RuntimeError` once the loop is closed, which happens on a secondary thread at shutdown (S2). AnyIO's `from_thread.run_sync` only works from AnyIO worker threads unless a token is passed (S9, S10).

| Option | Reading in-memory state | Shutdown on cancel | Windows | Dependency |
|---|---|---|---|---|
| (a) `ThreadingHTTPServer` in a daemon thread | Handler threads must not touch loop-owned objects. Safe patterns: loop publishes an immutable snapshot (e.g. a frozen dict / JSON bytes swapped by single reference assignment) that threads read; commands go back by `call_soon_threadsafe(queue.put_nowait, cmd)` (same as `console.py`). Wrap in `try/except RuntimeError` for the closed-loop race (S2). | Loop side: in a `finally`, call `server.shutdown()` from the loop thread via `to_thread.run_sync` (it blocks up to `poll_interval` 0.5 s; must not run on the serve thread, S4) then `server_close()`. `daemon_threads=True` is already the ThreadingHTTPServer default (S5), so open handler threads do not block exit. Shielded cleanup per S11. | `HTTPServer.allow_reuse_address = 1` sets SO_REUSEADDR with no Windows guard (S5); on Windows that allows port hijack (S6). The repo's webui already overrides it to `os.name != "nt"` -- reuse that subclass. Bind `("127.0.0.1", 0)` (S6: ephemeral ports; also dodges Windows reserved ranges). | stdlib; precedent in repo |
| (b) aiohttp `AppRunner` + `TCPSite` in the loop | Handlers run on the loop: read state directly, enqueue commands with `put_nowait`; no thread bridge. | `await runner.setup(); await TCPSite(runner, "127.0.0.1", 0).start()`; in `finally` with `CancelScope(shield=True)` + timeout: `await runner.cleanup()` (S7, S8, S11). aiohttp handler tasks are native asyncio tasks, not under AnyIO cancel scopes (S10); keep `shutdown_timeout` small (default 60 s, S8). `handle_signals=False` default, so it does not steal Ctrl+C (S8). Not documented by anyio or aiohttp specifically for "inside an anyio task group": works per S10's general rule, unverified by a test here. | `host=None` binds all interfaces (S8): must pass `"127.0.0.1"`. reuse_address auto only on Unix (S2, S8). | aiohttp already installed, but new import in `leafi/`; brings its own HTTP parser (security posture better than http.server, S3) |
| (c) anyio `create_tcp_listener` + hand-written HTTP | Same as (b), on the loop. | Listener closes with the task group; native AnyIO cancellation (S9, S11). | `local_host=None` = all v4+v6 interfaces (S9): must pass `"127.0.0.1"`. | No dependency, but a hand-written HTTP/1.x parser is new attack surface for a header-checking design. |

Firewall prompt on 127.0.0.1: not found in Microsoft docs (corpus: learn.microsoft.com Windows Firewall, Winsock pages); only T4 pointers say loopback-only binds do not prompt. Treat as needing a one-time measurement (gap G2).

Verdict Q1: (a) is the smallest change and has a precedent, provided reads go through an immutable snapshot and SO_REUSEADDR is off on Windows. (b) is the clean in-loop alternative if SSE or many endpoints are wanted later. (c) rejected.

### Q2. Exemplars of operator/debug consoles (only verified ones)

| Exemplar | State to UI | Injected input | Tagged as operator? | Excluded from data? |
|---|---|---|---|---|
| Pipecat RTVI (S25) | Push: observer sends a message per pipeline frame (transcriptions, bot output, metrics) | `send-text` -> user-role context message, optional interrupt; `client-message` -> app-defined frame | No: role `user`; only a separate frame type (`RTVISendTextFrame`) marks the path | Not addressed |
| Pipecat Whisker (S24) | Push: WebSocket from an in-process server, localhost:9090, observe-only | none | n/a | n/a; no auth documented |
| LiveKit Agents (S26) | Console mode in terminal; text mode | typed text -> interrupt -> `generate_reply(user_input)` as role `user` | Partly: `InputDetails.modality = "text"` vs `"audio"` | Not verified |
| OpenAI realtime console (S27) | Push over WebRTC data channel; one log of client+server events | `conversation.item.create` role `user` | No | Not addressed |
| Home Assistant Assist (S28) | Push of pipeline events over websocket during a run; last 10 runs kept in memory for an admin-only debug view | typed text starts the pipeline at the `intent` stage, skipping STT | Implicitly: the run's stages show no STT stage | Debug store is in-memory, bounded (10) |
| Rasa interactive (S29, docs only) | CLI | operator corrections | Yes, as intent | Opposite: corrections are exported as training data |

Pattern across exemplars: state is pushed per event; typed input is folded into the "user" role, and the only distinction is the entry path or a modality field. None verified ships an "operator" tag that downstream evaluation honours. For Leafi, the ADR-0013 rule (`confirmed` needs acoustic evidence) means the panel's typed utterances must carry their source explicitly (closest exemplar: LiveKit `modality="text"`; HA skipping the STT stage). Not found: Rhasspy/Wyoming satellite web UI (not searched to file level; gap G3).

### Q3. Loopback security

- DNS rebinding: check `Host` against an allowlist of loopback IPs and fixed names; 403 otherwise (S14, S16). Jupyter accepts any loopback IP and `localhost` after stripping the port.
- CSRF: OWASP (S12) ranks a per-session token sent in a custom header (forces CORS preflight; never in cookies-only, URL, or logs), plus Origin check (missing or `null` Origin is not same-origin evidence), plus `Sec-Fetch-Site` rejection of cross-site unsafe methods (sent to localhost too), plus rejecting simple content types (`text/plain`, form types) on JSON endpoints. The webui's existing Host + Origin + Content-Type + per-start token set matches S12 row by row. Jupyter differs: it allows a missing Origin for scripts and skips XSRF for token-authenticated requests (S16) -- acceptable there because the token is the secret.
- The second hop (webui -> study endpoint) is a non-browser client: Origin is absent, so the study endpoint should require a bearer token in a header and the loopback Host, and need not do Origin checks; it should also reject any request carrying an `Origin` header (a browser reached it directly) -- inferred from S12 + S16, not a cited rule.
- WebSocket, if ever used: Origin allowlist per handshake, token in first message, never in query string (S13).
- Chrome Local Network Access (2026): gates only requests from a more public initiator to a less public target (S19). A page served from `http://127.0.0.1:8770` calling its own origin is loopback->loopback: not gated (S19, S20). It does protect against a public web page probing 127.0.0.1 (prompt since Chrome 142, S20), but this is one browser's defence, not a substitute for the token. Reported, not confirmed: WebSocket coverage from Chrome 147 (S21).
- http.server's `send_header` does not sanitise CRLF (S3): never echo command text or state into headers.

### Q4. Status transport

- SSE from `ThreadingHTTPServer`: works in principle -- `daemon_threads=True` and HTTP/1.0 default (S5) let a handler hold the connection and write `data:` frames with flush; each open stream occupies one thread; disconnect is seen only on the next write; `shutdown()` stops accepting but does not end handler threads (S4). Through the webui proxy, the proxy also has to stream (a second held thread per viewer). Browsers without HTTP/2 cap SSE at about 6 connections per domain (S22, S23) -- relevant if the parent opens several tabs, since 127.0.0.1:8770 also serves other webui pages. Needs a comment heartbeat (~15 s, S22) and reconnect handling.
- Websockets: needs aiohttp/websockets in the study process and handshake hardening (S13); out of proportion for one viewer.
- 1 s polling: a GET returning the snapshot with a monotonic `version`; zero held threads; trivially proxied; latency up to 1 s, which is below a child's answer timescale. Exemplars push (Q2), but they stream audio-rate events to developers; the parent view needs state, not every frame.
- Verdict: 1 s polling (optionally `?since=<version>` returning 204/304 when unchanged). SSE deferred until a measured need.

### Q5. Discovery of port and token

- Jupyter (S17, S18): one runtime file per process, `jpserver-<pid>.json`, fields include url, port, token, pid; written with `secure_write` (delete-then-create, 0o600; on Windows an ACL for the current user + Administrators via pywin32 or ctypes); removed on clean shutdown; stale files are detected by readers: partial JSON is skipped, a dead pid causes `os.unlink` of the file.
- Applied to Leafi: the study process binds port 0, then writes `data/run/study-panel.json` (gitignored `data/`) with port, token, pid, start time, schema version, atomically (write temp + `os.replace`), and deletes it in its `finally`. The webui reads it on each proxy call; if pid is dead or connect fails, it reports "no session running" and may delete the file. Pid reuse on Windows is possible, so combine pid check with a connect + token probe (inference; Jupyter checks pid only).
- Windows permissions: `data/` sits in the owner's profile/repo; an ACL restriction like Jupyter's needs pywin32 or ctypes code -- owner decision (D-O2). Token in file is only as secret as the file; the threat on a single-user home PC is a browser page, which cannot read local files.

## 4. Decision pool

| # | Decision | Status | Rows |
|---|---|---|---|
| A1 | Endpoint = stdlib `ThreadingHTTPServer` subclass (reuse webui's `_Server` pattern: `allow_reuse_address = os.name != "nt"`) in a daemon thread, bound `("127.0.0.1", 0)` | adopt | S3, S4, S5, S6 |
| A2 | Loop publishes an immutable state snapshot (replace by reference); handler threads only read it; commands enter via `call_soon_threadsafe(queue.put_nowait, ...)` guarded for `RuntimeError` on a closed loop | adopt | S1, S2 |
| A3 | Shutdown in a shielded `finally`: `server.shutdown()` via `to_thread.run_sync` (not on the serve thread), then `server_close()`, then delete the runtime file | adopt | S4, S9, S11, S17 |
| A4 | Browser hop (webui): keep Host allowlist, Origin check (reject missing/`null` on unsafe methods), JSON-only Content-Type, per-start token in a custom header; add `Sec-Fetch-Site: cross-site` rejection | adopt | S12, S14, S16 |
| A5 | Study hop: bearer token header + loopback Host required; reject any request carrying `Origin` | adopt (inferred design, reviewer to confirm) | S12, S16 |
| A6 | Status by 1 s polling of a versioned snapshot | adopt | S4, S22, S23 |
| A7 | Runtime file with port, token, pid, started, schema; atomic write; removed on exit; readers treat dead pid or failed probe as stale | adopt | S17 |
| A8 | Typed panel input carries an explicit source (e.g. `source="panel"`/modality text) and never counts as acoustic evidence; operator commands recorded as such in session events | adopt (project rule ADR-0013; exemplars show the gap) | S25, S26, S28 |
| A9 | Never write user/command text into HTTP headers | adopt | S3 |
| F1 | aiohttp `AppRunner`/`TCPSite` in-loop server | defer: only if SSE/websocket becomes needed; then bind `127.0.0.1`, shielded `runner.cleanup()`, small `shutdown_timeout` | S7, S8, S10, S11 |
| F2 | SSE stream | defer: one thread per stream, proxy must stream, ~6-connection cap, heartbeat | S4, S22, S23 |
| R1 | anyio `create_tcp_listener` + hand-written HTTP | reject: own parser is new attack surface | S3, S9 |
| R2 | Relying on Chrome LNA instead of a token | reject: loopback->loopback is not gated; Chrome-only | S19, S20 |
| R3 | Token in URL query string | reject | S12, S13 |
| O1 | Should the panel's free-text answers be allowed to complete a reading item at all (versus only /skip, /next), given ADR-0013? | needs owner confirmation | S25, S26 (pattern), ADR-0013 |
| O2 | Restrict the runtime file with a Windows ACL (Jupyter `secure_write` style, pywin32/ctypes) or rely on the profile's default ACL | needs owner confirmation (privacy trade-off) | S18 |
| O3 | Are panel-typed turns stored in the session record (and shown in history), or kept out of practice/difficulty statistics only? | needs owner confirmation | S28, S29 |

## 5. Research gaps

- G1: No tier-1 doc covers aiohttp `AppRunner` started inside an AnyIO task group and cancelled; only the general mixing rule (S10). If F1 is taken, verify with a test.
- G2: Windows Defender Firewall behaviour for a 127.0.0.1-only bind is not documented in the Microsoft corpus searched; T4 says no prompt. Measure once on the owner's PC.
- G3: Rhasspy/Wyoming satellite web UI and Rasa human-handoff code were not verified at file level; not cited.
- G4: Whether LiveKit persists `modality` on the stored chat message (file truncated in fetch).
- G5: Chrome LNA extension to WebSockets (Chrome 147) is reported only by T4 (S21); irrelevant to A6 (polling) but relevant to F1/F2.
- G6: Pid reuse risk for stale-file detection on Windows is an inference, not from a source.
