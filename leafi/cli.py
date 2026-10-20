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
    print(doctor.report(settings))
    if args.download:
        print("--download: not implemented yet; run the commands printed above (plan Decision log).")
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


def cmd_setup(args: argparse.Namespace) -> int:
    env = Path(".env")
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    lines = [ln for ln in text.splitlines() if not ln.startswith("REDACT_TERMS=")]
    lines.append(f"REDACT_TERMS={args.redact}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("REDACT_TERMS updated in .env")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="leafi", description="Leafi household agent")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices", help="print the parsed devices.yml and the Hub").set_defaults(fn=cmd_devices)
    d = sub.add_parser("doctor", help="backend and model status")
    d.add_argument("--download", action="store_true")
    d.set_defaults(fn=cmd_doctor)
    s = sub.add_parser("study", help="run a reading session")
    s.add_argument("--text", action="store_true", help="typed input on the console, no hardware")
    s.add_argument("--book", help="book title (else identified from the camera or asked)")
    s.add_argument("--page-text", type=Path, help="text file for the page (manual, fully verified revision)")
    s.add_argument("--page", type=int, help="printed page number for --page-text")
    s.add_argument("--mock", action="store_true", help="mock services and no camera (safe in the home)")
    s.add_argument("--voice-policy", choices=["all", "primary", "none"])
    s.set_defaults(fn=cmd_study)
    e = sub.add_parser("export", help="JSON summary of a session (no audio, no learner free text)")
    e.add_argument("--session", type=int, required=True)
    e.set_defaults(fn=cmd_export)
    f = sub.add_parser("forget", help="parent deletion (ADR-0010 §9)")
    g = f.add_mutually_exclusive_group(required=True)
    g.add_argument("--session", type=int)
    g.add_argument("--book", type=int)
    f.set_defaults(fn=cmd_forget)
    st = sub.add_parser("setup", help="local setup")
    st.add_argument("--redact", required=True, help="comma-separated terms removed from cloud payloads")
    st.set_defaults(fn=cmd_setup)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return int(args.fn(args) or 0)
