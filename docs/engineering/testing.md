# Testing

Runner and command: `pytest.ini` + `.venv\Scripts\python -m pytest -q` (asyncio mode auto).

## Layers

| Layer | What | Fixtures |
|---|---|---|
| Pure logic | alignment, miscue classification, page fingerprint, lexicon rebuild, difficulty weights, habit scorer | plain data |
| Track with mocks | `study.session` end to end with `MockHub` (console listener fed a script, recording faces), `services.*.mock` | `tests/conftest.py` |
| Adapters against fakes | fake go2rtc HTTP server, fake AnkiConnect, fake xiaozhi client | `tests/fakes/` |
| Hardware / models | real sherpa-onnx, RapidOCR on fixture images, Kokoro | `@pytest.mark.hardware`, skipped unless `LEAFI_HW_TESTS=1` |

## Never mocked

`alignment`, `corrections`, `storage` (uses a temp SQLite file), `pages.text` precedence.

## Fixtures to create

- `tests/fixtures/pages/*.png`: pages rendered from known text with PIL (deterministic OCR ground truth), plus 2–3 real photos the owner takes of the child's current book (gitignored if copyright is a concern; referenced by hash).
- `tests/fixtures/audio/*.wav`: sentences synthesised with Kokoro reading the fixture text correctly and with one substituted word; used by the hardware-marked ASR/alignment tests.

## Regression themes

- A correction must never resurrect an old OCR miscue.
- `say()` must return with zero Mouths.
- Session restart must close stale sessions without data loss.
