"""`python -m leafi <command>`: devices, doctor, study, export, forget, backup, setup."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from leafi.core.config import Settings


def _settings() -> Settings:
    from leafi import bootstrap

    s = Settings()
    bootstrap.install(s)  # the socket guard, before any service is built (M5 design D2)
    return s


def cmd_devices(args: argparse.Namespace) -> int:
    from leafi import app

    settings = _settings()
    built = app.build(settings, text_mode=False)
    cfg = built.config
    print(f"voice_policy: {cfg.voice_policy}   primary_mouth: {cfg.primary_mouth}")
    print(f"study.eye: {cfg.study_eye}   study.listener: {cfg.study_listener} -> {built.hub.study_listener}")
    print(f"{'device':<16}{'adapter':<16}{'capabilities':<26}state")
    for d in cfg.devices:
        state = f"disabled ({d.disabled})" if d.disabled else ("enabled" if d.name in built.devices else "disabled")
        print(f"{d.name:<16}{d.adapter:<16}{','.join(d.capabilities):<26}{state}")
    hub = built.hub
    print(f"hub: mouths={sorted(hub.mouths)} faces={sorted(hub.faces)} eyes={sorted(hub.eyes)} "
          f"listeners={sorted(hub.listeners)} notifiers={sorted(hub.notifiers)}")
    for w in built.warnings:
        print(f"warning: {w}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from leafi import doctor

    settings = _settings()
    if args.download:
        if settings.leafi_no_network:
            print("LEAFI_NO_NETWORK=1: nothing is downloaded.")
            return 2
        print("downloading missing models (the only sanctioned download, ADR-0011):")
        for label, outcome in doctor.download(settings, set(args.only) if args.only else None):
            print(f"  {label:<16}{outcome}")
    print(doctor.report(settings))
    return 0


def cmd_study(args: argparse.Namespace) -> int:
    from leafi.runner import run_study

    settings = _settings()
    try:
        return asyncio.run(run_study(settings, args))
    except KeyboardInterrupt:
        # Ctrl-C: the session task was cancelled and cleaned up (lease released, line stopped); the session row
        # is closed as interrupted at the next start (ADR-0013 → Interrupted session). No traceback for the owner.
        print("\nLeafi: stopped. The session is closed as interrupted at the next start.")
        return 130


def cmd_export(args: argparse.Namespace) -> int:
    from leafi.core.storage import Store
    from leafi.study.records import export_session

    with Store(_settings().db_path) as store:
        print(json.dumps(export_session(store, args.session), ensure_ascii=False, indent=2))
    return 0


def cmd_forget(args: argparse.Namespace) -> int:
    from leafi.core.storage import Store
    from leafi.study.records import forget_book, forget_session

    settings = _settings()
    with Store(settings.db_path) as store:
        if args.learner is not None:
            code = _forget_learner(args, settings, store)
            if code:
                return code
        if args.session is not None:
            forget_session(store, args.session)
            print(f"forgot session {args.session}")
        if args.book is not None:
            forget_book(store, args.book)
            print(f"forgot book {args.book} (archived)")
        if not store.checkpoint():
            print("another Leafi process is reading: the deleted rows stay in leafi.db-wal until the supervisor's "
                  "next checkpoint (CHECKS_EVERY_S, 15 min by default)")
    backups = sorted((settings.data_dir / "backups").glob("leafi-*.db"))
    if backups:  # ADR-0019 §8: forgetting never edits a backup
        print(f"{len(backups)} backup(s) in {settings.data_dir / 'backups'} were made before this and still hold "
              "the forgotten data; delete them to forget it there too")
    return 0


def _forget_learner(args: argparse.Namespace, settings: Settings, store) -> int:
    """ADR-0018 §1. Without `--yes` it only says what would go; the Anki deck is a separate confirmation."""
    from leafi.core import learner_store
    from leafi.study import records

    row = learner_store.get(store, args.learner)
    if row is None or row["kind"] == "anonymous":
        print(f"no learner #{args.learner}")
        return 1
    sessions = store.one("SELECT COUNT(*) AS n FROM reading_sessions WHERE learner_id=?", (args.learner,))["n"]
    if not args.yes:
        print(f"would forget learner #{args.learner} {row['display_name']}: {sessions} session(s), their items, "
              "notes, cards and every text derived from them; the name stays replaced in shared page text. "
              "Run again with --yes to do it.")
        return 1
    try:
        rep = records.forget_learner(store, args.learner, settings.data_dir, settings.anki_deck)
    except records.LearnerBusy as e:
        print(e)
        return 1
    print(f"forgot learner #{args.learner}: {rep.sessions} session(s), {rep.derived_removed} derived text(s)")
    if rep.anki_notes:
        print(f"{len(rep.anki_notes)} card(s) are already in Anki deck {rep.deck!r} (note ids "
              f"{', '.join(map(str, rep.anki_notes[:20]))}{' …' if len(rep.anki_notes) > 20 else ''}); "
              "remove them there")
    if args.delete_anki_deck:
        from leafi.study.anki import AnkiClient

        try:
            asyncio.run(AnkiClient(settings.anki_url).invoke("deleteDecks", decks=[rep.deck], cardsToo=True))
            print(f"deleted Anki deck {rep.deck!r}")
        except Exception as e:  # noqa: BLE001 - the forgetting itself is done; report and go on
            print(f"Anki deck {rep.deck!r} not deleted ({type(e).__name__}); delete it in Anki")
    elif rep.deck:
        print(f"the Anki deck {rep.deck!r} is kept; run with --delete-anki-deck as well to delete it")
    return 0


def cmd_privacy(args: argparse.Namespace) -> int:
    """`privacy schools`: every learner's school answer, for the owner to confirm (a voice answer is a child's ASR
    text). `privacy learner NAME school VALUE`: set it (a school name, or `none`); without `--yes` it only shows the
    learner, the key and the value (design D10/D12)."""
    from leafi.core import learner_store
    from leafi.core.storage import Store
    from leafi.privacy import settings as privacy

    settings = _settings()
    if args.what == "terms":
        return _privacy_terms(args, settings)
    with Store(settings.db_path) as store:
        if args.what == "schools":
            for r in learner_store.enrolled(store):
                p = privacy.read(store, r["id"])
                if p.school is None:
                    shown = "NOT ANSWERED: their own words stay off the cloud"
                elif p.school == "none":
                    shown = "no school"
                else:
                    shown = repr(privacy.school_name(store, p))
                print(f"#{r['id']} {r['display_name']}: {shown}")
            return 0
        try:
            lid, _ = learner_store.choose(store, args.name, enrol=False)
        except learner_store.LearnerChoice as e:
            print(e)
            return 1
        value = None if args.value.strip().casefold() == "none" else args.value.strip()
        shown = "no school" if value is None else repr(value)
        if not args.yes:
            print(f"would set the school of learner #{lid} {args.name} to {shown}. Run again with --yes to do it.")
            return 1
        try:
            p = privacy.set_school(store, lid, value)
        except privacy.InvalidPrivacySetting as e:
            print(e)
            return 1
        print(f"learner #{lid} {args.name}: school {shown} (privacy version {p.version})")
    return 0


def _privacy_terms(args: argparse.Namespace, settings: Settings) -> int:
    """`privacy terms [list]`, `add TERM [--kind]`, `remove TERM`, `import`: the household's protected names,
    schools and other terms (ADR-0018 §3); changes need `--yes`."""
    from leafi.core.config import legacy_redact_terms
    from leafi.core.storage import Store, import_legacy_terms
    from leafi.privacy import settings as privacy

    action = args.action or "list"
    with Store(settings.db_path) as store:
        if action == "list":
            rows = privacy.terms(store)
            for tid, term, kind, former in rows:
                print(f"#{tid} {kind:<7}{term}" + (f"  (forgotten learner #{former})" if former is not None else ""))
            if not rows:
                print("no household terms; the learners' own names are protected without one")
            return 0
        if action == "import":
            legacy = legacy_redact_terms()
            if not legacy:
                from dotenv import dotenv_values

                if Path(".env").exists() and "REDACT_TERMS" in dotenv_values(".env", encoding="utf-8"):
                    if not args.yes:
                        print("REDACT_TERMS is empty: would remove the line from .env. Run again with --yes.")
                        return 1
                    return _unset_env("REDACT_TERMS")
                print("REDACT_TERMS is not set: nothing to import")
                return 0
            if not args.yes:
                print(f"would import {len(legacy)} REDACT_TERMS term(s) as names and remove the key from .env. "
                      "Run again with --yes to do it.")
                return 1
            with store.transaction():
                n = import_legacy_terms(store.conn, legacy)
            print(f"imported {n} term(s) into household_terms ({len(legacy) - n} already there or a learner's name)")
            return _unset_env("REDACT_TERMS")
        if not args.term:
            print(f"privacy terms {action} needs a term")
            return 2
        shown = f"{args.kind} {args.term!r}" if action == "add" else repr(args.term)
        if not args.yes:
            print(f"would {action} household term {shown}. Run again with --yes to do it.")
            return 1
        try:
            if action == "add":
                tid = privacy.add_term(store, args.term, args.kind)
                print(f"household term #{tid}: {shown}")
            else:
                for line in privacy.remove_term(store, args.term):
                    print(line)
                print(f"removed household term {shown}")
        except privacy.InvalidPrivacySetting as e:
            print(e)
            return 1
    return 0


def _unset_env(key: str) -> int:
    """Remove a retired key from `.env` through the shared writer (lock, backup, canonical form)."""
    from leafi import envedit

    try:
        digest = envedit.current_digest()
    except OSError as e:
        print(f"{key} left in .env: it cannot be read ({e.__class__.__name__})")
        return 1
    result = envedit.save({"digest": digest, "ops": {key: {"op": "unset"}}}, trusted_confirm=True)
    if result.body.get("ok"):
        print(f"{key} removed from .env")
        return 0
    print(f"{key} left in .env:", result.body.get("error") or "; ".join(
        f"{k}: {v}" for k, v in result.body.get("errors", {}).items()))
    return 1


def cmd_backup(args: argparse.Namespace) -> int:
    """A consistent copy of data/leafi.db through SQLite's backup API; never copy the file by hand (ADR-0019 §8).
    Works at any schema version, so it runs before `migrate`."""
    import datetime as dt

    from leafi.core.storage import BACKUPS_KEPT, backup_file, prune_backups

    settings = _settings()
    if args.prune:
        keep = BACKUPS_KEPT if args.keep is None else args.keep
        if keep < 1:
            print("--keep must be at least 1")
            return 2
        folder = settings.data_dir / "backups"
        gone = prune_backups(folder, keep) if folder.is_dir() else []
        for p in gone:
            print(f"deleted {p.name}")
        print(f"kept the newest {keep} backup(s) in {folder}; deleted {len(gone)}")
        return 0
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = args.to or settings.data_dir / "backups" / f"leafi-{stamp}.db"
    if not settings.db_path.exists():
        print(f"nothing to back up: {settings.db_path} does not exist")
        return 1
    print(f"backed up to {backup_file(settings.db_path, dest)}")
    from leafi.privacy import secret

    key = secret.key_path(settings.data_dir)
    if key.exists():  # the surrogates of a restored database need the key they were made with (design D8)
        import shutil

        shutil.copyfile(key, Path(dest).with_suffix(".key"))
        print(f"and its egress key to {Path(dest).with_suffix('.key')}")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    """ADR-0018 §7.2: the one command that changes the schema of a file with data; every other process closed."""
    from leafi.core import storage

    settings = _settings()
    path = settings.db_path
    try:
        if args.restore:
            storage.restore_file(path, args.restore)
            print(f"restored {path} from {args.restore}")
            return 0
        if not path.exists():
            print(f"{path} does not exist; Leafi creates it at schema {storage.SCHEMA_VERSION} on first open")
            return 0
        if not args.learner and storage.file_version(path) < 5:
            print("migrate needs --learner followed by the first name of the child whose sessions are already "
                  "recorded, in quotes")
            return 2
        from leafi.core.config import legacy_redact_terms

        res = storage.migrate_file(path, args.learner, learner_settings={"anki.deck": settings.anki_deck},
                                   legacy_terms=legacy_redact_terms())
    except storage.DatabaseInUse as e:
        print(e)
        return 2
    except (storage.SchemaError, ValueError, FileNotFoundError) as e:
        print(f"not migrated: {e}")
        return 1
    if res.from_version == storage.SCHEMA_VERSION:
        print(f"{path.name} is already at schema {storage.SCHEMA_VERSION}")
        return 0
    first = f"; first learner #{res.learner_id} {args.learner.strip()}" if res.learner_id is not None else ""
    print(f"migrated {path.name} from schema {res.from_version} to {storage.SCHEMA_VERSION}{first}; rebuilt "
          f"{len(res.rebuilt)} table(s), created {len(res.created)}; backup {res.backup}")
    return 0


def cmd_supervisor(args: argparse.Namespace) -> int:
    from leafi.ops import supervisor

    try:
        return asyncio.run(supervisor.run(_settings()))
    except KeyboardInterrupt:
        return 130


def cmd_alert(args: argparse.Namespace) -> int:
    """keep.ps1's path (ADR-0016): queue a coded alert and/or deliver what is due, once."""
    from leafi.core.storage import Store

    settings = _settings()
    with Store(settings.db_path) as store:
        return _alert(args, settings, store)


