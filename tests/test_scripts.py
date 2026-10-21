"""Windows console scripts run under Windows PowerShell 5.1, which reads a BOM-less file as the ANSI code page:
a .ps1 with non-ASCII text (the Chinese console labels) must keep its UTF-8 BOM or it no longer parses
(health.ps1 lost it to a scripted rename on 2026-10-21 and the health button broke)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_powershell_scripts_with_non_ascii_text_keep_their_utf8_bom():
    bad = []
    for f in sorted((ROOT / "scripts").rglob("*.ps1")):
        data = f.read_bytes()
        if any(b > 127 for b in data) and not data.startswith(b"\xef\xbb\xbf"):
            bad.append(f.relative_to(ROOT).as_posix())
    assert bad == []
