"""SQLite system of record `data/leafi.db` (ADR-0004). This schema is the fact; data-model.md explains it.

`SCHEMA` is the latest schema (version `SCHEMA_VERSION`). Opening has three states (ADR-0018 §7.2): an empty file
is created at `SCHEMA` in one transaction; a file at the latest version opens; a file that holds data below it
refuses and names `python -m leafi migrate`. Every opener holds a shared OS lock on `<db>.users` while it is open;
`migrate_file` takes it exclusively, so a migration never runs beside another Leafi process. Writes that must be
atomic use `Store.transaction()` (BEGIN IMMEDIATE … COMMIT, ROLLBACK on any exception). The file runs in WAL only
under a SQLite library free of the WAL-reset bug (ADR-0019).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import sqlite3
import weakref
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

import portalocker

log = logging.getLogger("leafi.storage")

JOURNAL_SIZE_LIMIT = 32 * 1024 * 1024  # a -wal file past this is truncated after a checkpoint (ADR-0019 §4)

# Steps 1–4, run only by `migrate_file` on files older than version 4; a new file is created at SCHEMA directly.
LEGACY_STEPS: list[str] = [
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
    # 3 — operational alerts and the watchdog's restart budget (ADR-0016)
    """
    CREATE TABLE alert_outbox(
        id INTEGER PRIMARY KEY, key TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('down','up','event')),
        reason TEXT NOT NULL, created_at TEXT NOT NULL, toasted INTEGER NOT NULL DEFAULT 0, sent_at TEXT,
        attempts INTEGER NOT NULL DEFAULT 0, next_try_at REAL NOT NULL DEFAULT 0);
    CREATE TABLE watchdog_state(
        id INTEGER PRIMARY KEY CHECK(id = 1), kills INTEGER NOT NULL DEFAULT 0, gave_up INTEGER NOT NULL DEFAULT 0,
        latch TEXT NOT NULL DEFAULT 'up' CHECK(latch IN ('up','down')), updated_at TEXT NOT NULL);
    """,
    # 4 — one budget per supervised service (ADR-0016 amendment: one supervisor for every service)
    """
    CREATE TABLE service_state(
        service TEXT PRIMARY KEY, kills INTEGER NOT NULL DEFAULT 0, gave_up INTEGER NOT NULL DEFAULT 0,
        latch TEXT NOT NULL DEFAULT 'up' CHECK(latch IN ('up','down')), updated_at TEXT NOT NULL);
    INSERT INTO service_state(service, kills, gave_up, latch, updated_at)
        SELECT 'camera', kills, gave_up, latch, updated_at FROM watchdog_state;
    DROP TABLE watchdog_state;
    """,
]

SCHEMA_VERSION = 5

# Provenance of a stored text (ADR-0018 §3): a class and the json list of source learner ids, both NOT NULL with
# no default, so every writer states them.
_PROV = "IN ('page','system','learner','derived_from_learner','parent')"

# 5 — learners, the session records of ADR-0017 §7.2, egress and consent (ADR-0018), the ADR-0013 v2 columns.
SCHEMA = f"""
    CREATE TABLE learners(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL CHECK(kind IN ('learner','guest','anonymous')), display_name TEXT NOT NULL,
        birth_year INTEGER, school_year INTEGER, alias TEXT, alias_age_band TEXT,
        settings TEXT NOT NULL DEFAULT '{{}}', settings_version INTEGER NOT NULL DEFAULT 1,
        recognition TEXT NOT NULL DEFAULT '{{}}',
        guest_reason TEXT CHECK(guest_reason IN ('declined','unconfirmed')), guest_expires_at TEXT,
        forgetting INTEGER NOT NULL DEFAULT 0 CHECK(forgetting IN (0,1)), created_at TEXT NOT NULL);
    CREATE TABLE household_terms(
        id INTEGER PRIMARY KEY, term TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('name','school','other')),
        former_learner_id INTEGER, created_at TEXT NOT NULL);
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
        source_learner_id INTEGER REFERENCES learners(id),
        forgotten INTEGER NOT NULL DEFAULT 0 CHECK(forgotten IN (0,1)), created_at TEXT NOT NULL,
        CHECK(source = 'parent' OR forgotten OR source_learner_id IS NOT NULL));
    CREATE TABLE reading_sessions(
        id INTEGER PRIMARY KEY, learner_id INTEGER NOT NULL REFERENCES learners(id),
        book_id INTEGER REFERENCES books(id), started_at TEXT NOT NULL,
        ended_at TEXT, mode TEXT NOT NULL CHECK(mode IN ('voice','text')), devices TEXT NOT NULL DEFAULT '[]',
        summary TEXT, lease_token TEXT);
    CREATE TABLE cycles(
        id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES reading_sessions(id),
        status TEXT NOT NULL CHECK(status IN ('open','closed')), opened_by_activity INTEGER, closed_reason TEXT,
        opened_at TEXT NOT NULL, closed_at TEXT);
    CREATE TABLE activities(
        id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES reading_sessions(id),
        cycle_id INTEGER REFERENCES cycles(id), kind TEXT NOT NULL, continuation INTEGER NOT NULL DEFAULT 0,
        params TEXT NOT NULL DEFAULT '{{}}', arm TEXT, propensity REAL, policy_version TEXT,
        decided_by TEXT CHECK(decided_by IN ('brain','default','learner')),
        override TEXT CHECK(override IN ('brain_unavailable','learner_choice','refused','wait')),
        autonomy INTEGER, epoch INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, started_at TEXT NOT NULL,
        ended_at TEXT, outcome TEXT,
        outcome_provenance_class TEXT NOT NULL CHECK(outcome_provenance_class {_PROV}),
        outcome_source_learners TEXT NOT NULL, assessment TEXT,
        assessment_provenance_class TEXT NOT NULL CHECK(assessment_provenance_class {_PROV}),
        assessment_source_learners TEXT NOT NULL);
    CREATE TABLE brain_calls(
        id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES reading_sessions(id),
        activity_id INTEGER REFERENCES activities(id), purpose TEXT NOT NULL, difficulty TEXT, tier TEXT,
        backend TEXT NOT NULL, endpoint_host TEXT, model TEXT, effective_provider TEXT, effective_model TEXT,
        prompt_version TEXT, payload TEXT NOT NULL,
        payload_provenance_class TEXT NOT NULL CHECK(payload_provenance_class {_PROV}),
        payload_source_learners TEXT NOT NULL, response TEXT,
        response_provenance_class TEXT NOT NULL CHECK(response_provenance_class {_PROV}),
        response_source_learners TEXT NOT NULL, latency_ms INTEGER,
        transmitted_attempts INTEGER NOT NULL DEFAULT 0, tokens_in INTEGER, tokens_out INTEGER,
        tokens_cached INTEGER, estimated_cost REAL, outcome TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE page_reads(
        id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES reading_sessions(id),
        cycle_id INTEGER REFERENCES cycles(id),
        page_id INTEGER NOT NULL REFERENCES pages(id), page_revision_id INTEGER NOT NULL
        REFERENCES page_revisions(id), attempt INTEGER NOT NULL DEFAULT 1, started_at TEXT NOT NULL,
        ended_at TEXT, reading_state TEXT, tokens_expected INTEGER NOT NULL DEFAULT 0,
        tokens_committed INTEGER NOT NULL DEFAULT 0, tokens_matched INTEGER NOT NULL DEFAULT 0,
        tokens_unread INTEGER NOT NULL DEFAULT 0, wpm REAL, alignment_versions TEXT NOT NULL DEFAULT '{{}}',
        self_corrections INTEGER NOT NULL DEFAULT 0, repetitions INTEGER NOT NULL DEFAULT 0,
        unaligned_words INTEGER NOT NULL DEFAULT 0, function_word_misses INTEGER NOT NULL DEFAULT 0,
        not_reached INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE utterances(
        id INTEGER PRIMARY KEY, page_read_id INTEGER REFERENCES page_reads(id),
        page_revision_id INTEGER REFERENCES page_revisions(id), session_id INTEGER NOT NULL
        REFERENCES reading_sessions(id), text TEXT NOT NULL, words TEXT NOT NULL DEFAULT '[]',
        kind TEXT NOT NULL CHECK(kind IN ('reading','control','question','correction','practice','answer')),
        provenance_class TEXT NOT NULL CHECK(provenance_class {_PROV}), source_learners TEXT NOT NULL,
        created_at TEXT NOT NULL);
    CREATE TABLE observations(
        id INTEGER PRIMARY KEY, utterance_id INTEGER NOT NULL REFERENCES utterances(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK(kind IN ('matched','substituted','deleted','inserted','unaligned')),
        token_start INTEGER, token_end INTEGER, heard_text TEXT, sim REAL,
        pair_class TEXT CHECK(pair_class IN ('exact','phones','fuzzy','join','inflection','substitute')),
        function_word INTEGER NOT NULL DEFAULT 0 CHECK(function_word IN (0,1)),
        repeat INTEGER NOT NULL DEFAULT 0 CHECK(repeat IN (0,1)),
        self_correction INTEGER NOT NULL DEFAULT 0 CHECK(self_correction IN (0,1)), word_count INTEGER,
        created_at TEXT NOT NULL,
        CHECK((kind = 'unaligned') = (token_start IS NULL) AND (kind = 'unaligned') = (token_end IS NULL)));
    CREATE TABLE miscues(
        id INTEGER PRIMARY KEY, observation_id INTEGER REFERENCES observations(id) ON DELETE CASCADE,
        page_read_id INTEGER NOT NULL REFERENCES page_reads(id) ON DELETE CASCADE,
        page_revision_id INTEGER NOT NULL REFERENCES page_revisions(id), cycle_id INTEGER REFERENCES cycles(id),
        expected TEXT NOT NULL, expected_token_index INTEGER NOT NULL, expected_char_span TEXT NOT NULL,
        heard TEXT, origin TEXT NOT NULL CHECK(origin IN ('substitution','deletion','supplied')),
        status TEXT NOT NULL CHECK(status IN ('candidate','confirmed','unsure','withdrawn','invalidated')),
        withdrawn_reason TEXT CHECK(withdrawn_reason IN ('self_corrected','reread','practice')),
        unsure_reason TEXT CHECK(unsure_reason IN
            ('disagreed','skipped','idle','interrupted','not_practised','unclear')),
        evidence TEXT NOT NULL DEFAULT 'none' CHECK(evidence IN ('none','acoustic')),
        score REAL, phonemes_expected TEXT, phonemes_heard TEXT, invalidated_reason TEXT,
        updated_at TEXT NOT NULL);
    CREATE TABLE practices(
        id INTEGER PRIMARY KEY, miscue_id INTEGER NOT NULL REFERENCES miscues(id) ON DELETE CASCADE,
        attempt INTEGER NOT NULL CHECK(attempt BETWEEN 1 AND 2),
        outcome TEXT NOT NULL CHECK(outcome IN ('matched','disagreed','skipped','unclear','idle')),
        evidence TEXT NOT NULL CHECK(evidence IN ('none','acoustic')), created_at TEXT NOT NULL);
    CREATE TABLE knowledge_items(
        id INTEGER PRIMARY KEY, learner_id INTEGER NOT NULL REFERENCES learners(id),
        kind TEXT NOT NULL CHECK(kind IN ('word','phrase','grammar','fact','pronunciation','pattern')),
        language TEXT NOT NULL, key TEXT NOT NULL, sense_hint TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','learning','known','lapsed','ignored')),
        anki_item_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(learner_id, kind, language, key, sense_hint));
    CREATE TABLE encounters(
        id INTEGER PRIMARY KEY, learner_id INTEGER NOT NULL REFERENCES learners(id),
        knowledge_item_id INTEGER NOT NULL REFERENCES knowledge_items(id),
        session_id INTEGER REFERENCES reading_sessions(id), page_revision_id INTEGER,
        context_sentence TEXT NOT NULL DEFAULT '',
        context_provenance_class TEXT NOT NULL CHECK(context_provenance_class {_PROV}),
        context_source_learners TEXT NOT NULL, explanation_en TEXT, explanation_zh TEXT, example TEXT,
        explanation_provenance_class TEXT NOT NULL CHECK(explanation_provenance_class {_PROV}),
        explanation_source_learners TEXT NOT NULL,
        trigger TEXT NOT NULL CHECK(trigger IN ('explain','check','miscue','parent','teach_ok','teach_incorrect')),
        created_at TEXT NOT NULL);
    CREATE TABLE difficulties(
        id INTEGER PRIMARY KEY, learner_id INTEGER NOT NULL REFERENCES learners(id),
        knowledge_item_id INTEGER REFERENCES knowledge_items(id), miscue_key TEXT,
        sessions_seen TEXT NOT NULL DEFAULT '[]', weight REAL NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('confirmed','watch','knowledge')), updated_at TEXT NOT NULL);
    CREATE TABLE retrieval_events(
        id INTEGER PRIMARY KEY, learner_id INTEGER NOT NULL REFERENCES learners(id),
        item_id INTEGER NOT NULL REFERENCES knowledge_items(id), activity_id INTEGER REFERENCES activities(id),
        at TEXT NOT NULL, day TEXT NOT NULL, outcome TEXT NOT NULL CHECK(outcome IN ('success','fail')),
        evidence TEXT NOT NULL CHECK(evidence IN ('typed','heard_confident','acoustic')));
    CREATE TABLE learner_notes(
        id INTEGER PRIMARY KEY, learner_id INTEGER NOT NULL REFERENCES learners(id),
        session_id INTEGER REFERENCES reading_sessions(id), text TEXT NOT NULL,
        provenance_class TEXT NOT NULL CHECK(provenance_class {_PROV}), source_learners TEXT NOT NULL,
        created_at TEXT NOT NULL);
    CREATE TABLE learner_note_citations(
        note_id INTEGER NOT NULL REFERENCES learner_notes(id) ON DELETE CASCADE,
        activity_id INTEGER NOT NULL REFERENCES activities(id), PRIMARY KEY(note_id, activity_id));
    CREATE TABLE book_notes(
        id INTEGER PRIMARY KEY, learner_id INTEGER NOT NULL REFERENCES learners(id),
        book_id INTEGER NOT NULL REFERENCES books(id), session_id INTEGER REFERENCES reading_sessions(id),
        topic TEXT, characters TEXT, text TEXT NOT NULL,
        provenance_class TEXT NOT NULL CHECK(provenance_class {_PROV}), source_learners TEXT NOT NULL,
        created_at TEXT NOT NULL);
    CREATE TABLE anki_outbox(
        id INTEGER PRIMARY KEY, learner_id INTEGER NOT NULL REFERENCES learners(id),
        knowledge_item_id INTEGER NOT NULL REFERENCES knowledge_items(id),
        op TEXT NOT NULL CHECK(op IN ('add','update')),
        state TEXT NOT NULL CHECK(state IN ('pending','sent','acked','failed')),
        attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, anki_note_id INTEGER,
        card_ids TEXT NOT NULL DEFAULT '[]', last_acked_fields TEXT NOT NULL DEFAULT '{{}}',
        updated_at TEXT NOT NULL, attempted_fields TEXT, front TEXT, back TEXT, sentence TEXT,
        card_provenance_class TEXT NOT NULL CHECK(card_provenance_class {_PROV}),
        card_source_learners TEXT NOT NULL);
    CREATE TABLE review_answers(
        id INTEGER PRIMARY KEY, learner_id INTEGER NOT NULL REFERENCES learners(id),
        knowledge_item_id INTEGER REFERENCES knowledge_items(id),
        card_id INTEGER NOT NULL, ease INTEGER NOT NULL CHECK(ease IN (1,2,3,4)),
        state TEXT NOT NULL CHECK(state IN ('pending','sent','acked','failed')), sent_at TEXT, acked_at TEXT,
        created_at TEXT NOT NULL);
    CREATE TABLE consents(
        id INTEGER PRIMARY KEY, learner_id INTEGER NOT NULL REFERENCES learners(id),
        purpose TEXT NOT NULL CHECK(purpose IN ('remote_teacher','cloud_text','biometric_voice','biometric_face')),
        recipient TEXT, item TEXT,
        status TEXT NOT NULL CHECK(status IN ('granted','used','withdrawn','expired','failed')),
        valid_from TEXT NOT NULL, valid_until TEXT,
        indicated_by TEXT NOT NULL CHECK(indicated_by IN ('learner_voice','learner_console','household_setting')),
        created_at TEXT NOT NULL);
    CREATE TABLE egress_log(
        id INTEGER PRIMARY KEY, destination TEXT NOT NULL,
        purpose TEXT NOT NULL CHECK(purpose IN
            ('decide','generate','answer','judge','word','tts','media','catalog','ops')),
        learner_id INTEGER REFERENCES learners(id), session_id INTEGER REFERENCES reading_sessions(id),
        payload_size INTEGER NOT NULL, body_hmac TEXT NOT NULL, consent_id INTEGER REFERENCES consents(id),
        status TEXT NOT NULL CHECK(status IN ('sending','sent','failed','unknown')),
        transmitted_attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        CHECK((purpose = 'ops') = (learner_id IS NULL)));
    CREATE TABLE lexicon(
        word TEXT NOT NULL, language TEXT NOT NULL,
        source TEXT NOT NULL CHECK(source IN ('book','correction','manual')), book_id INTEGER,
        weight REAL NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
    CREATE TABLE learner_profile(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE alert_outbox(
        id INTEGER PRIMARY KEY, key TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('down','up','event')),
        reason TEXT NOT NULL, created_at TEXT NOT NULL, toasted INTEGER NOT NULL DEFAULT 0, sent_at TEXT,
        attempts INTEGER NOT NULL DEFAULT 0, next_try_at REAL NOT NULL DEFAULT 0);
    CREATE TABLE service_state(
        service TEXT PRIMARY KEY, kills INTEGER NOT NULL DEFAULT 0, gave_up INTEGER NOT NULL DEFAULT 0,
        latch TEXT NOT NULL DEFAULT 'up' CHECK(latch IN ('up','down')), updated_at TEXT NOT NULL);
    CREATE UNIQUE INDEX lexicon_key ON lexicon(word, language, source, IFNULL(book_id, -1));
    CREATE UNIQUE INDEX household_terms_term ON household_terms(term COLLATE NOCASE);
    CREATE INDEX miscues_read ON miscues(page_read_id);
    CREATE UNIQUE INDEX miscues_open_token ON miscues(page_read_id, page_revision_id, expected_token_index)
        WHERE status = 'candidate';
    CREATE INDEX page_reads_session ON page_reads(session_id);
    CREATE UNIQUE INDEX page_reads_cycle_page ON page_reads(cycle_id, page_id) WHERE cycle_id IS NOT NULL;
    CREATE INDEX reading_sessions_learner ON reading_sessions(learner_id, book_id);
    CREATE INDEX activities_session ON activities(session_id);
    """

# Migration 5's copy expressions for columns a version-4 row does not have (ADR-0018 §3: existing text becomes
# `learner` text of the first learner, page-derived fields become `page`). `{L}` is the first learner's id.
_V5_COPY: dict[str, dict[str, str]] = {
    "reading_sessions": {"learner_id": "{L}"},
    "knowledge_items": {"learner_id": "{L}"},
    "difficulties": {"learner_id": "{L}"},
    "review_answers": {"learner_id": "{L}"},
    "encounters": {"learner_id": "{L}", "context_provenance_class": "'page'", "context_source_learners": "'[]'",
                   "explanation_provenance_class": "'learner'", "explanation_source_learners": "'[{L}]'"},
    "anki_outbox": {"learner_id": "{L}", "card_provenance_class": "'learner'", "card_source_learners": "'[{L}]'"},
    "corrections": {"source_learner_id": "CASE WHEN source = 'parent' THEN NULL ELSE {L} END"},
    "utterances": {"session_id": "COALESCE(session_id, (SELECT pr.session_id FROM page_reads pr "
                                 "WHERE pr.id = page_read_id))",
                   "provenance_class": "'learner'", "source_learners": "'[{L}]'"},
    "miscues": {"origin": "CASE WHEN heard IS NULL THEN 'deletion' ELSE 'substitution' END"},
}


class SchemaError(RuntimeError):
    """The file cannot be opened at this schema; the message names what to run."""


class NeedsMigration(SchemaError):
    pass


class DatabaseInUse(RuntimeError):
    """The lock file says another Leafi process has the database open (or a migration is running)."""


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")


def lock_path(db: Path) -> Path:
    return db.with_name(db.name + ".users")


class _FileLock:
    """One OS lock on `<db>.users`, held per handle: shared by every opener, exclusive for a migration."""

    def __init__(self, db: Path, exclusive: bool) -> None:
        path = lock_path(db)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: IO[str] | None = open(path, "a+")  # noqa: SIM115 - held for the Store's lifetime
        flags = (portalocker.LOCK_EX if exclusive else portalocker.LOCK_SH) | portalocker.LOCK_NB
        try:
            portalocker.lock(self._fh, flags)
        except portalocker.LockException as e:
            self._fh.close()
            self._fh = None
            if exclusive:
                raise DatabaseInUse(f"{db.name} is open in another Leafi process (supervisor, web UI, a session "
                                    "or a CLI command); close them all and run the command again") from e
            raise DatabaseInUse(f"{db.name} is being migrated (python -m leafi migrate); try again when it "
                                "finishes") from e

    def release(self) -> None:
        if self._fh is not None:
            try:
                portalocker.unlock(self._fh)
            finally:
                self._fh.close()
                self._fh = None


class UnsafeSQLite(RuntimeError):
    """A SQLite library with the WAL-reset bug met a WAL file it could not return to rollback mode."""


def _library_version() -> tuple[int, int, int]:
    return sqlite3.sqlite_version_info


def wal_safe(version: tuple[int, int, int]) -> bool:
    """Free of the WAL-reset bug: 3.51.3 and later, or the 3.50.7 / 3.44.6 backports (sqlite.org/wal.html §11)."""
    return version >= (3, 51, 3) or (3, 50, 7) <= version < (3, 51, 0) or (3, 44, 6) <= version < (3, 45, 0)


def _migrate_hint(db: Path, version: int) -> str:
    return (f"{db.name} is at schema {version}, this Leafi needs {SCHEMA_VERSION}: run `python -m leafi backup`, "
            f"then `python -m leafi migrate --learner \"<name of the child who has been reading>\"` "
            "with every other Leafi process closed (ADR-0018 §7.2)")


class Store:
    """One connection per process; `with store.transaction():` for atomic multi-row writes.

    `journal_mode` forces a mode in tests; production leaves it None and the library version decides (ADR-0019).
    """

    def __init__(self, path: Path | str, journal_mode: str | None = None) -> None:
        self.path = Path(path)
        memory = str(path) == ":memory:"
        self._lock: _FileLock | None = None
        if not memory:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._lock = _FileLock(self.path, exclusive=False)
        try:
            self.conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
            # An unclosed Store closes its connection BEFORE its lock goes (codex M3 review #5): the connection can
            # outlive the Store in a reference cycle, and a migration must never see the lock free while it is open.
            self._finalizer = weakref.finalize(self, _close, self.conn, self._lock)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            if not memory:
                self._set_journal_mode(journal_mode)
            self.conn.execute("PRAGMA busy_timeout = 5000")  # the supervisor and a session write one file (ADR-0016)
            self.conn.execute(f"PRAGMA journal_size_limit = {JOURNAL_SIZE_LIMIT}")
            self.conn.execute("PRAGMA secure_delete = ON")  # forgotten rows are overwritten, not left in free pages
            self._depth = 0
            self._open_schema()
        except BaseException:
            if getattr(self, "_finalizer", None) is not None:
                self._finalizer()
            elif self._lock is not None:
                self._lock.release()
            raise

    def _set_journal_mode(self, forced: str | None) -> None:
        """Runs before busy_timeout is set: a switch that would wait for another connection fails at once, warns,
        and is retried at the next open. An unfixed library that cannot leave WAL refuses the file (ADR-0019 §1)."""
        version = _library_version()
        want = forced or ("wal" if wal_safe(version) else "delete")
        if forced is None and want == "delete" and self.journal_mode != "wal":
            return  # an unfixed library on a rollback file: nothing to change, nothing to warn about
        try:
            got = self.conn.execute(f"PRAGMA journal_mode = {want}").fetchone()[0]
        except sqlite3.OperationalError as e:
            if e.sqlite_errorname not in ("SQLITE_BUSY", "SQLITE_LOCKED"):
                raise
            got = f"unchanged ({e})"
        v = ".".join(map(str, version))
        if want == "delete" and forced is None:
            if got != "delete":
                raise UnsafeSQLite(f"SQLite {v} has the WAL-reset bug and {self.path.name} is in WAL with another "
                                   "connection open; replace the Python install's DLLs\\sqlite3.dll (ADR-0019 §2)")
            log.warning("SQLite %s has the WAL-reset bug; %s returned to rollback mode; replace sqlite3.dll "
                        "(ADR-0019 §2)", v, self.path.name)
        elif got != want:
            log.warning("journal_mode = %s not applied to %s (%s); retried at the next open", want, self.path.name, got)

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def journal_mode(self) -> str:
        return self.conn.execute("PRAGMA journal_mode").fetchone()[0]

    # ---- schema
    def _open_schema(self) -> None:
        """The three states of ADR-0018 §7.2. Two openers of one empty file race safely: the second reads the
        version again under the write lock and finds the schema made (ADR-0019 §5)."""
        version = self.version  # read once: each decision below uses one reading (codex M3 #4)
        if version == SCHEMA_VERSION:
            return
        if version == 0:  # classified again under the write lock: another opener may have just created it
            with self.transaction():
                version = self.version
                if version == SCHEMA_VERSION:
                    return
                if version == 0 and _is_empty(self.conn):
                    for stmt in _split(SCHEMA):
                        self.conn.execute(stmt)
                    self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                    return
        if version > SCHEMA_VERSION:
            raise SchemaError(f"{self.path.name} is at schema {version}, newer than this Leafi "
                              f"({SCHEMA_VERSION}); update the code")
        raise NeedsMigration(_migrate_hint(self.path, version))

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
            self.conn.execute("COMMIT")  # inside the try: a failed COMMIT (SQLITE_BUSY) must roll back too
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise
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

    def checkpoint(self) -> bool:
        """Copy the -wal into the database and empty it; False when another connection's read kept it, in which
        case the supervisor's periodic checkpoint retries (ADR-0019 §6)."""
        return _truncate(self.conn)

    def backup(self, dest: Path | str) -> Path:
        """A consistent copy with `VACUUM INTO`: includes rows still in the -wal, and no remnants of deleted rows
        (ADR-0019 §8). The destination must not exist."""
        return _vacuum_into(self.conn, dest)

    def close(self) -> None:
        self._finalizer()


def _close(conn: sqlite3.Connection, lock: _FileLock | None) -> None:
    try:
        conn.close()
    finally:
        if lock is not None:
            lock.release()


def _is_empty(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0


def _vacuum_into(conn: sqlite3.Connection, dest: Path | str) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    conn.execute("VACUUM INTO ?", (str(dest),))
    return dest


def backup_file(path: Path | str, dest: Path | str) -> Path:
    """`Store.backup` for a file at any schema version (`leafi backup` runs before `leafi migrate`)."""
    path = Path(path)
    lock = _FileLock(path, exclusive=False)
    try:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, isolation_level=None)
        try:
            conn.execute("PRAGMA busy_timeout = 5000")
            return _vacuum_into(conn, dest)
        finally:
            conn.close()
    finally:
        lock.release()


BACKUPS_KEPT = 3  # owner decision 2026-10-23: the newest three, migration backups included


def prune_backups(folder: Path, keep: int = BACKUPS_KEPT) -> list[Path]:
    """Delete every `leafi-*.db` in `folder` but the `keep` newest by modification time; returns the deleted.
    Backups keep forgotten data (ADR-0019 §8), so pruning is also how a `forget` reaches them."""
    if keep < 1:
        raise ValueError("keep at least one backup")
    found = sorted(folder.glob("leafi-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    gone = found[keep:]
    for p in gone:
        p.unlink()
    return gone


def _truncate(conn: sqlite3.Connection) -> bool:
    if conn.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
        return True
    busy, _, _ = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    return not busy


def checkpoint_file(path: Path | str) -> bool:
    """`Store.checkpoint()` on a short-lived connection of its own, for a thread off the supervisor's event loop."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        return _truncate(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------- migration 5 (ADR-0018 §7.2)


@dataclass
class MigrationResult:
    from_version: int
    backup: Path | None
    learner_id: int | None
    rebuilt: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)


def _normal_sql(sql: str) -> str:
    """Schema text without layout, and without the quotes `ALTER TABLE … RENAME` adds to the table name."""
    s = re.sub(r"\s+", " ", sql).strip()
    s = re.sub(r"\s*([(),])\s*", r"\1", s)
    return re.sub(r'^CREATE TABLE "([^"]+)"', r"CREATE TABLE \1", s)


def schema_of(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    """(type, name) → normalised SQL of every table and index, the form a migrated and a fresh file must share."""
    return {(r[0], r[1]): _normal_sql(r[2]) for r in conn.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")}


def _target() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    for stmt in _split(SCHEMA):
        conn.execute(stmt)
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def rebuild(conn: sqlite3.Connection, table: str, target_sql: str, target_cols: list[str],
            copy: dict[str, str]) -> None:
    """SQLite's 12-step table change inside the caller's transaction, with foreign keys already off: create
    `new_<table>` from the target DDL, copy the shared columns (and `copy`'s expressions for the others), drop the
    old table, rename the new one into place (indexes are recreated by the caller)."""
    old_cols = set(_columns(conn, table))
    new = f"new_{table}"
    conn.execute(re.sub(rf"^(\s*CREATE TABLE )({table})\b", rf"\1{new}", target_sql, count=1))
    cols = [c for c in target_cols if c in copy or c in old_cols]
    exprs = [copy.get(c, c) for c in cols]
    conn.execute(f"INSERT INTO {new}({', '.join(cols)}) SELECT {', '.join(exprs)} FROM {table}")
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {new} RENAME TO {table}")


def migrate_file(path: Path | str, learner_name: str, *, backup_dir: Path | None = None,
                 learner_settings: dict | None = None,
                 _hook: Callable[[str], None] | None = None) -> MigrationResult:
    """`python -m leafi migrate --learner <name>`: exclusive lock, a backup, then ONE transaction that brings a
    version-4 file to `SCHEMA` and writes the first learner; any failure rolls it all back (ADR-0018 §7.2).
    `_hook(table)` runs before each rebuild, for the failure-injection test."""
    path = Path(path)
    name = learner_name.strip()
    if not name:
        raise ValueError("the first learner needs a name")
    lock = _FileLock(path, exclusive=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            return MigrationResult(version, None, None)
        if version > SCHEMA_VERSION:
            raise SchemaError(f"{path.name} is at schema {version}, newer than this Leafi ({SCHEMA_VERSION})")
        if version == 0 and _is_empty(conn):
            raise SchemaError(f"{path.name} is empty; Leafi creates it at schema {SCHEMA_VERSION} on first open")
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        dest = (backup_dir or path.parent / "backups") / f"leafi-v{version}-{stamp}.db"
        n = 1
        while dest.exists():  # a rerun right after a failure keeps the first backup too
            dest = dest.with_name(f"leafi-v{version}-{stamp}-{n}.db")
            n += 1
        backup = _vacuum_into(conn, dest)
        while version < len(LEGACY_STEPS):  # files older than 4 (none expected in a household; kept for safety)
            conn.execute("BEGIN IMMEDIATE")
            try:
                for stmt in _split(LEGACY_STEPS[version]):
                    conn.execute(stmt)
                conn.execute(f"PRAGMA user_version = {version + 1}")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            version += 1
        result = MigrationResult(version, backup, None)
        target = _target()
        want = schema_of(target)
        conn.execute("PRAGMA foreign_keys = OFF")  # outside the transaction, or the pragma is a no-op
        conn.execute("PRAGMA legacy_alter_table = ON")
        conn.execute("BEGIN IMMEDIATE")
        try:
            have = schema_of(conn)
            tables = [n for (t, n) in want if t == "table"]
            for t in tables:
                if ("table", t) not in have:
                    conn.execute(target.execute("SELECT sql FROM sqlite_master WHERE name=?", (t,)).fetchone()[0])
                    result.created.append(t)
            cur = conn.execute("INSERT INTO learners(kind, display_name, settings, created_at) VALUES "
                               "('learner', ?, ?, ?)", (name, dumps(learner_settings or {}), now_iso()))
            result.learner_id = first = int(cur.lastrowid)
            for t in tables:
                if t in result.created or have.get(("table", t)) == want[("table", t)]:
                    continue
                if _hook is not None:
                    _hook(t)
                copy = {c: e.replace("{L}", str(first)) for c, e in _V5_COPY.get(t, {}).items()}
                rebuild(conn, t, target.execute("SELECT sql FROM sqlite_master WHERE name=?", (t,)).fetchone()[0],
                        _columns(target, t), copy)
                result.rebuilt.append(t)
            have = schema_of(conn)
            for (kind, n), sql in want.items():
                if kind == "index" and have.get((kind, n)) != sql:
                    if (kind, n) in have:
                        conn.execute(f"DROP INDEX {n}")
                    conn.execute(target.execute("SELECT sql FROM sqlite_master WHERE name=?", (n,)).fetchone()[0])
            bad = conn.execute("PRAGMA foreign_key_check").fetchall()
            if bad:
                raise SchemaError(f"migration 5: {len(bad)} foreign key violation(s), first {tuple(bad[0])}; "
                                  "nothing was changed")
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA legacy_alter_table = OFF")
            conn.execute("PRAGMA foreign_keys = ON")
            target.close()
        return result
    finally:
        conn.close()
        lock.release()


def restore_file(path: Path | str, backup: Path | str) -> None:
    """Put a backup back in place through SQLite's backup API, under the exclusive lock (ADR-0018 §7.2)."""
    path, backup = Path(path), Path(backup)
    if not backup.is_file():
        raise FileNotFoundError(backup)
    lock = _FileLock(path, exclusive=True)
    try:
        src = sqlite3.connect(f"file:{backup.resolve().as_posix()}?mode=ro", uri=True)
        dst = sqlite3.connect(str(path))
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
    finally:
        lock.release()


def _split(script: str) -> list[str]:
    return [s.strip() for s in script.split(";") if s.strip()]


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def loads(text: str | None, default: Any = None) -> Any:
    if text is None:
        return default
    return json.loads(text)