def _alert(args: argparse.Namespace, settings: Settings, store) -> int:
    from leafi.core import alerts
    from leafi.devices.notifiers import NotifierDevice
    from leafi.ops.alerts import deliver, windows_toast

    if args.status:
        states = store.all("SELECT service, kills, gave_up, latch, updated_at FROM service_state ORDER BY service")
        if not states:
            print("supervisor: never ran")
        for st in states:
            if st["service"].startswith("check-"):
                continue
            print(f"{st['service']:<12} {st['latch']:<5} recoveries used {st['kills']}/3"
                  f"{'  GAVE UP (rearm: 🔁 or POST /rearm?service=' + st['service'] + ')' if st['gave_up'] else ''}"
                  f"  updated {st['updated_at']}")
        from leafi.ops import timing

        t, problems = timing.resolve(settings)
        enabled = [s.strip() for s in settings.supervise.split(",") if s.strip()]
        for d in timing.derived(t, enabled):
            print(f"  {d.service:<12} broken → first recovery within {d.first_recovery_s / 60:.1f} min, "
                  f"gives up within {d.give_up_s / 60:.1f} min (plus recovery run times)")
        if problems:
            print(f"timing settings conflict ({', '.join(problems)}): defaults in use; see python -m leafi timing")
        failing = [st["service"][6:] for st in states if st["service"].startswith("check-") and st["latch"] == "down"]
        checked = [st for st in states if st["service"].startswith("check-")]
        if checked:
            print(f"configuration checks: {len(checked) - len(failing)}/{len(checked)} ok"
                  f"{'; failing: ' + ', '.join(failing) if failing else ''}")
        rows = store.all("SELECT id, key, state, reason, created_at, attempts FROM alert_outbox "
                         "WHERE sent_at IS NULL ORDER BY id")
        print(f"unsent alerts: {len(rows)}")
        for r in rows:
            print(f"  #{r['id']} {r['created_at']} {r['key']}/{r['state']}/{r['reason']} (attempts {r['attempts']})")
    if args.insert:
        alerts.insert(store, *args.insert)
    if args.drain:
        notifier = NotifierDevice(options={"telegram_bot_token": settings.telegram_bot_token,
                                           "telegram_chat_id": settings.telegram_chat_id}, settings=settings)
        print(f"delivered {asyncio.run(deliver(store, windows_toast, notifier))}")
    return 0


