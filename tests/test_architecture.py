"""Import-graph rules from docs/architecture/overview.md (every import, including lazy ones inside functions)."""

from __future__ import annotations

import ast
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
        if ".send(" in f.read_text(encoding="utf-8") and "notif" in f.read_text(encoding="utf-8").lower():
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
