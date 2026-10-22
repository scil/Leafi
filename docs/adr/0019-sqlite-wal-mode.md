---
status: proposed
date: 2026-10-22
amends: 0004
---

# The system-of-record SQLite file runs in WAL mode

Owner decision 2026-10-22 ("use WAL mode"), from the research [`../research/2026-10-22-database-choice.md`](../research/2026-10-22-database-choice.md) (keep SQLite, ADR-0004 stands; do not adopt Postgres or ClickHouse; switch the journal to WAL as its own reviewed step).

**Problem.** `data/leafi.db` runs in SQLite's default rollback journal (`journal_mode = delete`). Five kinds of process open it — the study session (`runner`), the supervisor (ADR-0016, from logon), and three `leafi` CLI commands — and in rollback mode a writer that is committing refuses new readers, and a reader that holds a read lock makes a writer's `COMMIT` wait and fail with `SQLITE_BUSY` after `busy_timeout` (code-plan-review pass 2, B3.2; the failed-`COMMIT` defect fixed in `508448b`).

**Decision.** `leafi.core.storage.Store` opens every connection in **WAL** (write-ahead log) mode: readers and the one writer no longer block each other; writers still take turns (one write transaction at a time per file, unchanged). Provenance: *adopted* from SQLite's own documentation (`https://www.sqlite.org/wal.html`; research S2).

1. **Setting it.** WAL is a property of the database file, persistent once set. `Store.__init__` runs `PRAGMA journal_mode = WAL` after connecting and before migrating, on every open; it is a no-op when the file is already in WAL. Switching an existing file from rollback to WAL needs a moment with no other connection writing; if the pragma returns anything other than `wal` (another process holds a lock at that moment), the open continues in the current mode and logs one warning, and the next open retries. A new empty file is created in WAL directly.
2. **Unchanged.** `synchronous` stays at SQLite's default (`FULL`), so a committed transaction survives a power loss as before; `busy_timeout` stays 5000 ms; `BEGIN IMMEDIATE` transactions, the rollback of a failed `COMMIT` (`508448b`) and ADR-0017 §7.3's busy handling for writer–writer collisions all stay. Automatic checkpoints stay at SQLite's default (every 1000 pages); the last connection to close checkpoints and removes the `-wal` file.
3. **Two new files.** WAL keeps `data/leafi.db-wal` and `data/leafi.db-shm` beside the database while it is open. Both are under `data/`, which is gitignored (AGENTS.md boundary unchanged). WAL works only on a local disk shared by processes on the same machine (research S2); `data/` is local.
4. **Copies and backups.** A copy of `leafi.db` alone, taken while a connection is open, can miss committed transactions still in `-wal`. Any backup, export of the file, or restore (including ADR-0018 §7.2's migration backup) uses SQLite's backup API or `VACUUM INTO`, never a file copy; no current code copies the file.
5. **Read-only openers.** A `mode=ro` connection to a WAL file needs the `-shm` file to exist or the directory to be writable; ad-hoc read-only scripts on this PC satisfy that.
6. **The habit track's `data/sessions.db`** (`agent/storage.py`, ADR-0004's separate store) is not changed.

**Consequences.** The reader-side `SQLITE_BUSY` of pass 2 B3.2 disappears, and a `COMMIT` no longer fails because a reader holds a lock; a `COMMIT` can still fail on a writer–writer collision, which the existing rollback and ADR-0017 §7.3 cover. Two transient files appear in `data/`. Copying the database file by hand becomes unsafe while Leafi runs.

**Confirmation.** `tests/test_storage.py`: a new store reports `journal_mode = wal`; an existing rollback-journal file is switched to WAL on its next open; a second connection holding an open read transaction does not block a write and its `COMMIT`; the existing failed-`COMMIT` regression test keeps exercising the rollback by opening its store in rollback mode explicitly (a test-only `journal_mode` argument), because in WAL a reader can no longer make a `COMMIT` fail. The full suite passes.