def cmd_timing(args: argparse.Namespace) -> int:
    """The supervision timings in use after validation (ADR-0016); `--env` prints KEY=value for the scripts."""
    from leafi.ops import timing

    settings = Settings()  # no netguard: the scripts call this before anything else and it reads nothing remote
    t, problems = timing.resolve(settings)
    if args.env:
        print("\n".join(timing.as_env(t)))
        return 0
    enabled = [s.strip() for s in settings.supervise.split(",") if s.strip()]
    print(f"poll {t.poll_s:g} s, {t.bad_streak} bad polls → recovery, at most {t.max_recoveries} per outage, "
          f"healthy after {t.healthy_s:g} s; worst poll {timing.worst_poll_s(enabled):g} s")
    print(f"resume: gap > {t.resume_gap_s:g} s, grace {t.resume_grace_s:g} s; checks every {t.checks_every_s:g} s")
    print("grace: " + ", ".join(f"{k}={v:g}" for k, v in t.grace.items()))
    print("scripts: " + "; ".join(timing.as_env(t)))
    for d in timing.derived(t, enabled):
        print(f"  {d.service:<12} first recovery within {d.first_recovery_s / 60:.1f} min, gives up within "
              f"{d.give_up_s / 60:.1f} min")
    hb = timing.gatus_heartbeat_s(Path(settings.devices_file).parent / "gatus" / "config.yaml")
    if not timing.heartbeat_ok(hb, t, enabled):
        print(f"dashboard: the leafi/supervisor heartbeat ({hb} s) must exceed one poll "
              f"({t.poll_s + timing.worst_poll_s(enabled):g} s); edit config/gatus/config.yaml")
    print(f"Healthchecks.io: set the check's period above {t.poll_s + timing.worst_poll_s(enabled):g} s")
    if problems:
        print("CONFLICT: " + ", ".join(problems) + " — the settings involved use their defaults (ADR-0016)")
        return 1
    return 0


