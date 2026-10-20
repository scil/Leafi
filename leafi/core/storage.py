"""SQLite system of record `data/leafi.db` (ADR-0004). This schema is the fact; data-model.md explains it.

Migrations are ordered steps keyed by `PRAGMA user_version`. Writes that must be atomic use
`Store.transaction()` (BEGIN IMMEDIATE … COMMIT, ROLLBACK on any exception).
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

MIGRATIONS: list[str] = [
    # 1 — initial schema (data-model.md, 2026-10-19)
    """
    CREATE TABLE books(
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, isbn TEXT, language TEXT NOT NULL DEFAULT 'en',
        level TEXT, created_at TEXT NOT NULL, archived_at TEXT);
    CREATE TABLE pages(
        id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL REFERENCES books(id), printed_number INTEGER,
        observations TEXT, created_at TEXT NOT NULL);
    CREATE TABLE page_revisions(
        id INTEGER PRIMARY KEY, page_id INTEGER NOT NULL REFERENCES pages(id), rev INTEGER NOT NULL,
        text TEXT NOT NULL, source TEXT NOT NULL CHECK(source IN ('ocr','correction','manual')),
        spans_verified TEXT NOT NULL DEFAULT '[]', edit_map TEXT NOT NULL DEFAULT '[]',
        tokenizer_version TEXT NOT NULL, ocr_backend TEXT, ocr_confidence REAL, created_at TEXT NOT NULL,
        UNIQUE(page_id, rev));
    CREATE TABLE page_images(
        id INTEGER PRIMARY KEY, page_id INTEGER REFERENCES pages(id), path TEXT NOT NULL, width INTEGER,
        captured_at TEXT NOT NULL);
    CREATE TABLE corrections(
        id INTEGER PRIMARY KEY, page_revision_id INTEGER NOT NULL REFERENCES page_revisions(id),
        char_start INTEGER, char_end INTEGER, old_text TEXT NOT NULL, new_text TEXT NOT NULL,
        source TEXT NOT NULL CHECK(source IN ('voice','text','parent')), utterance_id INTEGER,
        created_at TEXT NOT NULL);
    CREATE TABLE reading_sessions(
        id INTEGER PRIMARY KEY, book_id INTEGER REFERENCES books(id), started_at TEXT NOT NULL,
        ended_at TEXT, mode TEXT NOT NULL CHECK(mode IN ('voice','text')), devices TEXT NOT NULL DEFAULT '[]',
        summary TEXT, lease_token TEXT);
    CREATE TABLE page_reads(
        id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES reading_sessions(id),
        page_id INTEGER NOT NULL REFERENCES pages(id), page_revision_id INTEGER NOT NULL
        REFERENCES page_revisions(id), attempt INTEGER NOT NULL DEFAULT 1, started_at TEXT NOT NULL,
        ended_at TEXT, reading_state TEXT, tokens_expected INTEGER NOT NULL DEFAULT 0,
        tokens_committed INTEGER NOT NULL DEFAULT 0, tokens_matched INTEGER NOT NULL DEFAULT 0,
        tokens_unread INTEGER NOT NULL DEFAULT 0, wpm REAL);
    CREATE TABLE utterances(
        id INTEGER PRIMARY KEY, page_read_id INTEGER REFERENCES page_reads(id),
        page_revision_id INTEGER REFERENCES page_revisions(id), session_id INTEGER
        REFERENCES reading_sessions(id), text TEXT NOT NULL, words TEXT NOT NULL DEFAULT '[]',
        kind TEXT NOT NULL CHECK(kind IN ('reading','control','question','correction','practice','answer')),
        created_at TEXT NOT NULL);
    CREATE TABLE observations(
        id INTEGER PRIMARY KEY, utterance_id INTEGER NOT NULL REFERENCES utterances(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK(kind IN ('matched','substituted','deleted','inserted')),
        token_start INTEGER NOT NULL, token_end INTEGER NOT NULL, heard_text TEXT, sim REAL,
        created_at TEXT NOT NULL);
    CREATE TABLE miscues(
        id INTEGER PRIMARY KEY, observation_id INTEGER REFERENCES observations(id) ON DELETE CASCADE,
        page_read_id INTEGER NOT NULL REFERENCES page_reads(id) ON DELETE CASCADE,
        page_revision_id INTEGER NOT NULL REFERENCES page_revisions(id),
        expected TEXT NOT NULL, expected_token_index INTEGER NOT NULL, expected_char_span TEXT NOT NULL,
        heard TEXT,
        status TEXT NOT NULL CHECK(status IN ('candidate','confirmed','unsure','withdrawn','invalidated')),
        withdrawn_reason TEXT CHECK(withdrawn_reason IN ('self_corrected','reread','practice')),
        unsure_reason TEXT CHECK(unsure_reason IN
            ('disagreed','skipped','idle','interrupted','not_practised')),
        evidence TEXT NOT NULL DEFAULT 'none' CHECK(evidence IN ('none','acoustic')),
        score REAL, phonemes_expected TEXT, phonemes_heard TEXT, invalidated_reason TEXT,
        updated_at TEXT NOT NULL);
    CREATE TABLE practices(
        id INTEGER PRIMARY KEY, miscue_id INTEGER NOT NULL REFERENCES miscues(id) ON DELETE CASCADE,
        attempt INTEGER NOT NULL CHECK(attempt BETWEEN 1 AND 2),
        outcome TEXT NOT NULL CHECK(outcome IN ('matched','disagreed','skipped')),
        evidence TEXT NOT NULL CHECK(evidence IN ('none','acoustic')), created_at TEXT NOT NULL);
    CREATE TABLE knowledge_items(
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL CHECK(kind IN ('word','phrase','grammar','fact','pronunciation')),
        language TEXT NOT NULL, key TEXT NOT NULL, sense_hint TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','learning','known','lapsed')),
        anki_item_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(kind, language, key, sense_hint));
    CREATE TABLE encounters(
        id INTEGER PRIMARY KEY, knowledge_item_id INTEGER NOT NULL REFERENCES knowledge_items(id),
        session_id INTEGER REFERENCES reading_sessions(id), page_revision_id INTEGER,
        context_sentence TEXT NOT NULL DEFAULT '', explanation_en TEXT, explanation_zh TEXT, example TEXT,
        trigger TEXT NOT NULL CHECK(trigger IN ('explain','check','miscue','parent')), created_at TEXT NOT NULL);
    CREATE TABLE difficulties(
        id INTEGER PRIMARY KEY, knowledge_item_id INTEGER REFERENCES knowledge_items(id), miscue_key TEXT,
        sessions_seen TEXT NOT NULL DEFAULT '[]', weight REAL NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('confirmed','watch','knowledge')), updated_at TEXT NOT NULL);
    CREATE TABLE anki_outbox(
        id INTEGER PRIMARY KEY, knowledge_item_id INTEGER NOT NULL REFERENCES knowledge_items(id),
        op TEXT NOT NULL CHECK(op IN ('add','update')),
        state TEXT NOT NULL CHECK(state IN ('pending','sent','acked','failed')),
        attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, anki_note_id INTEGER,
        card_ids TEXT NOT NULL DEFAULT '[]', last_acked_fields TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL);
    CREATE TABLE review_answers(
        id INTEGER PRIMARY KEY, knowledge_item_id INTEGER REFERENCES knowledge_items(id),
        card_id INTEGER NOT NULL, ease INTEGER NOT NULL CHECK(ease IN (1,3)),
        state TEXT NOT NULL CHECK(state IN ('pending','sent','acked','failed')), sent_at TEXT, acked_at TEXT,
        created_at TEXT NOT NULL);
    CREATE TABLE lexicon(
        word TEXT NOT NULL, language TEXT NOT NULL,
        source TEXT NOT NULL CHECK(source IN ('book','correction','manual')), book_id INTEGER,
        weight REAL NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
    CREATE UNIQUE INDEX lexicon_key ON lexicon(word, language, source, IFNULL(book_id, -1));
    CREATE TABLE learner_profile(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE INDEX miscues_read ON miscues(page_read_id);
    CREATE INDEX page_reads_session ON page_reads(session_id);
    """,
    # 2 — field hashes of the first add attempt, so a lost-ack dedupe never adopts parent edits (review 1 #4)
    """
    ALTER TABLE anki_outbox ADD COLUMN attempted_fields TEXT;
    """,
]


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")


class Store:
    """One connection per process; `with store.transaction():` for atomic multi-row writes."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._depth = 0
        self.migrate()

    # ---- schema
    def migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for i, step in enumerate(MIGRATIONS[version:], start=version + 1):
            with self.transaction():
                for stmt in _split(step):
                    self.conn.execute(stmt)
                self.conn.execute(f"PRAGMA user_version = {i}")

    @property
    def version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    # ---- transactions
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        if self._depth:  # nested: join the outer transaction
            self._depth += 1
            try:
                yield self.conn
            finally:
                self._depth -= 1
            return
        self.conn.execute("BEGIN IMMEDIATE")
        self._depth = 1
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")
        finally:
            self._depth = 0

    # ---- small helpers
    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def insert(self, table: str, **cols: Any) -> int:
        names = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        cur = self.conn.execute(f"INSERT INTO {table}({names}) VALUES({marks})", tuple(cols.values()))
        return int(cur.lastrowid)

    def one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params).fetchall())

    def close(self) -> None:
        self.conn.close()


def _split(script: str) -> list[str]:
    return [s.strip() for s in script.split(";") if s.strip()]


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def loads(text: str | None, default: Any = None) -> Any:
    if text is None:
        return default
    return json.loads(text)
