"""FiftyOne app for the OCR evaluation dataset, on 127.0.0.1:19151 (started by `stack.ps1 fiftyone`)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evalenv  # noqa: E402,F401  (telemetry off before fiftyone is imported)

import fiftyone as fo  # noqa: E402

dataset = fo.load_dataset(evalenv.DATASET) if fo.dataset_exists(evalenv.DATASET) else None
session = fo.launch_app(dataset, address="127.0.0.1", port=19151, remote=True, auto=False)
session.wait(-1)
