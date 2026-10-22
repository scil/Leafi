# Database choice: should Leafi move from SQLite to Postgres and ClickHouse?

Checked: 2026-10-22. Method: `tiered-research` (T1 = the owner's own docs, and Leafi's own code and database read directly; T2 = empirical studies, none needed here; T3 = local measurements and exemplar files; T4 = secondary, "reported" only). Every claim traces to a row of §8. Rows marked *(inferred)* are estimates, not measurements.

Decision it serves: the owner asked whether `data/leafi.db` should become Postgres and ClickHouse. The question arrives while ADR-0017 (AI-led study session) and ADR-0018 (learners and privacy v2) are proposed and plan migration 5, a table rebuild under a cross-process file lock. The answer must fit ADR-0004 (SQLite is the system of record, Anki schedules review), the privacy boundary (learner data stays on the machine, ADR-0011/0018), the Windows household PC, and the test suite.

Terms used below:

- **OLTP** (online transaction processing): many small reads and writes of individual rows, each in a short transaction. Leafi's session loop is OLTP.
- **OLAP** (online analytical processing): few large queries that scan and aggregate many rows. Leafi's evaluation of §9 of ADR-0017 is OLAP-shaped but tiny.
- **Writer**: a process that opens the database and writes to it. SQLite allows one write transaction at a time per file (S1, S2).
- **`SQLITE_BUSY`**: the error SQLite returns when a lock it needs is held by another connection, after `busy_timeout` expires (S3).
- **Rollback journal** vs **WAL** (write-ahead log): SQLite's two transaction-log modes. Leafi uses the rollback journal today (L2); in it, a writer that is committing blocks new readers. In WAL mode readers and the writer do not block each other (S2).
- **Table rebuild**: SQLite cannot change most constraints in place, so a migration that adds a CHECK value or a NOT NULL creates a new table, copies the rows, drops the old one and renames (harness-libraries research §1, M28).

## 1. Answer in one paragraph

No. Keep SQLite as the system of record (ADR-0004 stands) and change its journal to WAL as a reviewed, separate design step. Leafi's data is a few hundred kilobytes today and, by the estimate in §2.3, at most a few hundred megabytes per year for a household of three children; it has two to four writer processes on one PC, each writing a few short transactions per second at most. That is the workload SQLite's own documentation names as its fit (S1). Postgres would solve one real pain, the table-rebuild migration, at the price of a service that must be running before any study session or supervisor can start, a Docker volume or a Windows service to back up and upgrade every year, and a rewritten test suite. ClickHouse solves no problem Leafi has: it does not run natively on Windows, recommends 16–32 GB of RAM, and is built for scans over billions of rows (C1, C2). For the analytics ADR-0017 §9 asks for, plain SQL on SQLite is enough; DuckDB can read the same file ad hoc without a service (D1) if heavier analysis is ever wanted.

## 2. Leafi's actual workload

### 2.1 Measured today (read-only, `mode=ro`, 2026-10-22)

| Fact | Value | Source |
|---|---|---|
| File size of `data/leafi.db` | 167,936 bytes (41 pages of 4 KiB, 0 free) | L1 |
| `PRAGMA user_version` | 4 | L1 |
| `PRAGMA journal_mode` | `delete` (rollback journal) | L1 |
| SQLite in the venv | 3.49.1 | L1 |
| Other database files | `data/sessions.db` 8 KiB (habit track, separate per ADR-0004) | L1 |

Row counts:

| Table | Rows | Table | Rows |
|---|---|---|---|
| `reading_sessions` | 13 | `practices` | 2 |
| `utterances` | 20 | `page_reads` | 15 |
| `observations` | 46 | `pages` / `page_revisions` / `page_images` | 3 / 3 / 2 |
| `miscues` | 6 | `books` | 1 |
| `lexicon` | 44 | `service_state` | 20 |
| `alert_outbox` | 11 | `knowledge_items`, `encounters`, `difficulties`, `anki_outbox`, `review_answers`, `corrections`, `learner_profile` | 0 each |

These are development sessions (13 sessions, 20 utterances), not a household's use; they show the shape (about 2.3 observations per utterance), not the volume.

### 2.2 Who opens the file and how it writes

