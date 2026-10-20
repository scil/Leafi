"""`python -m leafi doctor`: every backend as ok / missing package / missing model / disabled / deferred.

Leafi downloads nothing at runtime (ADR-0011); `doctor` prints the download command for each missing model.
`--download` is the only sanctioned downloader and is not implemented in this slice (it prints the plan).
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator

from leafi.core.config import Settings

SERVICES: list[tuple[str, str, str]] = [
    # (label, registry module, settings attribute holding the configured backend)
    ("asr", "leafi.services.asr", "asr_backend"),
    ("tts en", "leafi.services.tts", "tts_backend_en"),
    ("tts zh", "leafi.services.tts", "tts_backend_zh"),
    ("ocr", "leafi.services.ocr", "ocr_backend"),
    ("ocr second opinion", "leafi.services.ocr", "ocr_second_opinion"),
    ("pronunciation", "leafi.services.pronunciation", "pron_backend"),
    ("brain", "leafi.services.brain", "brain_backend"),
    ("brain local fallback", "leafi.services.brain", "brain_local_model"),
    ("book lookup", "leafi.services.catalog", "book_lookup"),
]


def rows(settings: Settings) -> Iterator[tuple[str, str, str, str]]:
    for label, module, attr in SERVICES:
        backend = str(getattr(settings, attr) or "")
        if attr == "brain_local_model":
            backend = "ollama" if backend else ""
        if attr == "ocr_second_opinion" and not backend:
            yield label, "-", "deferred", "qwen_vl second opinion is deferred in v1 (ADR-0011)"
            continue
        if not backend or backend == "off":
            yield label, backend or "-", "disabled", ""
            continue
        try:
            reg = importlib.import_module(module).REGISTRY
            state, detail = reg.status(backend, settings)
        except (ImportError, LookupError) as e:
            state, detail = "error", str(e)
        yield label, backend, state, detail


def report(settings: Settings) -> str:
    lines = [f"{'service':<22}{'backend':<16}{'state':<16}detail"]
    for label, backend, state, detail in rows(settings):
        lines.append(f"{label:<22}{backend:<16}{state:<16}{detail}")
    if not settings.redact_list():
        lines.append("WARNING: REDACT_TERMS is empty; set it with: python -m leafi setup --redact \"<name>,<school>\"")
    if settings.pron_auto_judge:
        lines.append("NOTE: PRON_AUTO_JUDGE is on; it requires the evaluation threshold in ADR-0011.")
    return "\n".join(lines)
