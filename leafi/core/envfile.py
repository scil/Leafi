"""Lossless `.env` editing in canonical form, and the one locked writer (docs/plans/active/2026-10-21-env-settings-page.md).

A file is *canonical* when every line is blank, a column-0 comment, or `KEY=VALUE[ +#comment]` with a value that
python-dotenv, pydantic-settings and docker compose all read as the same text (§1). Only a canonical file is edited;
anything else is reported line by line and left alone. Standard library only: validation reaches `update_env` as a
`transform` from the outer coordinator (`leafi/envedit.py`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("leafi.envfile")

KEY = r"[A-Z][A-Z0-9_]*"
BARE = re.compile(r"[A-Za-z0-9_./:@,+=%-]*")
# KEY=, KEY=bare, KEY='quoted'; then optionally spaces + a comment without '$'
ASSIGN = re.compile(rf"^({KEY})=(?:(?P<bare>[A-Za-z0-9_./:@,+=%-]+)|'(?P<quoted>[^'\\\r\n]*)'|)(?P<comment> +#[^$]*)?$")
COMMENTED = re.compile(rf"^#\s*({KEY})=")
ABSENT = "absent"
ADDED_HEADER = "# ===== Added by the settings page ====="
SIDE_AGE_S = 60.0


class NotCanonical(ValueError):
    pass


class Unstorable(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


@dataclass(frozen=True)
class LineProblem:
    line: int  # 1-based; 0 = the whole file
    key: str | None
    rule: str


@dataclass(frozen=True)
class Op:
    kind: str  # set | empty | unset
    value: str = ""


def _diagnose(text: str) -> tuple[str | None, str]:
    # a key name is reported only for a line that is shaped like an assignment, never for free text (which may be data)
    m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*[=:]", text)
    key = m.group(1) if m else None
    if text[:1].isspace():
        rule = "leading space"
    elif text.startswith("export"):
        rule = "'export' prefix"
    elif key and key != key.upper():
        rule = "lower-case key"
    elif re.match(rf"^{KEY}\s*:", text):
        rule = "':' assignment"
    elif re.match(rf"^{KEY}\s+=|^{KEY}=\s", text) and not re.match(rf"^{KEY}= +#", text):
        rule = "space around '='"
    elif re.match(rf"^{KEY}= +#", text):
        rule = "empty value followed by a comment: readers see the comment as the value"
    elif "${" in text:
        rule = "${...} interpolation"
    elif '"' in text:
        rule = "double quotes"
    elif "\\" in text:
        rule = "backslash"
    elif "$" in text:
        rule = "'$' outside single quotes or in a comment"
    elif "=" not in text:
        rule = "not KEY=VALUE"
    else:
        rule = "value needs single quotes (space, '#' or another character outside A-Z a-z 0-9 _ . / : @ , + = % -)"
    return key, rule


class EnvFile:
    def __init__(self, raw: bytes, text: str | None, nl: str, lines: list[str], final_nl: bool,
                 problems: list[LineProblem]) -> None:
        self.raw, self._text, self.nl, self.lines, self.final_nl = raw, text, nl, lines, final_nl
        self._problems = problems

    # ------------------------------------------------------------ parse / render

    @classmethod
    def parse(cls, raw: bytes) -> "EnvFile":
        problems: list[LineProblem] = []
        if raw.startswith(b"\xef\xbb\xbf"):
            problems.append(LineProblem(1, None, "file starts with a BOM, so its first key is ignored by every Python reader"))
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return cls(raw, None, "\n", [], True, [LineProblem(0, None, "not valid UTF-8")])
        if text.startswith("﻿"):
            text = text[1:]
        crlf = text.count("\r\n")
        lf = text.count("\n") - crlf
        cr = text.count("\r") - crlf
        if cr or (crlf and lf):
            problems.append(LineProblem(0, None, "mixed newline styles"))
        nl = "\r\n" if crlf and not lf else "\n"
        body = text.replace("\r\n", "\n") if nl == "\r\n" else text
        final_nl = body.endswith("\n") or body == ""
        lines = body.split("\n")
        if final_nl:
            lines = lines[:-1]
        seen: dict[str, int] = {}
        # A quoted value may continue over lines, and its lines are data. Once a quote may be open, line boundaries
        # are no longer trustworthy, so no later problem names a key at all (a "key" could be part of a secret).
        open_quote, uncertain = None, False
        for i, ln in enumerate(lines, 1):
            if open_quote:
                problems.append(LineProblem(i, None, "continuation of a multi-line quoted value"))
                if open_quote in re.sub(r"\\.", "", ln):
                    open_quote = None
                continue
            if ln == "" or ln.startswith("#"):
                continue
            m = ASSIGN.match(ln)
            empty_then_comment = m and m.group("bare") is None and m.group("quoted") is None and m.group("comment")
            if m and not empty_then_comment and not (m.group("quoted") is not None and "${" in m.group("quoted")):
                k = m.group(1)
                if k in seen:
                    problems.append(LineProblem(i, None if uncertain else k, f"duplicate of line {seen[k]}"))
                else:
                    seen[k] = i
                continue
            key, rule = _diagnose(ln)
            problems.append(LineProblem(i, None if uncertain else key, rule))
            # any unbalanced quote, wherever it is on the line, may open a value that continues: from here on, lines
            # may be data, so treat what follows as continuation and name no key again
            bare = re.sub(r"\\.", "", ln)
            for qc in ("'", '"'):
                if bare.count(qc) % 2:
                    open_quote, uncertain = qc, True
                    break
        return cls(raw, text, nl, lines, final_nl, problems)

    def render(self) -> bytes:
        body = self.nl.join(self.lines) + (self.nl if self.final_nl and self.lines else "")
        return body.encode("utf-8")

    def digest(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()

    def problems(self) -> list[LineProblem]:
        return list(self._problems)

    # ------------------------------------------------------------ read

    def values(self) -> dict[str, str]:
        """Text of every assignment, as every reader sees it (canonical files only)."""
        if self._problems:
            raise NotCanonical(self._problems[0].rule)
        out = {}
        for ln in self.lines:
            m = ASSIGN.match(ln)
            if m:
                out[m.group(1)] = m.group("bare") or m.group("quoted") or ""
        return out

    def commented_keys(self) -> set[str]:
        return {m.group(1) for ln in self.lines if (m := COMMENTED.match(ln))}

    # ------------------------------------------------------------ write

    @staticmethod
    def encode(key: str, value: str, has_comment: bool) -> str:
        if ("'" in value or "\\" in value or "${" in value
                or any(not (c.isprintable() or c == " ") for c in value)):
            raise Unstorable(key)
        if value == "":
            return "''" if has_comment else ""
        if BARE.fullmatch(value):
            return value
        return f"'{value}'"

    def apply(self, ops: dict[str, Op], anchors: dict[str, str] | None = None) -> "EnvFile":
        """New file with the ops applied; untouched lines stay byte-identical. `anchors` maps a key to the exact text
        of the `.env.example` section header it belongs under (placement of a key the file does not have yet)."""
        if self._problems:
            raise NotCanonical(self._problems[0].rule)
        anchors = anchors or {}
        lines = list(self.lines)
        for key, op in ops.items():
            if not re.fullmatch(KEY, key):
                raise Unstorable(key)
            found = None
            for i, ln in enumerate(lines):
                m = ASSIGN.match(ln)
                if m and m.group(1) == key:
                    found = (i, m)
                    break
            if op.kind == "unset":
                if found:
                    lines[found[0]] = "# " + lines[found[0]]
                continue
            value = "" if op.kind == "empty" else op.value
            if found:
                i, m = found
                comment = m.group("comment") or ""
                lines[i] = f"{key}={self.encode(key, value, bool(comment))}{comment}"
            else:
                lines.insert(_placement(lines, key, anchors.get(key)), f"{key}={self.encode(key, value, False)}")
        out_text = self.nl.join(lines) + (self.nl if (self.final_nl or not self.lines) and lines else "")
        out = EnvFile.parse(out_text.encode("utf-8"))
        if out.problems():  # canonical by construction; never write anything else
            raise NotCanonical(out.problems()[0].rule)
        return out


def _placement(lines: list[str], key: str, anchor: str | None) -> int:
    """Index to insert a new `KEY=` line at: below the last `# KEY=` line; else at the end of the anchor section;
    else at the end of the 'Added by the settings page' section (created once at the end of the file)."""
    last_commented = None
    for i, ln in enumerate(lines):
        m = COMMENTED.match(ln)
        if m and m.group(1) == key:
            last_commented = i
    if last_commented is not None:
        return last_commented + 1
    for header in (anchor, ADDED_HEADER):
        if header and header in lines:
            start = lines.index(header)
            end = start + 1
            while end < len(lines) and not lines[end].startswith("# ====="):
                end += 1
            while end - 1 > start and lines[end - 1] == "":
                end -= 1
            return end
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(ADDED_HEADER)
    return len(lines)


# ---------------------------------------------------------------- the writer


@dataclass
class Committed:
    digest: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class RolledBack:
    reason: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class Conflict:
    pass


@dataclass
class RecoveryRequired:
    paths: dict[str, str]


Outcome = Committed | RolledBack | Conflict | RecoveryRequired

_THREAD_LOCK = threading.Lock()
ERROR_UNABLE_TO_MOVE_REPLACEMENT_2 = 1177


def read_state(path: Path) -> tuple[bytes, str]:
    """Current bytes and digest; a missing file is (b"", "absent")."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return b"", ABSENT
    return raw, hashlib.sha256(raw).hexdigest()


