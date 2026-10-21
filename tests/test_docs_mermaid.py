"""Mermaid diagrams in docs/ must render in Obsidian and on GitHub. Three mistakes broke them on 2026-10-21
(found by rendering every block with Mermaid 11.4.1): a `;` inside a sequence message (a statement separator),
a second `:` in a state transition label, and `\\n` used as a line break (shown literally; use `<br/>`)."""

from __future__ import annotations

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"
BLOCK = re.compile(r"```mermaid\n(.*?)```", re.S)


def _blocks():
    for f in sorted(DOCS.rglob("*.md")):
        if "archive" in f.parts:
            continue
        for m in BLOCK.finditer(f.read_text(encoding="utf-8")):
            yield f.relative_to(DOCS).as_posix(), m.group(1)


def test_mermaid_blocks_avoid_the_constructs_that_break_rendering():
    bad = []
    for name, src in _blocks():
        lines = src.splitlines()
        kind = lines[0].strip() if lines else ""
        for n, line in enumerate(lines[1:], start=2):
            if "\\n" in line:
                bad.append(f"{name} line {n}: literal \\n (use <br/>)")
            if kind == "sequenceDiagram" and ";" in line:
                bad.append(f"{name} line {n}: ';' ends a sequence statement")
            if kind.startswith("stateDiagram") and "-->" in line and line.count(":") > 1:
                bad.append(f"{name} line {n}: a second ':' in a transition label")
    assert bad == []
