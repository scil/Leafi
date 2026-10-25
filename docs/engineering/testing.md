# Testing

Runner and command: `pytest.ini` + `.venv\Scripts\python -m pytest -q` (asyncio mode auto).

## Layers

| Layer | What | Fixtures |
|---|---|---|
| Pure logic | alignment (multi-utterance scenarios), miscue transitions, page matching, correction/revision chain, difficulty weights, habit scorer | plain data, temp SQLite |
| Track with mocks | the study harness (`study.harness.loop.run_session`) end to end with a scripted console listener, recording Faces, mock services; deadlines moved by the test, not waited for | `tests/conftest.py`; `tests/harness_session.py` (whole sessions), `tests/harness_world.py` (one activity on a `World`), `tests/harness_helpers.py` (menu, policy, negotiation on a `Session` with scripted talk) |
| Adapters against fakes | fake go2rtc HTTP server (records `src`, simulates duration), stateful fake AnkiConnect (notes, cards, lost-ack mode, parent edits), blocking/cancellable fake Mouth | `tests/fakes/` |
| Privacy | the wire beneath egress recorded (`tests/egress_helpers.py::mock_egress`: a mock transport, TEST-NET resolution, real attempt rows) with canaries; `LEAFI_NO_NETWORK=1` subprocess run; real sockets on a loopback gateway port for the guard and the real `anthropic` SDK | `tests/test_privacy.py`, `tests/test_egress.py`, `tests/test_netguard.py`, `tests/test_pseudonym.py`, `tests/test_detector.py` (model cases with `LEAFI_HW_TESTS=1`) |
| Hardware / models | real sherpa-onnx, RapidOCR on fixture images and desk photos, Kokoro, OpenPronounce | `@pytest.mark.hardware`, run with `LEAFI_HW_TESTS=1` |

## Hardware measurement before reliance

pytest cannot tell how a real device behaves. A new device, a new Ear/Mouth combination or a new path to an existing device gets a `scripts/probes/` probe that measures its duplex behaviour, latency and microphone recovery, and its `docs/hardware/` datasheet row, before any design depends on it; rerun the probe after a camera firmware update or a go2rtc rebuild. The rules, the row format and the matrix: `docs/hardware/README.md`. Probes that make the camera speak run only with the owner present (`--i-am-present`).

## Never mocked

`alignment`, `corrections`/revisions, `storage` (temp file), `pages.current_text()` precedence, the speech lease.

## Required scenarios (from the codex review)

- Alignment: clean read; substitution; mid-sentence skip; trailing insertion; hesitation across two utterances; sentence restart; reread of three words; 15 % ASR noise; **unattempted suffix never deleted; rereads never penalised; cursor explainable**.
- Durable side effects: Anki add succeeds but the response is lost → no duplicate on retry (tag dedupe); crash between correction insert and revision insert → rollback; parent edits a note → reconciliation keeps Leafi fields; `answerCards` after a lost response is not repeated.
- Temporal: TTS failure with a Mouth present; hung Face; slow Mouth past `SAY_TIMEOUT_S` cancelled; concurrent `say()` serialised; listening gate reopens after drain; `stop` during playback.
- Controls: `stop`/`skip`/`page N` from every state; a page sentence that contains "stop" is read, not executed.
- Page identity: number match; observation match; two candidates → PAGE_UNCERTAIN; camera lost → assessment suspended.
- Privacy: canaries absent from every outbound body; no-network session completes; Notifier has no frame; a learner's and a guest's words leave redacted, never refused for their source (ADR-0021), with every listed name replaced and the detector skipping book fields only; an Ollama model is local only when listed on `LOCAL_MODELS` on a loopback host (M7 D1); (Chinese and mixed-script included); a spent token, a changed body or header, a version or `.env` change between prepare and send are refused; a guard refusal is never retried; retained sockets (TLS included) are shut down when their grant ends.
- The suite itself runs with the socket guard enforcing and an offline egress (`tests/conftest.py`): no test resolves a name or connects off the machine; a test that needs a server uses a loopback destination or `mock_egress`.
- Prompt injection: page text with instructions; Brain reply with a disallowed action.
- Habit track: speaker respects the speech lease.

## Fixtures to create

- `tests/fixtures/pages/*.png` rendered from known text with PIL (OCR ground truth) and `tests/fixtures/pages/desk/*.jpg` real captures (hands, curvature, glare, a spread) taken by the owner; referenced by hash if not committed.
- `tests/fixtures/audio/*.wav`: Kokoro-synthesised sentences (correct and one substituted word) for plumbing; a separate parent-labelled child-speech set (held out, not committed) for the false-correction evaluation that gates `PRON_AUTO_JUDGE`.

## Regression themes

- A correction must never resurrect or delete history; it invalidates with a reason.
- `say()` must return with zero Mouths and with a hung Mouth.
- Session restart must close stale sessions and release the lease.