class _FileLock:
    """OS lock on `<path>.lock`: released by the OS when the holder dies, so it is never stolen by age."""

    def __init__(self, path: Path, wait_s: float = 5.0) -> None:
        self.path, self.wait_s, self.fh = path, wait_s, None

    def __enter__(self):
        self.fh = open(self.path, "a+b")
        deadline = time.monotonic() + self.wait_s
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self.fh.close()
                    raise TimeoutError(f"{self.path.name} is held by another writer")
                time.sleep(0.05)

    def __exit__(self, *exc) -> None:
        try:
            if sys.platform == "win32":
                import msvcrt

                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.fh.close()


def protect_like(dst: Path, src: Path) -> None:
    """Give `dst` the access control of `src` (Windows DACL, else mode bits); no-op when `src` is absent."""
    if not src.exists():
        return
    if sys.platform != "win32":
        import shutil

        shutil.copymode(src, dst)
        return
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    get, put = advapi.GetFileSecurityW, advapi.SetFileSecurityW
    get.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    put.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    dacl = 0x4  # DACL_SECURITY_INFORMATION
    need = wintypes.DWORD(0)
    get(str(src), dacl, None, 0, ctypes.byref(need))
    buf = ctypes.create_string_buffer(need.value or 1)
    if not get(str(src), dacl, buf, need, ctypes.byref(need)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not put(str(dst), dacl, buf):
        raise ctypes.WinError(ctypes.get_last_error())


def _replace_file(path: Path, tmp: Path, side: Path) -> int:
    """Install `tmp` over `path` keeping `path`'s security descriptor; 0 on success, else the Win32 error code."""
    if sys.platform != "win32":
        os.replace(tmp, path)
        return 0
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = k32.ReplaceFileW
    fn.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p,
                   ctypes.c_void_p]
    # flags 0: no REPLACEFILE_IGNORE_MERGE_ERRORS, so failing to carry the ACL is a failure
    return 0 if fn(str(path), str(tmp), str(side), 0, None, None) else ctypes.get_last_error()


