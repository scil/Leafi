"""Pseudonymisation by lists (ADR-0018 §3, M5 design D10): every protected name is replaced before text leaves.

Lists, applied to every text class: each enrolled learner's display name and alias (one person entity,
`learner:<id>`), and every `household_terms` row — names of forgotten learners (`former:<id>`, one entity per
former learner across all their terms), other names (`term:<id>`), schools ("the school") and other terms
(`[place]`). While `REDACT_TERMS` still exists (until M5d), its terms are read too, as names.

Matching runs on NFC text, case-insensitively, longest term first. A Latin-script term matches where it is not
next to another Latin letter or a digit (so `我叫Rocco今天` matches and "Roccoli" does not); possessives and
hyphenated parts keep their suffix ("Rocco's" → "Arlo's"); a CJK term matches as a substring.

Each person entity has one stored surrogate (`pseudonyms`), allocated on first need by probing the bundled name
list from HMAC(secret, entity); a surrogate that has become a real household name is reallocated. A payload that
already contains an entity's surrogate as a word gets a one-off alternate for that request. Replies are mapped
back only for the person surrogates sent in that request, case-sensitively and as whole words; "the school",
`[place]` and `[name]` are never reversed.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from leafi.core.storage import now_iso

log = logging.getLogger("leafi.privacy.pseudonym")

SCHOOL = "the school"
PLACE = "[place]"
NAME = "[name]"

_NAMES_FILE = Path(__file__).with_name("surrogate_names.txt")
_LATIN = "A-Za-zÀ-ɏḀ-ỿ"
_EDGE = rf"[{_LATIN}0-9]"
_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]")


def surrogate_pool() -> list[str]:
    return [ln.strip() for ln in _NAMES_FILE.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")]


def norm(text: str) -> str:
    return unicodedata.normalize("NFC", text)


@dataclass(frozen=True)
class Entry:
    term: str
    kind: str  # "person" | "school" | "other"
    entity: str | None  # person entities only


@dataclass
class Lists:
    entries: list[Entry]

    def pattern(self) -> re.Pattern | None:
        if not self.entries:
            return None
        parts = []
        for e in sorted(self.entries, key=lambda e: -len(e.term)):
            body = r"\s+".join(re.escape(w) for w in norm(e.term).split())
            if _CJK.search(e.term):
                parts.append(f"(?:{body})")
            else:
                parts.append(f"(?<!{_EDGE})(?:{body})(?!{_EDGE})")
        return re.compile("|".join(parts), re.IGNORECASE)

    def lookup(self, matched: str) -> Entry:
        key = " ".join(norm(matched).split()).casefold()
        for e in sorted(self.entries, key=lambda e: -len(e.term)):
            if " ".join(norm(e.term).split()).casefold() == key:
                return e
        raise KeyError(matched)


def load_lists(conn: sqlite3.Connection, legacy_terms: list[str] | tuple[str, ...] = ()) -> Lists:
    entries: list[Entry] = []
    seen: set[str] = set()

    def add(term: str | None, kind: str, entity: str | None) -> None:
        if not term or not term.strip():
            return
        key = " ".join(norm(term).split()).casefold()
        if key in seen:
            return
        seen.add(key)
        entries.append(Entry(term.strip(), kind, entity))

    for lid, name, alias in conn.execute("SELECT id, display_name, alias FROM learners WHERE kind = 'learner'"):
        add(name, "person", f"learner:{lid}")
        add(alias, "person", f"learner:{lid}")
    for tid, term, kind, former in conn.execute("SELECT id, term, kind, former_learner_id FROM household_terms"):
        if kind == "school":
            add(term, "school", None)
        elif kind == "other":
            add(term, "other", None)
        else:
            add(term, "person", f"former:{former}" if former is not None else f"term:{tid}")
    for term in legacy_terms:  # REDACT_TERMS until M5d removes it (design D12)
        add(term, "person", f"legacy:{term.strip().casefold()}")
    return Lists(entries)


def _probe(secret: bytes, entity: str, pool: list[str], taken: set[str]) -> str | None:
    start = int.from_bytes(hmac.new(secret, f"surrogate:{entity}".encode(), hashlib.sha256).digest()[:8], "big")
    for i in range(len(pool)):
        name = pool[(start + i) % len(pool)]
        if name.casefold() not in taken:
            return name
    return None


def surrogates(conn: sqlite3.Connection, secret: bytes, lists: Lists) -> dict[str, str]:
    """entity → stored surrogate, allocating (in one write transaction) any missing ones and reallocating any that
    equal a protected term now. Entities the pool cannot serve map to `[name]`."""
    protected = {" ".join(norm(e.term).split()).casefold() for e in lists.entries}
    entities = sorted({e.entity for e in lists.entries if e.entity})
    pool = surrogate_pool()
    conn.execute("BEGIN IMMEDIATE")
    try:
        stored = {r[0]: r[1] for r in conn.execute("SELECT entity, surrogate FROM pseudonyms")}
        for ent, sur in list(stored.items()):
            if sur.casefold() in protected:
                conn.execute("DELETE FROM pseudonyms WHERE entity = ?", (ent,))
                del stored[ent]
                log.warning("surrogate of %s is now a household name; reallocated", ent)
        taken = protected | {s.casefold() for s in stored.values()}
        for ent in entities:
            if ent in stored or ent.startswith("legacy:"):
                continue
            name = _probe(secret, ent, pool, taken)
            if name is None:
                continue
            conn.execute("INSERT INTO pseudonyms(entity, surrogate, created_at) VALUES(?, ?, ?)",
                         (ent, name, now_iso()))
            stored[ent] = name
            taken.add(name.casefold())
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return {ent: stored.get(ent, NAME) for ent in entities if not ent.startswith("legacy:")}


@dataclass
class Mapping:
    """What one request sent: surrogate → the real name it stands for (person surrogates only)."""

    back: dict[str, str] = field(default_factory=dict)
    chosen: dict[str, str] = field(default_factory=dict)  # entity → the surrogate this request uses

    def reverse(self, text: str) -> str:
        if not self.back:
            return text
        pat = re.compile("|".join(f"(?<!{_EDGE}){re.escape(s)}(?!{_EDGE})"
                                  for s in sorted(self.back, key=len, reverse=True)))
        return pat.sub(lambda m: self.back[m.group(0)], text)


@dataclass
class Pseudonymizer:
    lists: Lists
    names: dict[str, str]  # entity → surrogate
    display: dict[str, str]  # entity → the name a reply is mapped back to
    pool: list[str] = field(default_factory=surrogate_pool)
    _pattern: re.Pattern | None = None

    def __post_init__(self) -> None:
        self._pattern = self.lists.pattern()

    def apply(self, text: str, mapping: Mapping, *, payload_words: set[str] | None = None) -> str:
        """Replace every listed term in `text`; record the person surrogates used in `mapping`. `payload_words`
        (casefolded words of the whole request) makes a surrogate already present in the payload a one-off
        alternate."""
        text = norm(text)
        if self._pattern is None:
            return text
        words = payload_words if payload_words is not None else {w.casefold() for w in re.findall(r"\w+", text)}

        def sub(m: re.Match) -> str:
            e = self.lists.lookup(m.group(0))
            if e.kind == "school":
                return SCHOOL
            if e.kind == "other":
                return PLACE
            ent = e.entity or ""
            sur = mapping.chosen.get(ent)
            if sur is None:
                sur = self.names.get(ent, NAME)
                if sur != NAME and sur.casefold() in words:
                    sur = self._alternate(words, mapping)
                mapping.chosen[ent] = sur
            if sur != NAME:
                mapping.back[sur] = self.display.get(ent, e.term)
            return sur

        return self._pattern.sub(sub, text)

    def _alternate(self, words: set[str], mapping: Mapping) -> str:
        used = {s.casefold() for s in self.names.values()} | {s.casefold() for s in mapping.back}
        protected = {" ".join(norm(e.term).split()).casefold() for e in self.lists.entries}
        for name in self.pool:
            k = name.casefold()
            if k not in used and k not in words and k not in protected:
                return name
        return NAME


def build(conn: sqlite3.Connection, secret: bytes, legacy_terms: list[str] | tuple[str, ...] = ()) -> Pseudonymizer:
    """Allocate what is missing, then read: for callers outside a read snapshot (tests, tools)."""
    surrogates(conn, secret, load_lists(conn, legacy_terms))
    return build_read(conn, secret, legacy_terms)


def build_read(conn: sqlite3.Connection, secret: bytes,
               legacy_terms: list[str] | tuple[str, ...] = ()) -> Pseudonymizer:
    """Read-only, for egress's snapshot: the lists and the stored surrogates as they are now. An entity that has
    none yet (it appeared after the allocation step) is replaced by `[name]`, never sent."""
    lists = load_lists(conn, legacy_terms)
    stored = {r[0]: r[1] for r in conn.execute("SELECT entity, surrogate FROM pseudonyms")}
    protected = {" ".join(norm(e.term).split()).casefold() for e in lists.entries}
    pool, taken = surrogate_pool(), protected | {s.casefold() for s in stored.values()}
    names: dict[str, str] = {}
    for ent in sorted({e.entity for e in lists.entries if e.entity}):
        if ent.startswith("legacy:"):
            name = _probe(secret, ent, pool, taken)
            names[ent] = name or NAME
            if name:
                taken.add(name.casefold())
        else:
            sur = stored.get(ent)
            names[ent] = sur if sur is not None and sur.casefold() not in protected else NAME
    display: dict[str, str] = {}
    for lid, name in conn.execute("SELECT id, display_name FROM learners WHERE kind = 'learner'"):
        display[f"learner:{lid}"] = name
    for e in lists.entries:
        if e.entity and e.entity not in display:
            display[e.entity] = e.term
    return Pseudonymizer(lists, names, display)
