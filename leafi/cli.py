"""`python -m leafi <command>`: devices, doctor, study, export, forget, setup."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from leafi.core.config import Settings


def _settings() -> Settings:
    s = Settings()
    if s.leafi_no_network:
        from leafi.core import netguard

        netguard.install()
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

    store = Store(_settings().db_path)
    print(json.dumps(export_session(store, args.session), ensure_ascii=False, indent=2))
    return 0


def cmd_forget(args: argparse.Namespace) -> int:
    from leafi.core.storage import Store
    from leafi.study.records import forget_book, forget_session

    store = Store(_settings().db_path)
    if args.session is not None:
        forget_session(store, args.session)
        print(f"forgot session {args.session}")
    if args.book is not None:
        forget_book(store, args.book)
        print(f"forgot book {args.book} (archived)")
    return 0


def cmd_supervisor(args: argparse.Namespace) -> int:
    from leafi.ops import supervisor

    try:
        return asyncio.run(supervisor.run(_settings()))
    except KeyboardInterrupt:
        return 130


def cmd_alert(args: argparse.Namespace) -> int:
    """keep.ps1's path (ADR-0016): queue a coded alert and/or deliver what is due, once."""
    from leafi.core import alerts
    from leafi.core.storage import Store
    from leafi.devices.notifiers import NotifierDevice
    from leafi.ops.alerts import deliver, windows_toast

    settings = _settings()
    store = Store(settings.db_path)
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
                                           "telegram_chat_id": settings.telegram_chat_id})
        print(f"delivered {asyncio.run(deliver(store, windows_toast, notifier))}")
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
        print(f"{name:<18}{verdict}")
    return 0 if all(v == "ok" for _, v in results) else 1


def cmd_setup(args: argparse.Namespace) -> int:
    env = Path(".env")
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    lines = [ln for ln in text.splitlines() if not ln.startswith("REDACT_TERMS=")]
    lines.append(f"REDACT_TERMS={args.redact}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("REDACT_TERMS updated in .env")
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
    d.add_argument("--only", nargs="*", choices=["asr", "vad", "tts en", "pronunciation", "ocr"],
                   help="restrict --download to these services")
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
    s.set_defaults(fn=cmd_study)
    e = sub.add_parser("export", help="JSON summary of a session (no audio, no learner free text)")
    e.add_argument("--session", type=int, required=True)
    e.set_defaults(fn=cmd_export)
    f = sub.add_parser("forget", help="parent deletion (ADR-0010 §9)")
    g = f.add_mutually_exclusive_group(required=True)
    g.add_argument("--session", type=int)
    g.add_argument("--book", type=int)
    f.set_defaults(fn=cmd_forget)
    sub.add_parser("supervisor", help="keep every Leafi service running, recover the ones that stop answering, "
                   "send alerts (ADR-0016)").set_defaults(fn=cmd_supervisor)
    sub.add_parser("checks", help="run the configuration checks once and print them; no alerts (ADR-0016)"
                   ).set_defaults(fn=cmd_checks)
    a = sub.add_parser("alert", help="queue a coded alert and/or deliver due alerts once (ADR-0016)")
    a.add_argument("--insert", nargs=3, metavar=("KEY", "STATE", "REASON"))
    a.add_argument("--drain", action="store_true")
    a.add_argument("--status", action="store_true", help="restart budget and unsent alerts (health.ps1)")
    a.set_defaults(fn=cmd_alert)
    st = sub.add_parser("setup", help="local setup")
    st.add_argument("--redact", required=True, help="comma-separated terms removed from cloud payloads")
    st.set_defaults(fn=cmd_setup)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    _file_log(Settings().data_dir / "logs" / "leafi.log")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return int(args.fn(args) or 0)