| Process | Opens `leafi.db` | Writes | Source |
|---|---|---|---|
| Study session (`leafi/runner.py`) | one `Store` for the session | after every utterance: the utterance, its observations (`session.py:726`), miscues, page reads; each step in one `BEGIN IMMEDIATE` transaction | L2, L4 |
| Supervisor (`leafi/ops/supervisor.py:523`) | one `Store` from logon, held open | `service_state` on state changes, `alert_outbox` delivery every 10 s (`DELIVER_EVERY_S`), each in a transaction | L3 |
| CLI commands (`leafi/cli.py` ×3) | short-lived `Store` | exports, `doctor`, corrections | L5 |
| Web UI | today `agent.webui` writes `config/tasks.yml` and `.env`, **not** `leafi.db` (L6); ADR-0017/0018 move per-learner settings onto the settings page, which then reads and writes `leafi.db` | — | L6, A2 |

`Store` sets `foreign_keys = ON`, `busy_timeout = 5000`, migrates on open, and rolls back a failed `COMMIT` (L2). ADR-0017 §7.3 lowers the study process's timeout to 250 ms with async backoff and adds the `store_busy` activity status (A1).

So: **at most four writer processes, one of them (the study session) doing nearly all the writing, at speech pace** — an utterance every few seconds, not a few thousand per second.

Reads: the session loop reads the current page text, the reading state and the menu inputs per step; `knowledge.recompute_difficulties` scans one learner's encounters after a session; `records.export_session` reads one session; ADR-0017 §9's evaluation aggregates per-session outcomes by arm (A1). All are indexed lookups or scans of one learner's rows.

### 2.3 What ADR-0017/0018 add, and rows per year *(inferred)*

New tables (A1 §7.2, A2 §1–§4): `learners`, `cycles`, `activities`, `brain_calls`, `retrieval_events`, `learner_notes` + `learner_note_citations`, `book_notes`, `egress_log`, `consents`. Migration 5 rebuilds the tables whose CHECK or NOT NULL changes, under an exclusive `portalocker` lock, from an explicit `leafi migrate` command (A2 §7.2).

Assumptions for one child: 4 sessions a week (research suggests ≥ 3, A1 §6.3) → about 200 sessions a year; 20 minutes each; 150 utterances per session; 2.3 observations per utterance (§2.1); 10 activities per session (`activities_per_cycle` 6, several cycles); `brain_calls_per_session` capped at 40 (A1 §6.3); 20 retrieval events per session.

| Table | Per session | Per child per year | Three children per year |
|---|---|---|---|
| `utterances` | 150 | 30,000 | 90,000 |
| `observations` | 350 | 70,000 | 210,000 |
| `miscues`, `page_reads`, `encounters` | ~40 | 8,000 | 24,000 |
| `activities`, `cycles` | ~13 | 2,600 | 7,800 |
| `brain_calls` | ≤ 40 | ≤ 8,000 | ≤ 24,000 |
| `egress_log` (≈ one per transmission, plus `ops` rows kept 30 days) | ≤ 40 | ≤ 8,000 | ≤ 24,000 |
| `retrieval_events` | 20 | 4,000 | 12,000 |
| **Total rows** | ~650 | **~130,000** | **~400,000** |

Size: most rows are under 200 bytes; `brain_calls` stores the payload and the response, say 2–8 KB each. Upper bound ≈ 24,000 × 8 KB ≈ 190 MB plus ≈ 400,000 × 200 B ≈ 80 MB → **about 0.1–0.3 GB per year for three children**, the larger part being Brain payloads that ADR-0018 §4.3 can age out. SQLite's documentation calls content "less than a terabyte" with "low writer concurrency" its fit (S1); Leafi is three to four orders of magnitude below that.

## 3. The pains, and which a database change would fix

