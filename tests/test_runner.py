"""`leafi study` composition in `leafi.runner`."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

from leafi import runner
from leafi.core.hub import Hub
from tests.fakes import RecordingFace

PAGE = Path("tests/fixtures/pages/p1.txt")


class _Eye:
    async def snapshot(self, max_width=None):
        return None


@pytest.fixture
def captured(monkeypatch, settings):
    """The `Env` `run_study` builds the harness session from; the session itself does not run."""
    from leafi import app
    from leafi.study.harness import loop

    got: dict = {}

    async def recorder(env):
        got.update(vars(env))
        return 1

    hub = Hub(faces={"f": RecordingFace()}, eyes={"desk": _Eye()}, policy="none", study_eye="desk")
    monkeypatch.setattr(app, "build", lambda *a, **k: SimpleNamespace(hub=hub))
    monkeypatch.setattr(loop, "run_session", recorder)
    settings.ocr_backend = "mock"
    settings.book_lookup = "off"
    return got


def _args(**kw) -> argparse.Namespace:
    base = dict(text=False, mock=True, voice_policy=None, mouth=None, book="Fixture", page_text=None, page=None,
                learner="Ada")
    return argparse.Namespace(**{**base, **kw})


async def test_page_text_session_does_not_watch_the_camera_for_page_turns(captured, settings):
    """Owner's voice runs (2026-10-21): with the page given by --page-text, the camera coming back online read
    as page turns and moved the reading to an OCR'd "page 3". Page turns then come only from "next page"."""
    assert await runner.run_study(settings, _args(page_text=PAGE, page=1)) == 0
    assert captured["page_tracker"] is None


async def test_camera_session_still_watches_for_page_turns(captured, settings):
    assert await runner.run_study(settings, _args()) == 0
    assert captured["page_tracker"] is not None
