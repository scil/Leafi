"""Canonical `.env` editing and the locked writer (design: docs/plans/active/2026-10-21-env-settings-page.md §1-§2).

Storage is never mocked: real files in tmp_path. Only `ReplaceFileW` is faked, and each fake first produces the
documented on-disk state for real.
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from dotenv import dotenv_values

from leafi.core import envfile
from leafi.core.envfile import (ABSENT, Committed, Conflict, EnvFile, NotCanonical, Op, RecoveryRequired, RolledBack,
                                Unstorable, health, read_state, update_env)
from tests.test_architecture import ROOT

EXAMPLE = ROOT / ".env.example"


def parse(text: str) -> EnvFile:
    return EnvFile.parse(text.encode("utf-8"))


def dotenv_text(tmp_path, raw: bytes) -> dict:
    f = tmp_path / "probe.env"
    f.write_bytes(raw)
    return dotenv_values(f, encoding="utf-8")


# ---------------------------------------------------------------- canonical form


@pytest.mark.parametrize("text", ["A=1\nB='x y'\n", "A=1\r\nB=2\r\n", "# c\n\nA=1   # note\n", "A=1", ""])
def test_no_op_round_trip_is_byte_identical(text):
    f = parse(text)
    assert f.problems() == []
    assert f.render() == text.encode()
    assert f.apply({}).render() == text.encode()


def test_env_example_is_canonical_and_reads_as_the_grammar_says(tmp_path):
    raw = EXAMPLE.read_bytes()
    f = EnvFile.parse(raw)
    assert f.problems() == []
    assert f.apply({}).render() == raw
    assert dotenv_text(tmp_path, raw) == f.values()
    for key in ("XIAOMI_USERID", "XIAOMI_DID", "BARK_URL", "CHILD_FACE_LABEL", "REDACT_TERMS"):
        assert f.values()[key] == "", key  # `KEY=   # help` used to read as the help text


@pytest.mark.parametrize("text,rule", [
    ("\ufeffA=1\n", "BOM"),
    ("A=1\r\nB=2\n", "mixed newline"),
    (" A=1\n", "leading space"),
    ("export A=1\n", "export"),
    ('A="x$y"\n', "double quotes"),
    ('A="x\\\\y"\n', "double quotes"),
    ("A='a\\\\b'\n", "backslash"),
    ("A='a\\'\n", "backslash"),
    ("A: v\n", "':' assignment"),
    ("A=${X}\n", "interpolation"),
    ("A='${X}'\n", "interpolation"),
    ('A="${X}"\n', "interpolation"),
    ("a=1\n", "lower-case"),
    ("A=1\nA=2\n", "duplicate of line 1"),
    ("A=   # note\n", "empty value followed by a comment"),
    ("A=x # $$\n", "'$'"),
    ("A=x y\n", "single quotes"),
])
def test_non_canonical_lines_are_reported_and_block_apply(text, rule):
    f = EnvFile.parse(text.encode("utf-8"))
    problems = f.problems()
    assert problems and any(rule in p.rule for p in problems), problems
    with pytest.raises(NotCanonical):
        f.apply({"B": Op("set", "1")})


def test_a_multi_line_value_never_reports_its_inner_lines_as_keys():
    f = parse("CAM_PASSWORD='first\nSecretCanary\nSecret=Canary2\nlast'\nA=1\n")
    problems = f.problems()
    assert [p.line for p in problems] == [1, 2, 3, 4]
    assert all(p.key in (None, "CAM_PASSWORD") for p in problems)
    assert "Canary" not in repr(problems)


def test_an_escaped_quote_does_not_end_the_value_and_no_later_line_names_a_key():
    f = parse("CAM_PASSWORD='first\nescaped\\'\nSecretCanary: hidden\nlast'\nOther: x\n")
    assert "Canary" not in repr(f.problems())
    assert all(p.key in (None, "CAM_PASSWORD") for p in f.problems())


@pytest.mark.parametrize("text", [
    "'CAM_PASSWORD'='first\nSecretCanary: hidden\nlast'\n",
    "CAM_PASSWORD = \"first\nSecretCanary=hidden\nlast\"\n",
    "x 'unbalanced\nSecretCanary: hidden\n",
    "CAM_PASSWORD='x\\\\'\nSecretCanary: hidden'\n",
    'CAM_PASSWORD="x\\\\\\\\"\nSecretCanary: hidden"\n',
])
def test_no_line_after_an_unbalanced_quote_names_a_key(text):
    assert "Canary" not in repr(parse(text).problems())


def test_a_conflict_survives_a_failing_cleanup(tmp_path, monkeypatch):
    env = tmp_path / ".env"

    def appears(src, dst):
        dst.write_bytes(b"B=2\n")
        raise FileExistsError(dst)

    real_unlink = Path.unlink

    def sticky(self, missing_ok=False):
        if self.suffix == ".tmp":
            raise PermissionError(self)
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(envfile, "_link", appears)
    monkeypatch.setattr(Path, "unlink", sticky)
    out = update_env(env, ABSENT, transform({"A": Op("set", "1")}), tmp_path / "data")
    monkeypatch.setattr(Path, "unlink", real_unlink)
    assert isinstance(out, Conflict)


@pytest.mark.parametrize("value", ["a%b", "a=b", "x@y:z", "p$q", "p #q", "#", "a+", "名字,学校", "", "two words",
                                   "Ann O'Brien,Some School #1", "it's"])
def test_written_values_read_back_identically(tmp_path, value):
    f = parse("# head\nA=old   # keep me\nB=1\n").apply({"A": Op("set", value), "C": Op("set", value)})
    assert f.problems() == []
    back = dotenv_text(tmp_path, f.render())
    assert back["A"] == value and back["C"] == value and back["B"] == "1"
    assert f.values()["A"] == value


@pytest.mark.parametrize("value", ["it's \"q\"", "it's $5", "a\\b", "x${Y}", "a\nb", "a\x00b", "tab\there"])
def test_unstorable_values_are_rejected(value):
    with pytest.raises(Unstorable):
        parse("A=1\n").apply({"A": Op("set", value)})


def test_ops_change_only_their_own_lines():
    before = "# ===== S =====\nA=1   # help\n# B=2\nC=3\n"
    f = parse(before)
    after = f.apply({"A": Op("set", "9"), "B": Op("set", "5"), "C": Op("unset")}).render().decode()
    assert after == "# ===== S =====\nA=9   # help\n# B=2\nB=5\n# C=3\n"


def test_empty_keeps_the_comment_with_quotes_and_reads_empty(tmp_path):
    f = parse("A=x   # note\nB=y\n").apply({"A": Op("empty"), "B": Op("empty")})
    assert f.render().decode() == "A=''   # note\nB=\n"
    assert dotenv_text(tmp_path, f.render()) == {"A": "", "B": ""}


def test_placement_uses_the_anchor_section_then_an_added_section():
    text = "# ===== One =====\nA=1\n\n# ===== Two =====\nB=2\n"
    f = parse(text).apply({"N": Op("set", "x")}, anchors={"N": "# ===== One ====="})
    assert f.render().decode() == "# ===== One =====\nA=1\nN=x\n\n# ===== Two =====\nB=2\n"
    g = parse(text).apply({"M": Op("set", "y")})
    assert g.render().decode().endswith("B=2\n\n# ===== Added by the settings page =====\nM=y\n")
    h = g.apply({"Z": Op("set", "z")})
    assert h.render().decode().count("Added by the settings page") == 1
    assert h.render().decode().endswith("M=y\nZ=z\n")


def test_crlf_files_stay_crlf():
    f = parse("A=1\r\nB=2\r\n").apply({"A": Op("set", "3"), "C": Op("set", "4")})
    assert b"\n" not in f.render().replace(b"\r\n", b"")


@pytest.mark.skipif(not shutil.which("docker"), reason="docker not installed")
def test_compose_reads_canonical_values_like_python_dotenv(tmp_path):
    values = {"A": "a%b", "B": "x@y:z", "C": "p$q", "D": "p #q", "E": "#", "F": "", "G": "a+", "H": "two words",
              "I": "Ann O'Brien,Some School #1", "J": "it's"}
    f = parse("").apply({k: Op("set", v) for k, v in values.items()})
    env = tmp_path / "x.env"
    env.write_bytes(f.render())
    (tmp_path / "compose.yml").write_text("services:\n  s:\n    image: scratch\n", encoding="utf-8")
    try:
        out = subprocess.run(["docker", "compose", "--env-file", str(env), "-f", str(tmp_path / "compose.yml"),
                              "config", "--environment"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("docker compose unavailable")
    if out.returncode != 0:
        pytest.skip("docker compose config --environment unavailable")
    seen = dict(line.split("=", 1) for line in out.stdout.splitlines() if "=" in line)
    for k, v in values.items():
        assert seen.get(k) == v, k
    assert dotenv_text(tmp_path, f.render()) == values


# ---------------------------------------------------------------- the writer


def transform(ops):
    return lambda old: EnvFile.parse(old).apply(ops).render()


def test_update_commits_backs_up_and_detects_conflicts(tmp_path):
    env, data = tmp_path / ".env", tmp_path / "data"
    env.write_bytes(b"A=1\n")
    _, digest = read_state(env)
    out = update_env(env, digest, transform({"A": Op("set", "2")}), data)
    assert isinstance(out, Committed) and env.read_bytes() == b"A=2\n"
    assert [p.read_bytes() for p in (data / "env-backup").glob("*.bak")] == [b"A=1\n"]
    assert isinstance(update_env(env, digest, transform({"A": Op("set", "3")}), data), Conflict)
    assert env.read_bytes() == b"A=2\n"
    assert not list(tmp_path.glob(".env.*.tmp")) and not list(tmp_path.glob(".env.*.side"))


def test_a_failing_transform_writes_nothing(tmp_path):
    env = tmp_path / ".env"
    env.write_bytes(b"A=1\n")

    def boom(old):
        raise ValueError("invalid")

    with pytest.raises(ValueError):
        update_env(env, read_state(env)[1], boom, tmp_path / "data")
    assert env.read_bytes() == b"A=1\n"
    assert not list(tmp_path.glob(".env.*.tmp"))


def test_backups_rotate_to_five_even_within_one_millisecond(tmp_path):
    env, data = tmp_path / ".env", tmp_path / "data"
    env.write_bytes(b"A=0\n")
    for i in range(1, 9):
        assert isinstance(update_env(env, read_state(env)[1], transform({"A": Op("set", str(i))}), data), Committed)
    baks = sorted((data / "env-backup").glob("*.bak"), key=lambda p: int(p.name.split(".")[2]))
    assert [p.read_bytes() for p in baks] == [f"A={i}\n".encode() for i in range(3, 8)]


def test_first_creation_and_its_conflict(tmp_path, monkeypatch):
    env, data = tmp_path / ".env", tmp_path / "data"
    assert isinstance(update_env(env, ABSENT, transform({"A": Op("set", "1")}), data), Committed)
    assert env.read_bytes() == b"\n# ===== Added by the settings page =====\nA=1\n" or env.read_bytes().endswith(b"A=1\n")
    assert not (data / "env-backup").exists() or not list((data / "env-backup").glob("*.bak"))

    other = tmp_path / "other" / ".env"
    other.parent.mkdir()

    def appears(src, dst):
        dst.write_bytes(b"B=2\n")
        raise FileExistsError(dst)

    monkeypatch.setattr(envfile, "_link", appears)
    assert isinstance(update_env(other, ABSENT, transform({"A": Op("set", "1")}), data), Conflict)
    assert other.read_bytes() == b"B=2\n"

    third = tmp_path / "third" / ".env"
    third.parent.mkdir()

    def fails(src, dst):
        raise PermissionError(dst)

    monkeypatch.setattr(envfile, "_link", fails)
    out = update_env(third, ABSENT, transform({"A": Op("set", "1")}), data)
    assert isinstance(out, RolledBack) and not third.exists()


def test_replace_outcomes_are_classified_by_what_env_holds(tmp_path, monkeypatch):
    env, data = tmp_path / ".env", tmp_path / "data"

    def run(fake):
        env.write_bytes(b"A=1\n")
        monkeypatch.setattr(envfile, "_replace_file", fake)
        return update_env(env, read_state(env)[1], transform({"A": Op("set", "2")}), data)

    def moved_aside(path, tmp, side):  # ERROR_UNABLE_TO_MOVE_REPLACEMENT_2: .env is now at `side`
        path.rename(side)
        return 1177

    out = run(moved_aside)
    assert isinstance(out, RolledBack) and env.read_bytes() == b"A=1\n"

    real_replace = envfile.os.replace

    def no_restore(src, dst):
        if str(src).endswith(".side"):
            raise PermissionError(src)
        return real_replace(src, dst)

    monkeypatch.setattr(envfile.os, "replace", no_restore)
    out = run(moved_aside)
    monkeypatch.setattr(envfile.os, "replace", real_replace)
    assert isinstance(out, RecoveryRequired) and not env.exists()
    assert Path(out.paths["side"]).read_bytes() == b"A=1\n"
    assert Path(out.paths["tmp"]).read_bytes() == b"A=2\n"
    assert Path(out.paths["backup"]).read_bytes() == b"A=1\n"
    assert Path(out.paths["marker"]).exists()
    assert any("recovery marker" in h for h in health(env, data))
    Path(out.paths["side"]).rename(env)
    Path(out.paths["tmp"]).unlink()
    Path(out.paths["marker"]).unlink()

    def unchanged(path, tmp, side):  # ERROR_UNABLE_TO_MOVE_REPLACEMENT: both keep their names
        return 1176

    out = run(unchanged)
    assert isinstance(out, RolledBack) and env.read_bytes() == b"A=1\n"
    assert not list(tmp_path.glob(".env.*.tmp"))


def test_cleanup_failure_after_a_successful_install_is_a_warning(tmp_path, monkeypatch):
    env, data = tmp_path / ".env", tmp_path / "data"
    env.write_bytes(b"A=1\n")

    def replaced_leaving_side(path, tmp, side):
        side.write_bytes(path.read_bytes())
        envfile.os.replace(tmp, path)
        return 0

    real_unlink = Path.unlink

    def sticky(self, missing_ok=False):
        if self.name.endswith(".side"):
            raise PermissionError(self)
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(envfile, "_replace_file", replaced_leaving_side)
    monkeypatch.setattr(Path, "unlink", sticky)
    out = update_env(env, read_state(env)[1], transform({"A": Op("set", "2")}), data)
    monkeypatch.setattr(Path, "unlink", real_unlink)
    assert isinstance(out, Committed) and env.read_bytes() == b"A=2\n"
    assert out.warnings and ".side" in out.warnings[0]


def test_an_unreadable_result_needs_recovery_and_keeps_every_file(tmp_path, monkeypatch):
    env, data = tmp_path / ".env", tmp_path / "data"
    env.write_bytes(b"A=1\n")
    state = {"installed": False}

    def replaced(path, tmp, side):
        side.write_bytes(path.read_bytes())
        envfile.os.replace(tmp, path)
        state["installed"] = True
        return 0

    real_read = Path.read_bytes

    def read(self):
        if state["installed"] and self == env:
            raise PermissionError(self)
        return real_read(self)

    monkeypatch.setattr(envfile, "_replace_file", replaced)
    monkeypatch.setattr(Path, "read_bytes", read)
    out = update_env(env, read_state(env)[1], transform({"A": Op("set", "2")}), data)
    monkeypatch.setattr(Path, "read_bytes", real_read)
    assert isinstance(out, RecoveryRequired)
    assert Path(out.paths["side"]).exists() and Path(out.paths["marker"]).exists()


def test_a_replace_that_raises_is_classified_not_propagated(tmp_path, monkeypatch):
    env, data = tmp_path / ".env", tmp_path / "data"
    env.write_bytes(b"A=1\n")

    def raises(path, tmp, side):
        raise PermissionError(path)

    monkeypatch.setattr(envfile, "_replace_file", raises)
    out = update_env(env, read_state(env)[1], transform({"A": Op("set", "2")}), data)
    assert isinstance(out, RolledBack) and env.read_bytes() == b"A=1\n"
    assert not list(tmp_path.glob(".env.*.tmp"))


HOLDER = """
import sys, time
from leafi.core.envfile import _FileLock
from pathlib import Path
with _FileLock(Path(sys.argv[1])):
    print("held", flush=True)
    time.sleep(float(sys.argv[2]))