| Pain | Where | Root cause | Postgres fixes it? | WAL fixes it? | Other fix |
|---|---|---|---|---|---|
| A reader (e.g. `checkpoint`'s settings read) gets `SQLITE_BUSY` | review pass 2, B3.2 (R1) | Rollback journal: a writer in PENDING/EXCLUSIVE refuses new SHARED locks (S3) | yes (MVCC readers never wait) | **yes**: readers do not block writers and writers do not block readers (S2) | — |
| Two writers collide (supervisor vs session) | ADR-0017 §7.3 (A1) | One writer per file (S1, S2) | yes, row-level locks | no, still one writer; but each Leafi transaction is milliseconds, so `busy_timeout` absorbs it | keep transactions short; never hold a write transaction across an `await` |
| `COMMIT` fails while a reader holds a lock | `test_storage.py:75` (L7) | Rollback journal | yes | **yes** (the test's premise disappears; the test must be rewritten to collide two writers) | already handled by `508448b` |
| Migration 5 must rebuild tables to change CHECK/NOT NULL | ADR-0018 §7.2, review G4.3 (A2, R1) | SQLite `ALTER TABLE` limits (M28); native NOT NULL/CHECK changes arrive in 3.53.0 (M29), the venv has 3.49.1 | **yes**: `ADD CONSTRAINT … NOT VALID` + `VALIDATE`, `SET NOT NULL`, no rewrite (P1); DDL is transactional | no | the `rebuild()` helper of harness-libraries §1; or a SQLite ≥ 3.53 build *(not verified for Python 3.12 on Windows)* |
| Migration runs in whichever process opens first | review G4.3 (R1) | `Store.__init__` migrates on open (L2) | **no**: any engine needs one migrator and the others refusing; Postgres would use an advisory lock where SQLite uses `portalocker` | no | ADR-0018 §7.2's explicit `leafi migrate` command, as planned |
| Restoring a backup while another process has the file open fails on Windows | review G4.3 (R1) | Windows file sharing | moves the problem: restoring a Postgres dump also needs the clients stopped | no | restore only under the exclusive lock (A2 §7.2) |
| Analytics over sessions, arms and Brain calls | ADR-0017 §9 (A1) | none yet: at ~600 sessions a year per household the inverse-propensity estimate is one `GROUP BY` | not needed | not needed | SQL views in SQLite; DuckDB `ATTACH … (TYPE sqlite)` for ad-hoc work (D1) |

Postgres's one clear win is the migration row. The other pains are either fixed by WAL or are design problems (who migrates, how restores happen) that any engine has.

## 4. Options

| Option | Problem it solves for Leafi | Operations on the household PC | Fit with ADR-0004 / privacy | Migration story | Tests |
|---|---|---|---|---|---|
| **SQLite, rollback journal (today)** | — | none: a file in `data/` | is ADR-0004; file never leaves the PC | migration 5 as a rebuild under `portalocker` (A2) | 21 of 51 test files open `Store` on `tmp_path` files (L7); fast, isolated |
| **SQLite in WAL mode** (recommended) | reader `SQLITE_BUSY` (B3.2); failed `COMMIT` under a reader | none new; `-wal` and `-shm` files sit beside the DB (S2); WAL is persistent once set (S2); backups must use the backup API or `VACUUM INTO`, never a plain file copy of `leafi.db` alone (S2, S4) | unchanged | unchanged; the rebuild still needs exclusion, and a WAL file can still return BUSY on open during crash recovery or while a connection closes (S2) | `test_storage.py:75` must be rewritten (L7); others unchanged |
| **Postgres** (local, Docker or Windows service) | rebuild migrations (P1); concurrent writers; MVCC reads | a server that must be running before the supervisor and every session start; under Docker Desktop it lives in the WSL 2 VM, whose default memory cap is 50 % of RAM (W1), and ports publish on all interfaces unless bound to `127.0.0.1` (K1) — this repo already binds Frigate's ports wide (L8); native: the EDB installer (P3); a major upgrade every few years needs `pg_dump`/restore or `pg_upgrade` (P2); each major is supported 5 years (P2) | supersedes ADR-0004; data stays local only if the port is loopback-bound and the volume is backed up locally; a new egress row (loopback) | real gain: transactional DDL, `NOT VALID` constraints (P1); needs a one-time SQLite → Postgres copy | every `Store(tmp_path …)` fixture needs a server or a per-test database; the no-network privacy run must allow the DB socket |
| **ClickHouse** | none: no workload of Leafi's is a scan over large data | no native Windows build, WSL only (C1); 32 GB recommended, < 16 GB gives memory exceptions by default, 2 GB "only at a low rate" (C2) | a second store of learner data to protect and forget (ADR-0018 §4.3 `forget` must reach it) | none needed | a second fixture world |
| **Postgres + ClickHouse** | as Postgres, plus an OLAP engine for data Leafi does not have | both of the above, plus a pipeline copying rows between them | two stores to keep consistent for `forget` | both | both |
| **SQLite + DuckDB for analytics** | ad-hoc analysis beyond plain SQL, if ever needed | none: a Python package; `ATTACH 'leafi.db' (TYPE sqlite)` reads the live file, locking left to SQLite, `BUSY_TIMEOUT` 5000 ms (D1) | unchanged; DuckDB is a reader, opened read-only by convention | none | none in the core suite |
| **libSQL / Turso** | none today: libSQL keeps SQLite's single-writer model (T1); concurrent writes are in Turso, a Rust rewrite in beta (T1) | Python driver is experimental (T1) | a fork, not SQLite | as SQLite | as SQLite |

## 5. Recommendation and trade-off

1. **Keep SQLite as the system of record.** ADR-0004 needs no change.
2. **Propose WAL mode as its own small design** (it touches concurrency, so AGENTS.md requires the review path). It removes the reader-side `SQLITE_BUSY` of B3.2 and the failed-`COMMIT`-under-reader case. It needs: `PRAGMA journal_mode = WAL` set once (in migration 5 or `leafi migrate`), backups through the backup API or `VACUUM INTO` (S4), the `test_storage.py:75` test rewritten, and ADR-0017 §7.3's busy handling kept for writer–writer collisions.
3. **Keep ADR-0018 §7.2's explicit `leafi migrate` and `portalocker` exclusion.** A move to Postgres would not remove the need for one migrator.
4. **Do the rebuild with the `rebuild()` helper** from the harness-libraries research §1; re-check later whether a SQLite ≥ 3.53 build is available to the venv, which would make most CHECK/NOT NULL changes native (M29).
5. **Analytics**: SQL views over `activities`, `brain_calls`, `retrieval_events` in SQLite; DuckDB only as an optional tool for the owner, not a core dependency.

Trade-off: Leafi keeps hand-written rebuild migrations (about 80 lines plus tests) and one writer at a time, in exchange for no database service to keep running, no Docker dependency for the core loop (harness-libraries constraint), backups that are one file, and an unchanged test suite.

## 6. What would change this recommendation

| Signal | Threshold | Then |
|---|---|---|
| Writers | more than one process writing continuously (e.g. two study sessions at once in one household, or a web UI with frequent writes) and `store_busy` endings above about 1 % of activities in the supervisor's counts | Postgres becomes worth its operations cost |
| Machines | the database must be shared by more than one computer (a second study station, a NAS) — SQLite and WAL are same-host only (S1, S2) | Postgres, loopback replaced by a LAN address under ADR-0018's `lan` rules |
| Data size | above about 10 GB, or a single analytical query over a minute | DuckDB over a periodic copy first; ClickHouse never at household scale |
| Migrations | more than one or two rebuild migrations a year, or a rebuild that fails in practice | first SQLite ≥ 3.53; Postgres if that is unavailable |
| Product shape | Leafi serving many households from one server | a new ADR: Postgres server-side, with the privacy model rewritten |

## 7. Open questions

- Whether Python 3.12 on Windows can load SQLite ≥ 3.53 (a newer `sqlite3.dll` or an `apsw`/`pysqlite3` wheel) — *not verified*.
- Real `brain_calls` payload size: measure after ADR-0017 runs a few weeks; the 2–8 KB above is *inferred*.
- Whether the supervisor's dashboard reads `leafi.db` often enough to matter under WAL checkpoints — the code shows reads only, *not measured*.

## 8. Sources

| ID | Tier | Source | source-date | checked | Taken (and not taken) |
|---|---|---|---|---|---|
| S1 | T1 | SQLite, Appropriate Uses — https://www.sqlite.org/whentouse.html | updated 2025-05-31 | 2026-10-22 | fit: device-local, low writer concurrency, < 1 TB; one writer per file; client/server for network or many writers |
| S2 | T1 | SQLite, Write-Ahead Logging — https://www.sqlite.org/wal.html | updated 2026-08-25 | 2026-10-22 | readers and writer concurrent, one writer, same host only, `-wal`/`-shm`, persistent mode, BUSY on recovery/close |
| S3 | T1 | SQLite, File Locking v3 — https://www.sqlite.org/lockingv3.html | updated 2025-05-31 | 2026-10-22 | no new SHARED under PENDING; readers coexist with RESERVED |
| S4 | T1 | SQLite, VACUUM — https://www.sqlite.org/lang_vacuum.html | updated 2025-07-12 | 2026-10-22 | `VACUUM INTO` is a consistent snapshot; backup API alternative |
| M28 | T1 | SQLite, ALTER TABLE — https://www.sqlite.org/lang_altertable.html | updated 2026-10-05 | 2026-10-22 | via harness-libraries §9.1; 12-step rebuild |
| M29 | T1 | SQLite 3.53.0 release log — https://www.sqlite.org/releaselog/3_53_0.html | 2026-04-09 | 2026-10-22 | via harness-libraries §9.1; native NOT NULL/CHECK ALTER |
| P1 | T1 | PostgreSQL 18.6, ALTER TABLE — https://www.postgresql.org/docs/current/sql-altertable.html | 18.6 docs, undated | 2026-10-22 | `NOT VALID`/`VALIDATE`, no rewrite for constant defaults, ACCESS EXCLUSIVE by default |
| P2 | T1 | PostgreSQL versioning policy — https://www.postgresql.org/support/versioning/ | living page; 18.6 current | 2026-10-22 | 5-year support, quarterly minors, majors need dump/restore or `pg_upgrade` |
| P3 | T1 | PostgreSQL Windows downloads — https://www.postgresql.org/download/windows/ | living page | 2026-10-22 | EDB installer, zip binaries; desktop Windows "can generally be expected to run" |
| C1 | T1 | ClickHouse, Install on Windows — https://clickhouse.com/docs/install/windows | undated | 2026-10-22 | runs natively on Linux and macOS; Windows via WSL |
| C2 | T1 | ClickHouse, Usage recommendations — https://clickhouse.com/docs/operations/tips | undated | 2026-10-22 | 32 GB recommended, < 16 GB memory exceptions, 2 GB low rate; nothing taken on OLTP fit (page silent) |
| D1 | T1 | DuckDB 2.0, SQLite extension — https://duckdb.org/docs/2.0/core_extensions/sqlite.html | DuckDB 2.0 docs, undated | 2026-10-22 | `ATTACH (TYPE sqlite)`, read-write, locking by SQLite, `BUSY_TIMEOUT` 5000 ms, strict types |
| T1 | T1 | tursodatabase/libsql README — https://github.com/tursodatabase/libsql | living page | 2026-10-22 | single-writer model kept; new features in Turso (beta); Python driver experimental |
| W1 | T1 | Microsoft Learn, WSL config — https://learn.microsoft.com/en-us/windows/wsl/wsl-config | 2026-10-16 | 2026-10-22 | WSL 2 VM memory default 50 % of RAM |
| K1 | T1 | Docker, Port publishing — https://docs.docker.com/engine/network/port-publishing/ | living page | 2026-10-22 | published ports bind all interfaces by default; `127.0.0.1:` prefix to restrict |
| L1 | T3 | Local measurement: `sqlite3.connect("file:data/leafi.db?mode=ro")`, `PRAGMA`s and `count(*)` per table | 2026-10-22 | 2026-10-22 | sizes and counts of §2.1 |
| L2 | T1 | Leafi `leafi/core/storage.py` (`Store`) | HEAD f96b20d | 2026-10-22 | pragmas, migrate on open, `BEGIN IMMEDIATE`, failed COMMIT rollback |
| L3 | T1 | Leafi `leafi/ops/supervisor.py` | HEAD f96b20d | 2026-10-22 | `Store` at line 523, `DELIVER_EVERY_S = 10.0`, transactions on `service_state` |
| L4 | T1 | Leafi `leafi/study/session.py:726`, `leafi/runner.py:33` | HEAD f96b20d | 2026-10-22 | per-utterance observation inserts |
| L5 | T1 | Leafi `leafi/cli.py` lines 76, 85, 112 | HEAD f96b20d | 2026-10-22 | short-lived openers |
| L6 | T1 | Leafi `agent/webui/__main__.py`, `agent/storage.py` | HEAD f96b20d | 2026-10-22 | web UI does not open `leafi.db` today; habit track uses `data/sessions.db` |
| L7 | T1 | Leafi `tests/` (51 files; 21 construct `Store`; 2 import `sqlite3`); `tests/test_storage.py:75` | HEAD f96b20d | 2026-10-22 | test impact |
| L8 | T1 | Leafi `docker-compose.yml` | HEAD f96b20d | 2026-10-22 | Frigate/MQTT ports bound to all interfaces; gatus bound to loopback |
| A1 | T1 | `docs/adr/0017-ai-led-study-session.md` (proposed, v4) | revised 2026-10-22 | 2026-10-22 | §6.3 limits, §7.2 tables, §7.3 busy store, §9 evaluation |
| A2 | T1 | `docs/adr/0018-learners-and-privacy-v2.md` (proposed) | 2026-10-22 | 2026-10-22 | §1 learners, §4.3 retention, §7.2 migration 5 and `portalocker` |
| A3 | T1 | `docs/adr/0004-sqlite-system-of-record-anki-as-scheduler.md` (accepted) | 2026-10-19 | 2026-10-22 | SQLite as system of record |
| R1 | T1 | `docs/plans/active/reviews/2026-10-22-code-plan-review-ai-led-pass-2.md` | 2026-10-22 | 2026-10-22 | B3.2 (reader BUSY), G4.3 (migrate on open, restore under open file) |
| HL | T1 | `docs/research/2026-10-22-harness-libraries.md` §1 | 2026-10-22 | 2026-10-22 | `rebuild()` helper recommendation, M28/M29 rows |