def _link(src: Path, dst: Path) -> None:
    os.link(src, dst)


def _exclusive(path: Path) -> None:
    os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)))


def _backup(path: Path, old: bytes, backup_dir: Path, keep: int = 5) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamps = []
    for p in backup_dir.glob(".env.*.bak"):
        try:
            stamps.append(int(p.name.split(".")[2]))
        except (IndexError, ValueError):
            continue
    stamp = max([time.time_ns()] + [s + 1 for s in stamps])
    dst = backup_dir / f".env.{stamp}.bak"
    _exclusive(dst)
    protect_like(dst, path)
    dst.write_bytes(old)
    for old_stamp in sorted(stamps + [stamp])[:-keep]:
        (backup_dir / f".env.{old_stamp}.bak").unlink(missing_ok=True)
    return dst


def _write_marker(data_dir: Path, paths: dict[str, str]) -> str | None:
    body = json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **paths}, indent=1)
    for n in range(100):
        p = data_dir / ("env-recovery.json" if n == 0 else f"env-recovery-{n}.json")
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            with open(p, "x", encoding="utf-8") as fh:
                fh.write(body)
            return str(p)
        except FileExistsError:
            continue
        except OSError:
            return None
    return None


def update_env(path: Path, expected_digest: str, transform: Callable[[bytes], bytes], data_dir: Path) -> Outcome:
    """The only way `.env` is written (§2). `transform(old) -> new` may raise; then nothing is written and the
    exception propagates. The result is decided by what `.env` holds afterwards, never by which call failed."""
    path = Path(path)
    with _THREAD_LOCK, _FileLock(path.with_name(path.name + ".lock")):
        old, digest = read_state(path)
        if digest != expected_digest:
            return Conflict()
        existed = digest != ABSENT
        new = transform(old)
        backup = _backup(path, old, data_dir / "env-backup") if existed else None
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
        tmp = Path(tmp_name)
        side = path.with_name(f"{path.name}.{os.urandom(4).hex()}.side")
        try:
            os.close(fd)
            protect_like(tmp, path)
            with open(tmp, "wb") as fh:
                fh.write(new)
                fh.flush()
                os.fsync(fh.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        reason = ""
        if not existed:
            try:
                _link(tmp, path)
            except FileExistsError:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    log.warning("could not remove %s after a conflict", tmp.name)
                return Conflict()
            except OSError as e:
                reason = f"could not create .env ({e.__class__.__name__})"
        else:
            try:
                err = _replace_file(path, tmp, side)
            except OSError as e:  # os.replace off Windows, or ctypes itself failing
                err = -1
                reason = f"replace failed ({e.__class__.__name__})"
            if err:
                reason = reason or f"replace failed (Windows error {err})"
                if err == ERROR_UNABLE_TO_MOVE_REPLACEMENT_2:
                    try:
                        os.replace(side, path)
                    except OSError:
                        pass
        try:
            after = path.read_bytes()
        except FileNotFoundError:
            after = None
        except OSError:
            after = b"\0unknown"  # the state cannot be established: treat as needing recovery, remove nothing
        before = old if existed else None
        if after == new or after == before:
            warnings = []
            for leftover in (tmp, side):
                try:
                    leftover.unlink(missing_ok=True)
                except OSError:
                    warnings.append(f"could not remove {leftover.name}; delete it by hand")
            if after == new:
                return Committed(hashlib.sha256(new).hexdigest(), warnings)
            return RolledBack(reason or "not written", warnings)
        paths = {"side": str(side), "tmp": str(tmp), "backup": str(backup) if backup else ""}
        marker = _write_marker(data_dir, paths)
        paths["marker"] = marker or ""
        log.critical(".env needs manual recovery: %s", paths)
        return RecoveryRequired(paths)


def health(path: Path, data_dir: Path, now: float | None = None) -> list[str]:
    """Why the `env-file` check fails (empty = passes): recovery marker, recovery leftovers, missing, non-canonical."""
    now = time.time() if now is None else now
    out = [f"recovery marker {p.name}" for p in sorted(Path(data_dir).glob("env-recovery*.json"))]
    path = Path(path)
    for p in sorted(path.parent.glob(path.name + ".*")):
        if p.suffix in (".side", ".tmp") and now - p.stat().st_mtime > SIDE_AGE_S:
            out.append(f"leftover {p.name}")
    raw, digest = read_state(path)
    if digest == ABSENT:
        out.append(".env is missing")
    elif EnvFile.parse(raw).problems():
        out.append(".env is not in canonical form")
    return out
