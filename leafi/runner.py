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
    from leafi.services import brain as brain_service
    from leafi.services import pronunciation
    from leafi.study.anki import AnkiClient
    from leafi.study.session import StudySession

    built = composition.build(settings, text_mode=bool(args.text), voice_policy=args.voice_policy,
                              tts_backend="mock" if args.mock else None,
                              config=composition.load_config(settings) if not args.mock else _mock_config())
    store = Store(settings.db_path)
    brain_name = "mock" if args.mock else settings.brain_backend
    brain = brain_service.REGISTRY.create(brain_name, settings)
    pron = None
    if settings.pron_auto_judge and not args.text:
        pron = pronunciation.REGISTRY.create("mock" if args.mock else settings.pron_backend, settings)
    session = StudySession(store=store, hub=built.hub, settings=settings, brain=brain,
                           anki_client=None if args.mock else AnkiClient(settings.anki_url), pron=pron)
    page_text = args.page_text.read_text(encoding="utf-8") if args.page_text else None
    try:
        sid = await session.run(book_title=args.book, page_text=page_text, page_number=args.page)
    except LeaseHeld as e:
        print(f"Another Leafi session holds the speech lease: {e}")
        return 2
    print(f"session {sid} saved to {settings.db_path}")
    return 0


def _mock_config():
    """`--mock`: console only, no camera, no PC speaker — safe in the home (AGENTS.md)."""
    from leafi.core.hub import DevicesConfig, DeviceSpec

    return DevicesConfig(voice_policy="none", devices=[DeviceSpec("console", "console", ["listener", "face"])],
                         study_listener="console")
