"""Shared setup for the OCR evaluation trial: telemetry off, paths, local endpoints, secrets.

Import this before any tool. It refuses an endpoint that is not on this PC, so a missing setting cannot fall back
to a vendor cloud (the Langfuse SDK defaults to https://cloud.langfuse.com).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

TELEMETRY_OFF = {
    "MLFLOW_DISABLE_TELEMETRY": "true",
    "DO_NOT_TRACK": "true",
    "FIFTYONE_DO_NOT_TRACK": "true",
    "PHOENIX_TELEMETRY_ENABLED": "false",
    "MLFLOW_DISABLE_AGENT_HINT": "1",
}
os.environ.update(TELEMETRY_OFF)
# Piped output (the Obsidian console) defaults to cp1252, which has no → or Chinese: print would raise.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]  # this checkout (code, git commit)
_common = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                         capture_output=True, text=True, check=True).stdout.strip()
MAIN = Path(_common).parent  # the main checkout, also from a worktree: data outlives the worktree
EVALS = MAIN / "cache" / "evals"
DATA = EVALS / "ocr"
PHOTOS = DATA / "photos"
TRUTH = DATA / "truth.json"
TAGS_FILE = HERE / "tags.json"  # the condition tags: group → options; changed only through tags.py
DATASET = "leafi-ocr"
os.environ.setdefault("FIFTYONE_DATABASE_DIR", str(EVALS / "fiftyone" / "db"))

MLFLOW_URI = "http://127.0.0.1:19500"
PHOENIX_URL = "http://127.0.0.1:19006"
LANGFUSE_URL = "http://localhost:19300"
LABEL_STUDIO_URL = "http://localhost:19080"


def local(url: str) -> str:
    host = urlparse(url).hostname
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit(f"refusing a non-local endpoint: {url}")
    return url


for _u in (MLFLOW_URI, PHOENIX_URL, LANGFUSE_URL, LABEL_STUDIO_URL):
    local(_u)


def tags() -> dict[str, list[str]]:
    return json.loads(TAGS_FILE.read_text(encoding="utf-8"))


def secrets() -> dict[str, str]:
    """cache/evals/stack.env, written by `stack.ps1 up`."""
    path = EVALS / "stack.env"
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def git_state() -> tuple[str, bool]:
    """(commit, dirty) of this checkout."""
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=no"],
                                capture_output=True, text=True, check=True).stdout.strip())
    return commit, dirty