"""


def test_the_os_lock_serialises_processes_and_dies_with_its_holder(tmp_path):
    lock = tmp_path / ".env.lock"
    p = subprocess.Popen([sys.executable, "-c", HOLDER, str(lock), "30"], stdout=subprocess.PIPE, text=True,
                         cwd=ROOT)
    try:
        assert p.stdout.readline().strip() == "held"
        with pytest.raises(TimeoutError):
            with envfile._FileLock(lock, wait_s=0.3):
                pass
        p.kill()
        p.wait(10)
        with envfile._FileLock(lock, wait_s=5):
            pass
    finally:
        p.kill()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACLs")
def test_an_explicit_ace_survives_a_save_and_reaches_the_backup(tmp_path):
    env, data = tmp_path / ".env", tmp_path / "data"
    env.write_bytes(b"A=1\n")
    subprocess.run(["icacls", str(env), "/grant", "*S-1-5-32-545:(R)"], check=True, capture_output=True)

    def aces(p):
        return subprocess.run(["icacls", str(p)], capture_output=True, text=True).stdout.splitlines()[0]

    want = aces(env).split(" ", 1)[1].strip()
    assert isinstance(update_env(env, read_state(env)[1], transform({"A": Op("set", "2")}), data), Committed)
    assert env.read_bytes() == b"A=2\n"
    assert "S-1-5-32-545" in aces(env) or "Users" in aces(env)
    bak = next((data / "env-backup").glob("*.bak"))
    assert aces(bak).split(" ", 1)[1].strip() == want


def test_health(tmp_path):
    env, data = tmp_path / ".env", tmp_path / "data"
    assert health(env, data) == [".env is missing"]
    env.write_bytes(b' A=1\n')
    assert health(env, data) == [".env is not in canonical form"]
    env.write_bytes(b"A=1\n")
    assert health(env, data) == []
    data.mkdir()
    (data / "env-recovery.json").write_text("{}")
    assert health(env, data) == ["recovery marker env-recovery.json"]
    (data / "env-recovery.json").unlink()
    side = tmp_path / ".env.ab12.side"
    side.write_bytes(b"A=0\n")
    old = time.time() - 120
    import os

    os.utime(side, (old, old))
    assert health(env, data) == ["leftover .env.ab12.side"]
    fresh = tmp_path / ".env.cd34.tmp"
    fresh.write_bytes(b"")
    assert health(env, data) == ["leftover .env.ab12.side"]  # a 10-second-old temp is a save in progress
    side.unlink()
    assert health(env, data) == []
