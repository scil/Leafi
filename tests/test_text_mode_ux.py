"""Owner's first text-mode run (2026-10-20): Leafi said "read it aloud" although text mode only takes typed
lines, showed no prompt, and Ctrl-C printed a traceback. These tests pin the three fixes."""

from __future__ import annotations

import io
from pathlib import Path

from leafi.core.ports import Display
from leafi.devices.console import ConsoleDevice

PAGE = Path("tests/fixtures/pages/p1.txt").read_text(encoding="utf-8")


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
