# Plan review: ADR-0019, the system-of-record SQLite file runs in WAL mode

- Skill: `code-plan-review` (`E:\GitHub\scil\ai-skills\skills\code-plan-review\SKILL.md`)
- Reviewer: a fresh Claude agent, one of three independent reviewers
- Date: 2026-10-22
- Plan: `docs/adr/0019-sqlite-wal-mode.md` (status proposed). Settled and not argued: WAL is decided, SQLite stays (`docs/research/2026-10-22-database-choice.md`).
- Code read: `leafi/core/storage.py`, `leafi/runner.py`, `leafi/ops/supervisor.py` (around `run`), `leafi/cli.py`, `leafi/study/records.py` (`forget_*`), `tests/test_storage.py`, `tests/conftest.py`, `tests/test_supervisor.py` (migration test); docs `docs/architecture/quality-attributes/reliability.md`, ADR-0017 §7.3, ADR-0018 §7.2. Tree grepped for `sqlite3.connect`, `Store(`, `leafi.db`, `journal_mode`, `shutil.copy*`/`os.replace`/`unlink`/`rename`, `VACUUM`, `.backup(`, and `data/` in `scripts/` and `docker-compose.yml`.

## The model, restated

- One file, `data/leafi.db`, opened only through `leafi.core.storage.Store` (one connection per process, autocommit, `BEGIN IMMEDIATE` for writes, `busy_timeout` 5000, migrate on open). Openers in code: `runner.py:33` (study session), `supervisor.py:523` (held open from logon, never closed), `cli.py:76/85/112` (`export`, `forget`, `alert`; short-lived, never closed explicitly). About 21 test files open `Store` on `tmp_path`; `test_storage.py:81` also opens a raw `sqlite3` reader. No container mounts `data/` (`docker-compose.yml` uses named volumes only).
- The change: `Store.__init__` runs `PRAGMA journal_mode = WAL` on every open, before migrating; a non-`wal` answer logs a warning and the open continues in rollback mode; everything else (`synchronous`, `busy_timeout`, `BEGIN IMMEDIATE`, failed-COMMIT rollback, autocheckpoint) stays at its current value or SQLite's default.
- Who decides: whichever process opens the file first after the change converts it; SQLite decides checkpoints (every 1000 pages, and on last close).
- New on-disk state: `leafi.db-wal` and `leafi.db-shm` beside the database. Since the supervisor holds a connection from logon, they exist practically always, and committed data lives in `-wal` until a checkpoint copies it into `leafi.db`.
- Outsiders: none; no public surface. The relevant "outside" party is any tool that copies `data/` (the owner's backup, a manual copy, a restore).

## Decisions for the owner

1. **Does any backup or sync tool copy `data/` today** (Windows File History, OneDrive, a robocopy job, the owner's own backup scheme, a vault console button)? `docs/architecture/quality-attributes/reliability.md:25` says `data/*.db` "are copied by the user's normal backup". Serves I2.3, G4.3, H1.1, H5.1. Recommendation: assume yes; ship a `python -m leafi backup` command (backup API or `VACUUM INTO`) with this ADR and point the user's backup at its output instead of the live file.
2. **Where the conversion runs.** The research (§5.2) said "set once (in migration 5 or `leafi migrate`)"; the ADR sets it on every open from every process. Serves H7.2. Recommendation: keep every-open (it is idempotent and lands before ADR-0018's `leafi migrate` exists), but write the reason into the ADR and handle the raise path (F1.1).
3. **Checkpoint policy.** Whether to force `PRAGMA wal_checkpoint(TRUNCATE)` at the end of a study session, after `forget`, and inside the backup command, or to keep SQLite's default only. Serves H1.1 and the privacy line under Outside the catalog. Recommendation: checkpoint at session end and after `forget`; leave autocheckpoint at default.

## Most severe

| rank | row | cost |
|---|---|---|
| 1 | I2.3 / G4.3 | data lost or corrupted on restore: the documented backup is a file copy of `data/*.db`, which under WAL misses committed data in `-wal` or pairs a `leafi.db` and a `-wal` taken at different instants |
| 2 | H1.1 | same cause, amplifier: with the supervisor never closing and a 168 KB database, autocheckpoint (1000 pages ≈ 4 MB) may not run for weeks, so most recent data exists only in `-wal`; a stale `-wal` left beside a restored file is replayed onto it |
| 3 | F1.1 | an open that cannot take the lock for the conversion raises `database is locked` instead of returning a non-`wal` mode; implemented as written, `Store.__init__` fails and the supervisor or the study session does not start |
| 4 | H5.1 | backup becomes an operation that needs a command, and nothing gives the owner one |
| 5 | H7.2 | the ADR departs from its own research (set once under the migrator's exclusive lock; rewrite the failed-COMMIT test as two colliding writers) without saying why |

## B. The server handles a write

| question | where in the plan | possibility | suggestion |
|---|---|---|---|
| B2.4 | Confirmation | unspecified: the tests cover a new file, an uncontended rollback→WAL switch, and a reader beside a writer; none converts while another connection holds a lock (the warn-and-continue path of §1), and none collides two WAL writers at `BEGIN IMMEDIATE`, which the research said the rewritten test should do and which ADR-0017 §7.3's busy handling depends on | add two tests: (a) a raw connection holds `BEGIN; SELECT` on a rollback file, `Store` opens with a short timeout, asserts the open succeeds in rollback mode with one warning, and the next open after release reports `wal`; (b) two `Store`s on one WAL file, one inside `transaction()`, the other's `transaction()` raises `OperationalError` at `BEGIN IMMEDIATE` with `busy_timeout = 0` and its connection is left usable |

Unlikely: B1.1–B1.5 (no conditional writes change), B2.1 (one file, no lock order change), B2.2 (one connection per process, unchanged), B2.3 (no new call path), B3.1 (no public path), B3.2 (the conversion waits at most `busy_timeout`, 5 s; 250 ms in the study process per ADR-0017 §7.3), B3.3–B3.5 (no retry or sweep added), B4.1–B4.3 (no multi-effect call), B5.1 (WAL gives each read transaction one snapshot; reads become more consistent, not less), B5.2 (no screen).

## F. A branch over a value with several states

| question | where in the plan | possibility | suggestion |
|---|---|---|---|
| F1.1 | §1, "if the pragma returns anything other than `wal` … the open continues in the current mode and logs one warning" | likely: the pragma's outcomes are (a) `wal`; (b) another mode string (`memory` for `":memory:"`, which `Store` accepts at `storage.py:152`; `delete` in some refusal cases); (c) raises `sqlite3.OperationalError: database is locked` when the exclusive lock for the switch cannot be had within the busy timeout. The plan branches only on (a)/(b); (c) escapes `Store.__init__`, so the supervisor at logon (`supervisor.py:523`) or `run_study` (`runner.py:33`) fails to start instead of continuing in rollback mode | name the three outcomes; catch `OperationalError` around the pragma only (locked or busy) and treat it like (b); skip the pragma or the warning for `":memory:"`; log the warning at most once per process so `alert --status` from `health.ps1` does not fill `leafi.log` while a conversion keeps failing |

Unlikely: F1.2–F1.4 (no other branch added), F2.1 (the fall-through, rollback mode, is the safe state).

## G. The domain says what exists

| question | where in the plan | possibility | suggestion |
|---|---|---|---|
| G4.3 | §4, "never a file copy; no current code copies the file" | likely: the ADR adds a constraint on everyone who copies the database and checks it against code only; the existing copier is a documented procedure, `reliability.md:25` ("`data/*.db` are copied by the user's normal backup"), plus any manual copy or restore the owner does from the vault console or Explorer | same fix as I2.3: list every copier and restorer (code, scripts, console buttons, the user's backup), give them one command to call, and rewrite `reliability.md:25` |

Unlikely: G1.1 (no domain rule), G2.1–G2.3 (no entity state), G3.1 (no public writer), G4.1 (no constraint removed), G4.2 (no new writer path into tables), G5.1 (no identity).

## H. Someone already owns this

| question | where in the plan | possibility | suggestion |
|---|---|---|---|
| H1.1 | §2, "Automatic checkpoints stay at SQLite's default … the last connection to close checkpoints and removes the `-wal` file"; §3, "while it is open" | likely: the defaults read are `synchronous`, `busy_timeout` and `wal_autocheckpoint`; their effect here is unstated. The supervisor holds its connection from logon and is stopped by kill or logoff, never by `close()`, so "last connection to close" practically never happens; at Leafi's write rate (research §2.1: 41 pages) the 1000-page autocheckpoint may not fire for weeks, so `leafi.db` alone is stale by weeks and `-wal` is the live data. `journal_size_limit` (unset: `-wal` keeps its high-water size) is not mentioned | state per setting its value and what it does here; checkpoint explicitly where a consistent main file matters (the backup command uses the backup API anyway; `PRAGMA wal_checkpoint(TRUNCATE)` at session end and after `forget`, decision 3); restore procedure: stop every Leafi process, then delete `-wal` and `-shm` before putting the restored file in place, or restore through the backup API into the live file. One cause with I2.3 and G4.3 |
| H1.3 | Consequences, "a `COMMIT` can still fail on a writer–writer collision" | possible: with `BEGIN IMMEDIATE` the write lock is taken at `BEGIN`, so under WAL a second writer fails at `BEGIN IMMEDIATE`, not at `COMMIT`; no source is cited. An implementer of ADR-0017 §7.3 who wraps only `COMMIT` in the busy retry misses the real failure point | cite the SQLite page for where `SQLITE_BUSY` surfaces in WAL with `BEGIN IMMEDIATE`, and say that §7.3's retry wraps the whole `transaction()` |
| H3.3 | Confirmation, "a test-only `journal_mode` argument" | possible: the production constructor grows a parameter whose only caller is a test, and the failed-COMMIT rollback is then exercised only in a mode production never runs | keep `Store`'s signature; make the COMMIT fail inside the test by wrapping `store.conn` in a proxy whose `execute("COMMIT")` raises `OperationalError`, in WAL, so the rollback path is tested as it runs |
| H5.1 | §4 | likely: once a file copy is unsafe, a backup (and a restore) is an operation the owner repeats and can only do correctly through a command; the plan adds no command and no console step, and the project keeps a console (`Leafi Console buttons · 控制台按钮.md`) | add `python -m leafi backup [--to <dir>]` (backup API or `VACUUM INTO`, keeping N copies) with a console button, and the console's own check run; the restore stays a documented procedure unless the owner wants a button |
| H7.2 | §1 and Confirmation versus research §5.2 and §3 | likely: the research recommended setting WAL once "in migration 5 or `leafi migrate`" (under the exclusive lock of ADR-0018 §7.2) and rewriting the failed-COMMIT test "to collide two writers"; the ADR converts on every open from whichever process opens first (the shape the research's own row "migration runs in whichever process opens first" warns about) and keeps the old test in rollback mode via a test-only argument; neither departure states its reason | add one line per departure with its reason (decision 2), or follow the research; for the test, see H3.3 and B2.4 |

Unlikely: H1.2 (no hand-written twin of a SQLite feature), H1.4 (no copied pairing), H1.5 (tests use real SQLite, no stub), H2.1–H2.3 (no interaction concern), H3.1, H3.2, H3.4 (the setting lives in one place, `Store.__init__`), H4.1–H4.3 (no content), H6.1 (stdlib `sqlite3` is imported by `storage.py` alone for this file; `agent/storage.py` owns the separate `sessions.db`; the raw reader in `test_storage.py:81` is a test), H6.2 (no swappable adapter), H6.3 (no pin; the venv's SQLite 3.49.1 supports WAL), H7.1 (provenance: adopted from `sqlite.org/wal.html`).

## I. One truth, several copies

| question | where in the plan | possibility | suggestion |
|---|---|---|---|
| I2.3 | §4 versus `docs/architecture/quality-attributes/reliability.md:25` | likely: two documents state the backup rule and they disagree: reliability.md says the user's normal backup copies `data/*.db`; ADR-0019 says never a file copy. A file backup under WAL either misses everything still in `-wal` (H1.1: possibly weeks) or captures `leafi.db` and `-wal` at different instants; restoring the pair, or restoring `leafi.db` beside a leftover newer `-wal`, replays frames onto the wrong pages | one owner for "how `leafi.db` is backed up and restored" (ADR-0019 §4, or reliability.md with the ADR linking to it), naming the `leafi backup` command (H5.1) and the restore steps (H1.1); reliability.md's line rewritten in the same change. Same cause as G4.3 and H1.1 |

Unlikely: I1.1, I1.2 (nothing rendered twice), I1.3 (one path, `Settings.db_path`; `-wal`/`-shm` are derived by SQLite; no container or second host sees `data/`), I2.1, I2.2 (no business rule), I3.1, I3.2 (no confirmation).

## Not touched

- A. The client sends a request: no client or request path changes.
- C. Who is asking: no identity or authorization decision.
- D. A screen holds state: no screen.
- E. A journey across routes: no routes.
- J. Time passes: no deadline or time-driven state.
- K. A pipeline judges input: no recognizer or judgement.

## Materials

- Owner decisions (backup tooling in use, conversion site, checkpoint policy): absent (delegated); recorded under Decisions for the owner, rows marked as above.
- Openers of the database, file copies under `data/`, test fixtures opening `Store`: read from the files (grep of the tree, listed in the header).
- Bindings loaded: none. The stack is Python 3.12 + stdlib `sqlite3` (SQLite 3.49.1) on Windows; no `references/stacks/` file covers SQLite or Python. SQLite behaviours used here (the switch to WAL needs an exclusive lock and reports busy as an error; `BEGIN IMMEDIATE` takes the write lock at begin; autocheckpoint at 1000 pages; a leftover `-wal` is replayed on open) are general knowledge, to be confirmed against `sqlite.org/wal.html` and `sqlite.org/pragma.html#pragma_journal_mode`.

## Outside the catalog

- A long-lived connection that leaves a read statement un-reset pins a WAL snapshot: that process silently reads stale data and checkpoints cannot pass it, so `-wal` grows. In rollback mode the same bug surfaced loudly as writers' `SQLITE_BUSY`. The supervisor's connection is the candidate (open from logon); CPython's refcounting makes it unlikely with `Store.one/all`, but a test that runs a supervisor poll and then asserts `PRAGMA wal_checkpoint` reports no busy frames would pin it. Binding candidate for a future `sqlite.md`.
- Privacy of `forget` (ADR-0010 §9, ADR-0018 §4.3): deleted learner words stay readable in freed pages of `leafi.db` today (no `secure_delete`), and under WAL also in old `-wal` frames until they are overwritten; a file backup then carries them. Pre-existing in part, widened by WAL; `PRAGMA secure_delete` plus a `TRUNCATE` checkpoint after `forget` would close it (decision 3).
- Binding candidate `sqlite.md` (third time it is proposed in this repository's reviews): add the WAL shapes above (conversion raises busy; backup by file copy; stale `-wal` on restore; pinned snapshot).
