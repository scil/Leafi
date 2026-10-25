"""Import-graph rules from docs/architecture/overview.md (every import, including lazy ones inside functions)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEAFI = ROOT / "leafi"
SERVICE_PACKAGES = {"asr", "tts", "ocr", "pronunciation", "brain", "vision", "catalog"}


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mod = _module_name(path)
    pkg = mod if path.name == "__init__.py" else mod.rsplit(".", 1)[0]
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg.split(".")
                base = base[: len(base) - (node.level - 1)]
                name = ".".join(base + ([node.module] if node.module else []))
            else:
                name = node.module or ""
            out.append(name)
            out += [f"{name}.{a.name}" for a in node.names]
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "import_module":
            if node.args and isinstance(node.args[0], ast.Constant):
                out.append(str(node.args[0].value))
    return out


def _files(sub: str) -> list[Path]:
    return sorted((LEAFI / sub).rglob("*.py"))


def test_core_imports_nothing_from_other_rings():
    bad = []
    for f in _files("core"):
        for name in _imports(f):
            if name.startswith(("leafi.devices", "leafi.services", "leafi.study", "leafi.app", "leafi.cli",
                                "leafi.privacy", "leafi.bootstrap")):
                bad.append(f"{f.name}: {name}")
    assert bad == []


def test_privacy_and_bootstrap_import_only_core():
    """M5 design D1/D2: egress sits between core and every caller; bootstrap runs before any service exists."""
    bad = []
    for f in [*_files("privacy"), LEAFI / "bootstrap.py"]:
        for name in _imports(f):
            if name.startswith("leafi.") and not name.startswith(("leafi.core", "leafi.privacy")):
                bad.append(f"{f.name}: {name}")
    assert bad == []


def test_devices_import_only_core():
    bad = []
    for f in _files("devices"):
        for name in _imports(f):
            if name.startswith(("leafi.services", "leafi.study", "leafi.app")):
                bad.append(f"{f.name}: {name}")
    assert bad == []


def test_tracks_never_import_adapters_or_backends():
    """study/ may import a service package (its Protocol + registry), never a backend module or a device."""
    bad = []
    for f in _files("study"):
        for name in _imports(f):
            if name.startswith("leafi.devices") or name.startswith("leafi.app"):
                bad.append(f"{f.name}: {name}")
            parts = name.split(".")
            if parts[:2] == ["leafi", "services"] and len(parts) >= 4 and parts[2] in SERVICE_PACKAGES:
                # leafi.services.<svc>.<x>: allowed only when <x> is a name exported by the package itself
                pkg_init = LEAFI / "services" / parts[2] / "__init__.py"
                backend_file = LEAFI / "services" / parts[2] / f"{parts[3]}.py"
                if backend_file.exists() or not pkg_init.exists():
                    bad.append(f"{f.name}: {name}")
    assert bad == []


def test_only_brain_claude_and_notifiers_import_anthropic_or_reach_the_internet():
    allowed_anthropic = {"leafi/services/brain/claude.py"}
    bad = []
    for f in LEAFI.rglob("*.py"):
        rel = f.relative_to(ROOT).as_posix()
        names = _imports(f)
        if any(n == "anthropic" or n.startswith("anthropic.") for n in names) and rel not in allowed_anthropic:
            bad.append(rel)
    assert bad == []


def test_ops_imports_only_core_and_devices():
    bad = []
    for f in _files("ops"):
        for name in _imports(f):
            if name.startswith(("leafi.services", "leafi.study", "leafi.app")):
                bad.append(f"{f.name}: {name}")
    assert bad == []


def test_only_the_alert_deliverer_calls_notifier_send():
    """ADR-0016: every operational alert is a catalog sentence sent by `ops/alerts.py::deliver`."""
    bad = []
    for f in LEAFI.rglob("*.py"):
        rel = f.relative_to(ROOT).as_posix()
        if rel in {"leafi/ops/alerts.py", "leafi/devices/notifiers.py"}:
            continue
        # an httpx client's `.send(request)` (egress) is not the notifier's `.send(text)`
        if re.search(r"\b(?:notifier|n|device)\w*\.send\(", f.read_text(encoding="utf-8")):
            bad.append(rel)
    assert bad == []


def test_envfile_is_stdlib_only_and_envedit_stays_in_the_outer_ring():
    import sys

    names = _imports(LEAFI / "core" / "envfile.py")
    assert all(n.split(".")[0] in sys.stdlib_module_names or n.startswith("__future__") for n in names), names
    bad = [f"{f.name}: {n}" for ring in ("core", "ops", "study") for f in _files(ring) for n in _imports(f)
           if n == "leafi.envedit" or n.startswith("leafi.envedit.")]
    assert bad == []


def test_no_environment_reads_outside_core_config():
    bad = []
    for f in LEAFI.rglob("*.py"):
        rel = f.relative_to(ROOT).as_posix()
        if rel == "leafi/core/config.py":
            continue
        text = f.read_text(encoding="utf-8")
        if "os.environ" in text or "os.getenv" in text:
            bad.append(rel)
    assert bad == []


# ADR-0021 E9 (M7 design D22 before it): a write of a learner- or session-owned row goes through `learner_store`'s
# fenced writers, which check the owning learner in the statement. The functions below are exempt; each says why.
_WRITE_EXEMPT = {
    "leafi/study/harness/guests.py:discard": "moves a discarded guest's rows to the permanent `anonymous` row",
}
# The UPDATEs that stay raw: status, timestamps, counters and ids only (ADR-0021 E9, X5, Y5). Any other column of
# an owned table — a text, a JSON text, `reading_sessions.learner_id` — goes through `update_named`.
MAINTENANCE_COLUMNS: dict[str, set[str]] = {
    "reading_sessions": {"ended_at", "post_done_at", "book_id",
                         "summary"},  # JSON of counts and enum strings by construction (`records.summary`)
    "activities": {"status", "ended_at", "cycle_id"},
    "review_answers": {"state", "sent_at", "acked_at"},
    "knowledge_items": {"status", "updated_at"},
    "anki_outbox": {"state", "attempts", "updated_at", "anki_note_id",
                    "card_ids",  # Anki card ids
                    "attempted_fields", "last_acked_fields",  # JSON of field hashes
                    "last_error"},  # an AnkiConnect error string
    "item_status_events": {"activity_id"},  # an id, set NULL by `forget --session` before its activities go
}
_INSERT = re.compile(r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\{\}|\w+)", re.IGNORECASE)
_UPDATE = re.compile(r"UPDATE\s+(\{\}|\w+)\s+SET\s+(.*?)(?:\s+WHERE\b|$)", re.IGNORECASE | re.DOTALL)


def _set_targets(clause: str) -> list[str]:
    """The columns a SET clause assigns: `name =` at parenthesis depth 0 (so `COALESCE(?, summary)` is not one)."""
    out, depth, flat = [], 0, []
    for ch in clause:
        depth += ch == "("
        depth -= ch == ")"
        flat.append(ch if depth == 0 else " ")
    for part in "".join(flat).split(","):
        m = re.match(r"\s*(\w+)\s*=", part)
        if m:
            out.append(m.group(1))
    return out


def _sql(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):  # an f-string: its placeholders read as "{}"
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    return None


def _owned_write_problems(rel: str, source: str, fenced: set[str]) -> list[str]:
    """Every write of an owned table in one module (functions and module- or class-level constants) that is not
    allowed outside `learner_store`: an INSERT (literal, dynamic or `store.insert`), an UPDATE assigning a column
    outside `MAINTENANCE_COLUMNS`, an UPDATE with a placeholder in the SET of an owned table, or an UPDATE whose
    table name is not a literal."""
    tree = ast.parse(source)
    owner: dict[int, str] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            for node in ast.walk(fn):
                owner.setdefault(id(node), fn.name)
    bad = []
    for node in ast.walk(tree):
        where = owner.get(id(node), "<module>")
        if f"{rel}:{where}" in _WRITE_EXEMPT:
            continue
        sql = _sql(node)
        if sql:
            m = _INSERT.search(sql)
            if m and (m.group(1) in fenced or m.group(1) == "{}"):
                bad.append(f"{rel}:{node.lineno} {where}: INSERT INTO {m.group(1)}")
            m = _UPDATE.search(sql)
            if m:
                table, clause = m.group(1), m.group(2)
                if table == "{}":
                    bad.append(f"{rel}:{node.lineno} {where}: UPDATE with a non-literal table name")
                elif table in fenced:
                    if "{}" in clause:
                        bad.append(f"{rel}:{node.lineno} {where}: UPDATE {table} SET with a placeholder")
                    extra = [c for c in _set_targets(clause) if c not in MAINTENANCE_COLUMNS.get(table, set())]
                    if extra:
                        bad.append(f"{rel}:{node.lineno} {where}: UPDATE {table} SET {', '.join(extra)}")
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "insert"
                and node.args and _sql(node.args[0]) in fenced):
            bad.append(f"{rel}:{node.lineno} {where}: store.insert({_sql(node.args[0])!r})")
    return bad


def test_every_write_of_an_owned_row_goes_through_the_fence():
    """ADR-0021 E9: INSERTs into `DIRECT_OWNED | SESSION_OWNED` tables, and UPDATEs of them beyond the maintenance
    allow-list, live in `leafi/core/learner_store.py`."""
    from leafi.core import learner_store as ls

    fenced = set(ls.DIRECT_OWNED) | set(ls.SESSION_OWNED)
    bad = []
    for f in LEAFI.rglob("*.py"):
        rel = f.relative_to(ROOT).as_posix()
        if rel in ("leafi/core/learner_store.py", "leafi/core/storage.py"):
            continue
        bad += _owned_write_problems(rel, f.read_text(encoding="utf-8"), fenced)
    assert sorted(set(bad)) == []


def test_the_fence_scanner_refuses_text_columns_and_dynamic_tables():
    from leafi.core import learner_store as ls

    fenced = set(ls.DIRECT_OWNED) | set(ls.SESSION_OWNED)
    refused = [
        'def f(s): s.execute("UPDATE encounters SET example=? WHERE id=?", (1, 2))',
        'def f(s): s.execute("UPDATE utterances SET words=? WHERE id=?", (1, 2))',
        'def f(s): s.execute("UPDATE book_notes SET characters=? WHERE id=?", (1, 2))',
        'def f(s): s.execute("UPDATE reading_sessions SET learner_id=? WHERE id=?", (1, 2))',
        'SQL = "UPDATE learner_notes SET text=? WHERE id=?"',  # a module-level constant
        'def f(s, t): s.execute(f"UPDATE {t} SET x=?", (1,))',
        'def f(s): s.execute("INSERT INTO brain_calls(session_id) VALUES(?)", (1,))',
    ]
    for src in refused:
        assert _owned_write_problems("x.py", src, fenced), src
    allowed = ['def f(s): s.execute("UPDATE activities SET status=?, ended_at=? WHERE id=?", (1, 2, 3))',
               'def f(s): s.execute("UPDATE reading_sessions SET post_done_at=COALESCE(ended_at, ?)", (1,))']
    for src in allowed:
        assert _owned_write_problems("x.py", src, fenced) == [], src
