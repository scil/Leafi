"""Control grammar (plan S1): typed `/commands` always; spoken phrases only for utterances ≤ 6 words.

Brain is never used for intent. Learner free text never leaves the LAN: an explanation target is kept
only when it is a word or phrase of the page (the session checks that).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from leafi.core.text import norm, words

MAX_SPOKEN_WORDS = 6


@dataclass(frozen=True)
class Control:
    kind: str  # stop skip back page next_page explain fix again hard good easy yes no
    n: int | None = None
    text: str | None = None  # explain target / fix new text
    old: str | None = None  # fix: Leafi's (wrong) text
    path: Path | None = None  # /page N --text <file>
    typed: bool = False


_TYPED = re.compile(r"^/(\w+)\s*(.*)$", re.DOTALL)
_SPOKEN: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^(?:leafi )?stop$"), "stop"),
    (re.compile(r"^(?:leafi )?skip(?: (?:it|this|this one|that))?$"), "skip"),
    (re.compile(r"^go back$"), "back"),
    (re.compile(r"^next page$"), "next_page"),
    (re.compile(r"^(?:turn to )?page (\w+)$"), "page"),
    (re.compile(r"^i (?:don't|do not) understand$"), "explain"),
    (re.compile(r"^what does (.+) mean$"), "explain"),
    (re.compile(r"^what is (.+)$"), "explain"),
    (re.compile(r"^(?:the book says|it's|it is|it says) (.+?) not (.+)$"), "fix"),
    (re.compile(r"^again$"), "again"),
    (re.compile(r"^(?:good|got it)$"), "good"),
    (re.compile(r"^hard$"), "hard"),  # review eases 1-4: again / hard / good / easy (ADR-0017 §3.1)
    (re.compile(r"^easy$"), "easy"),
    (re.compile(r"^(?:yes|yeah|yep|sure|ok|okay)$"), "yes"),
    (re.compile(r"^(?:no|nope|no thanks)$"), "no"),
    (re.compile(r"^i (?:don't|do not) know$"), "dont_know"),
]


_NUMBER_WORDS = {norm(str(k)): k for k in range(1000)}


def _to_int(s: str) -> int | None:
    s = s.strip()
    if s.isdigit():
        return int(s)
    return _NUMBER_WORDS.get(norm(s))


def parse_typed(text: str) -> Control | None:
    m = _TYPED.match(text.strip())
    if not m:
        return None
    cmd, rest = m.group(1).lower(), m.group(2).strip()
    if cmd in ("stop", "skip", "again", "hard", "good", "easy", "yes", "no"):
        return Control(cmd, typed=True)
    if cmd == "back":
        return Control("back", n=_to_int(rest) or 1, typed=True)
    if cmd == "page":
        parts = rest.split()
        n = _to_int(parts[0]) if parts else None
        path = None
        if "--text" in parts:
            i = parts.index("--text")
            path = Path(" ".join(parts[i + 1:])) if i + 1 < len(parts) else None
        return Control("page", n=n, path=path, typed=True)
    if cmd == "next":
        return Control("next_page", typed=True)
    if cmd == "explain":
        return Control("explain", text=rest or None, typed=True)
    if cmd == "fix":  # /fix Y X : Leafi has Y, the book says X
        parts = rest.split(None, 1)
        if len(parts) == 2:
            return Control("fix", old=parts[0], text=parts[1], typed=True)
        return Control("fix", typed=True)
    return Control("unknown", text=cmd, typed=True)


def parse_spoken(text: str) -> Control | None:
    ws = words(text)
    if not ws or len(ws) > MAX_SPOKEN_WORDS:  # longer utterances are reading, never commands
        return None
    flat = " ".join(norm(w) for w in ws)
    for pat, kind in _SPOKEN:
        m = pat.match(flat)
        if not m:
            continue
        if kind == "page":
            n = _to_int(m.group(1))
            return Control("page", n=n) if n is not None else None
        if kind == "back":
            return Control("back", n=1)
        if kind == "explain":
            return Control("explain", text=m.group(1) if m.groups() else None)
        if kind == "fix":
            return Control("fix", text=m.group(1), old=m.group(2))
        return Control(kind)
    return None


def parse(text: str) -> Control | None:
    return parse_typed(text) if text.strip().startswith("/") else parse_spoken(text)