def cmd_checks(args: argparse.Namespace) -> int:
    """Run every configuration check once and print the result; no alert is raised (ADR-0016)."""
    from leafi.ops import checks

    settings = _settings()

    async def run_all() -> list[tuple[str, str]]:
        out = []
        for c in checks.build(settings):
            try:
                out.append((c.name, "ok" if await c.run() else "FAIL"))
            except Exception as e:  # noqa: BLE001 - report, do not stop
                out.append((c.name, f"could not run ({type(e).__name__})"))
        return out

    results = asyncio.run(run_all())
    for name, verdict in results:
        print(f"{name:<20}{verdict}")
    return 0 if all(v == "ok" for _, v in results) else 1


def cmd_setup(args: argparse.Namespace) -> int:
    """The household's privacy setup in order (ADR-0018 §3, §5): learners' schools, protected terms, the Anki
    notice. It only prints; each step is its own confirmed command."""
    from leafi.core.storage import Store
    from leafi.privacy import settings as privacy
    from leafi.study.anki import NOTICE

    settings = _settings()
    with Store(settings.db_path) as store:
        missing = privacy.missing_school(store)
        n_terms = len(privacy.terms(store))
    print("1. every learner's school (a learner without one keeps their own words off the cloud):")
    if missing:
        for _, n in missing:
            print(f"   python -m leafi privacy learner \"{n}\" school, then the school's name in quotes "
                  "(or none), then --yes")
    else:
        print("   all answered (python -m leafi privacy schools)")
    print(f"2. other names to protect (relatives, friends, places): {n_terms} now; add one with "
          "python -m leafi privacy terms add, then the name in quotes, then --kind name, school or other, then --yes")
    print(f"3. Anki: {NOTICE}")
    return 0


