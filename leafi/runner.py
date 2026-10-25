"""`python -m leafi study`: builds the session from settings through the composition root (`leafi.app`)."""

from __future__ import annotations

import argparse
import logging

from leafi.core.config import Settings
from leafi.core.lease import LeaseHeld
from leafi.core.storage import Store

log = logging.getLogger("leafi.runner")


async def run_study(settings: Settings, args: argparse.Namespace) -> int:
    from leafi import app as composition

    config = composition.load_config(settings) if not args.mock else _mock_config()
    if getattr(args, "panel", False) and not any(d.adapter == "panel" for d in config.devices):
        from leafi.core.hub import DeviceSpec

        config.devices.append(DeviceSpec("panel", "panel", ["listener", "face"]))  # session panel design D1
    built = composition.build(settings, text_mode=bool(args.text), voice_policy=args.voice_policy,
                              tts_backend="mock" if args.mock else None, config=config)
    if getattr(args, "mouth", None):
        # `--mouth pc`: speak only through the named devices (a voice session at the desk without the camera
        # speaker; AGENTS.md forbids camera audio unless the owner asks for it).
        keep = set(args.mouth)
        unknown = keep - set(built.hub.mouths)
        if unknown:
            log.warning("--mouth: no such Mouth %s (have %s)", sorted(unknown), sorted(built.hub.mouths))
        built.hub.mouths = {n: m for n, m in built.hub.mouths.items() if n in keep}
    from leafi.study.harness.busy import STUDY_BUSY_TIMEOUT_MS

    store = Store(settings.db_path, busy_timeout_ms=STUDY_BUSY_TIMEOUT_MS)  # ADR-0017 §7.3
    try:
        return await _run(settings, args, built, store)
    finally:
        try:
            store.checkpoint()  # session end: fold the -wal into the file (ADR-0019 §6)
        except Exception:  # noqa: BLE001 - never mask the session's own outcome
            log.warning("checkpoint at session end failed", exc_info=True)
        store.close()


async def _run(settings: Settings, args: argparse.Namespace, built, store: Store) -> int:
    from leafi.services import pronunciation
    from leafi.study.anki import AnkiClient
    from leafi.study.harness import loop

    pron = None
    if settings.pron_auto_judge and not args.text:
        pron = pronunciation.REGISTRY.create("mock" if args.mock else settings.pron_backend, settings)
    ocr = tracker = catalog = None
    eye = built.hub.eye()
    # `--page-text` gives the page by hand: the camera is not watched for page turns ("next page" turns it),
    # since a camera coming back online read as turns and moved the reading to an OCR'd page (2026-10-21).
    if eye is not None and not args.text and not args.page_text:
        from leafi.services import catalog as catalog_service
        from leafi.services import ocr as ocr_service
        from leafi.study.page_tracker import PageTracker

        state, detail = ocr_service.REGISTRY.status(settings.ocr_backend, settings)
        if state == "ok":
            ocr = ocr_service.REGISTRY.create(settings.ocr_backend, settings)
            tracker = PageTracker(store, eye, ocr, settings)
        else:
            log.warning("page camera off: ocr %s %s %s", settings.ocr_backend, state, detail)
        if settings.book_lookup != "off":
            catalog = catalog_service.REGISTRY.create(settings.book_lookup, settings)
    from leafi import app as composition
    from leafi.core import learner_store
    from leafi.privacy import runtime
    from leafi.services.wordinfo import LocalWordInfo

    runtime.get(settings).start_detector()  # loads in a thread while the session starts (M7 design D8)
    lexicon = [r["word"] for r in store.all("SELECT DISTINCT word FROM lexicon")]
    page_text = args.page_text.read_text(encoding="utf-8") if args.page_text else None
    # `--mock` never calls a model; otherwise the Brain sequences sessions when a tier is usable (M7b).
    brain = None if args.mock else composition.build_brain(settings, runtime.get(settings))
    log.info("study brain: %s", sorted(brain.configured()) if brain else "off (default policy)")
    env = loop.Env(store=store, hub=built.hub, settings=settings, page_tracker=tracker, ocr=ocr, catalog=catalog,
                   brain=brain,
                   anki=None if args.mock else AnkiClient(settings.anki_url), pron=pron,
                   word_info=LocalWordInfo(settings.models_dir, lexicon), book_title=args.book, page_text=page_text,
                   page_number=args.page, learner=getattr(args, "learner", None))
    panel = _attach_panel(env, built, store) if getattr(args, "panel", False) else None
    try:
        sid = await loop.run_session(env)
    except LeaseHeld as e:
        print(f"Another Leafi session holds the speech lease: {e}")
        return 2
    except learner_store.LearnerChoice as e:
        print(f"Leafi: {e}")
        return 2
    finally:
        if panel is not None:
            await panel.close()  # idempotent; a panel refused the lease never started (design D1)
        if hasattr(ocr, "aclose"):
            await ocr.aclose()  # a read still running in the executor finishes before the loop ends (design O5)
    print(f"session {sid} saved to {settings.db_path}")
    return 0


def _attach_panel(env, built, store):
    """`study --panel` (session panel design D1, D2): the device starts in `on_built`, which `run_session` calls once
    the speech lease is held, and is told of every change; the console goes quiet at end of input without a
    terminal, so a session driven from the panel is not stopped by an empty stdin."""
    import sys

    from leafi.study.harness.snapshot import snapshot

    panel = built.devices.get("panel")
    if panel is None:
        log.warning("--panel: no panel device was built")
        return None
    if not sys.stdin.isatty():
        for lis in built.hub.listeners.values():
            if getattr(lis, "name", None) == "console" and hasattr(lis, "options"):
                lis.options["eof_stops"] = False

    def on_built(s, w) -> None:
        panel.start(lambda: snapshot(s, w), session_id=s.session_id, store=store)
        s.hooks.append(panel.mark_dirty)
        w.inputs.on_change = panel.mark_dirty

    env.on_built = on_built
    return panel


def _mock_config():
    """`--mock`: console only, no camera, no PC speaker — safe in the home (AGENTS.md)."""
    from leafi.core.hub import DevicesConfig, DeviceSpec

    return DevicesConfig(voice_policy="none", devices=[DeviceSpec("console", "console", ["listener", "face"])],
                         study_listener="console")
