"""Owner's first text-mode run (2026-10-20): Leafi said "read it aloud" although text mode only takes typed
lines, showed no prompt, and Ctrl-C printed a traceback. These tests pin the three fixes."""

from __future__ import annotations

import io
from pathlib import Path

from leafi.core.hub import Hub
from leafi.core.ports import Display
from leafi.core.storage import Store
from leafi.devices.console import ConsoleDevice
from leafi.services.brain.mock import MockBrain
from leafi.study.session import StudySession
from tests.fakes import RecordingFace, ScriptedListener

PAGE = Path("tests/fixtures/pages/p1.txt").read_text(encoding="utf-8")


async def test_text_mode_page_ready_tells_the_learner_to_type(settings):
    store = Store(settings.db_path)
    face = RecordingFace()
    hub = Hub(faces={"console": face}, policy="none")
    session = StudySession(store=store, hub=hub, settings=settings, brain=MockBrain(),
                           listener=ScriptedListener(["/stop"]))
    await session.run(book_title="Fixture", page_text=PAGE, page_number=1)
    ready = [t for t in face.texts if t.startswith("Page 1 is ready")]
    assert ready and "Type each sentence" in ready[0] and "aloud" not in ready[0]


async def test_voice_mode_page_ready_still_says_read_aloud(settings):
    store = Store(settings.db_path)
    face = RecordingFace()
    hub = Hub(faces={"console": face}, policy="none")
    session = StudySession(store=store, hub=hub, settings=settings, brain=MockBrain(),
                           listener=ScriptedListener(["/stop"], voice=True))
    await session.run(book_title="Fixture", page_text=PAGE, page_number=1)
    # `phrases.say` rotates the two voice variants; either is fine, the typed-mode hint is not
    assert any(t.startswith(("Page 1 is ready", "Got page 1")) for t in face.texts)
    assert not any("Type each sentence" in t for t in face.texts)


async def test_page_ready_is_said_after_the_review_cards_not_before(settings):
    """Owner's first voice run (2026-10-21): "Read it aloud whenever you like" came before REVIEW_DUE, so the
    learner began reading while the session still waited on Anki and the first sentence was never heard."""
    from leafi.study import anki
    from tests.fakes.anki import FakeAnki

    store = Store(settings.db_path)
    fake = FakeAnki()
    fake.add_due_card("blew")
    face = RecordingFace()
    hub = Hub(faces={"console": face}, policy="none")
    session = StudySession(store=store, hub=hub, settings=settings, brain=MockBrain(),
                           listener=ScriptedListener(["good", "/stop"], voice=True),
                           anki_client=anki.AnkiClient(transport=fake.transport()))
    await session.run(book_title="Fixture", page_text=PAGE, page_number=1)
    review = next(i for i, t in enumerate(face.texts) if t.startswith("Remember this one?"))
    ready = next(i for i, t in enumerate(face.texts) if t.startswith(("Page 1 is ready", "Got page 1")))
    assert ready > review
    assert sum(t.startswith(("Page 1 is ready", "Got page 1")) for t in face.texts) == 1


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


async def test_console_shows_a_prompt_when_listening_on_a_terminal():
    out = io.StringIO()
    console = ConsoleDevice(stdin=_Tty(""), stdout=out)
    await console.show(Display("listening", "listening"))
    assert out.getvalue() == "> "
    piped = io.StringIO()
    console = ConsoleDevice(stdin=io.StringIO(""), stdout=piped)
    await console.show(Display("listening", "listening"))
    assert piped.getvalue() == ""


def test_ctrl_c_exits_cleanly_without_a_traceback(monkeypatch, capsys):
    from leafi import cli, runner

    async def boom(settings, args):
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "run_study", boom)
    rc = cli.main(["study", "--text", "--mock", "--book", "X"])
    assert rc == 130
    assert "stopped" in capsys.readouterr().out