def cmd_env_example(args: argparse.Namespace) -> int:
    from leafi import envedit

    m, mismatches = envedit.load()
    if m is None or mismatches:
        print("config/env-schema.json disagrees with the code; fix these first:")
        print("\n".join(f"  {x}" for x in mismatches))
        return 1
    (envedit.ROOT / ".env.example").write_bytes(envedit.env_example(m))
    print(".env.example regenerated from config/env-schema.json")
    return 0


def _file_log(path: Path) -> None:
    """WARNING and above from every command, rotating 5 × 1 MB (ADR-0016), so faults outlive the console."""
    from logging.handlers import RotatingFileHandler

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5, encoding="utf-8", delay=True)
    except OSError:
        return
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter("%(asctime)s %(process)d %(name)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(handler)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="leafi", description="Leafi household agent")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices", help="print the parsed devices.yml and the Hub").set_defaults(fn=cmd_devices)
    d = sub.add_parser("doctor", help="backend and model status")
    d.add_argument("--download", action="store_true", help="fetch the missing models under MODELS_DIR")
    d.add_argument("--only", nargs="*",
                   choices=["asr", "vad", "tts en", "pronunciation", "ocr", "wordlists", "names", "yle",
                            "speechocean762"],
                   help="restrict --download to these; the YLE PDF and evaluation data (speechocean762) only when "
                        "named")
    d.set_defaults(fn=cmd_doctor)
    s = sub.add_parser("study", help="run a reading session")
    s.add_argument("--text", action="store_true", help="typed input on the console, no hardware")
    s.add_argument("--book", help="book title (else identified from the camera or asked)")
    s.add_argument("--page-text", type=Path, help="text file for the page (manual, fully verified revision)")
    s.add_argument("--page", type=int, help="printed page number for --page-text")
    s.add_argument("--mock", action="store_true", help="mock services and no camera (safe in the home)")
    s.add_argument("--voice-policy", choices=["all", "primary", "none"])
    s.add_argument("--mouth", action="append", metavar="DEVICE",
                   help="speak only through this device (repeatable), e.g. --mouth pc keeps the camera silent")
    s.add_argument("--learner", metavar="NAME",
                   help="who is reading (a new name is enrolled); optional while only one learner is enrolled")
    s.set_defaults(fn=cmd_study)
    e = sub.add_parser("export", help="JSON summary of a session (no audio, no learner free text)")
    e.add_argument("--session", type=int, required=True)
    e.set_defaults(fn=cmd_export)
    f = sub.add_parser("forget", help="parent deletion (ADR-0010 §9, ADR-0018 §1)")
    g = f.add_mutually_exclusive_group(required=True)
    g.add_argument("--session", type=int)
    g.add_argument("--book", type=int)
    g.add_argument("--learner", type=int, metavar="ID", help="a learner and everything derived from them")
    f.add_argument("--yes", action="store_true", help="confirm --learner (without it, only print what would go)")
    f.add_argument("--delete-anki-deck", action="store_true", help="with --learner: also delete their Anki deck")
    f.set_defaults(fn=cmd_forget)
    pv = sub.add_parser("privacy", help="learners' privacy answers (ADR-0018 §3, §5)")
    pvs = pv.add_subparsers(dest="what", required=True)
    pvs.add_parser("schools", help="every learner's school answer, to confirm")
    pt = pvs.add_parser("terms", help="the household's protected names, schools and other terms")
    pt.add_argument("action", nargs="?", choices=["list", "add", "remove", "import"],
                    help="list (default) | add TERM | remove TERM | import (the retired REDACT_TERMS)")
    pt.add_argument("term", nargs="?")
    pt.add_argument("--kind", choices=["name", "school", "other"], default="name")
    pt.add_argument("--yes", action="store_true", help="confirm (without it, only print what would change)")
    pl = pvs.add_parser("learner", help="set a learner's school: a name, or none")
    pl.add_argument("name")
    pl.add_argument("key", choices=["school"])
    pl.add_argument("value", help='the school\'s name, or "none"')
    pl.add_argument("--yes", action="store_true", help="confirm (without it, only print what would change)")
    pv.set_defaults(fn=cmd_privacy)
    b = sub.add_parser("backup", help="consistent copy of data/leafi.db (SQLite backup API, ADR-0019)")
    b.add_argument("--to", type=Path, help="destination file (default data/backups/leafi-<UTC time>.db)")
    b.add_argument("--prune", action="store_true",
                   help="instead of backing up, delete all but the newest --keep backups in data/backups")
    b.add_argument("--keep", type=int, help="backups --prune keeps (default storage.BACKUPS_KEPT, 3)")
    b.set_defaults(fn=cmd_backup)
    m = sub.add_parser("migrate", help="bring data/leafi.db to the latest schema; every other Leafi process "
                       "closed (ADR-0018 §7.2)")
    m.add_argument("--learner", metavar="NAME", help="the first learner, who owns the sessions already recorded")
    m.add_argument("--restore", type=Path, metavar="BACKUP", help="put a backup back in place instead")
    m.set_defaults(fn=cmd_migrate)
    sub.add_parser("supervisor", help="keep every Leafi service running, recover the ones that stop answering, "
                   "send alerts (ADR-0016)").set_defaults(fn=cmd_supervisor)
    tm = sub.add_parser("timing", help="supervision timings after validation, derived times, conflicts (ADR-0016)")
    tm.add_argument("--env", action="store_true", help="KEY=value lines for keep.ps1 / install-tasks.ps1")
    tm.set_defaults(fn=cmd_timing)
    sub.add_parser("checks", help="run the configuration checks once and print them; no alerts (ADR-0016)"
                   ).set_defaults(fn=cmd_checks)
    a = sub.add_parser("alert", help="queue a coded alert and/or deliver due alerts once (ADR-0016)")
    a.add_argument("--insert", nargs=3, metavar=("KEY", "STATE", "REASON"))
    a.add_argument("--drain", action="store_true")
    a.add_argument("--status", action="store_true", help="restart budget and unsent alerts (health.ps1)")
    a.set_defaults(fn=cmd_alert)
    st = sub.add_parser("setup", help="local setup")
    st.set_defaults(fn=cmd_setup)
    sub.add_parser("env-example", help="regenerate .env.example from config/env-schema.json"
                   ).set_defaults(fn=cmd_env_example)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    _file_log(Settings().data_dir / "logs" / "leafi.log")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from leafi.core.storage import DatabaseInUse, SchemaError

    try:
        return int(args.fn(args) or 0)
    except (SchemaError, DatabaseInUse) as e:  # a file to migrate, or a migration running: say what to do
        print(f"Leafi: {e}")
        return 2
