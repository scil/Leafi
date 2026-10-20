"""`python -m leafi doctor`: every backend as ok / missing package / missing model / disabled / deferred.

Leafi downloads nothing at runtime (ADR-0011): `doctor` prints what is missing, and `doctor --download` is the
one sanctioned downloader. It fetches only the fixed set below (release assets and model hubs), never at
inference time, and skips what is already present.
"""

from __future__ import annotations

import importlib
import logging
import shutil
import tarfile
import tempfile
import urllib.request
from collections.abc import Iterator
from pathlib import Path

from leafi.core.config import Settings

log = logging.getLogger("leafi.doctor")

SERVICES: list[tuple[str, str, str]] = [
    # (label, registry module, settings attribute holding the configured backend)
    ("asr", "leafi.services.asr", "asr_backend"),
    ("vad", "leafi.services.asr.vad", "asr_backend"),
    ("tts en", "leafi.services.tts", "tts_backend_en"),
    ("tts zh", "leafi.services.tts", "tts_backend_zh"),
    ("ocr", "leafi.services.ocr", "ocr_backend"),
    ("ocr second opinion", "leafi.services.ocr", "ocr_second_opinion"),
    ("pronunciation", "leafi.services.pronunciation", "pron_backend"),
    ("brain", "leafi.services.brain", "brain_backend"),
    ("brain local fallback", "leafi.services.brain", "brain_local_model"),
    ("book lookup", "leafi.services.catalog", "book_lookup"),
]

KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"


def rows(settings: Settings) -> Iterator[tuple[str, str, str, str]]:
    for label, module, attr in SERVICES:
        backend = str(getattr(settings, attr) or "")
        if attr == "brain_local_model":
            backend = "ollama" if backend else ""
        if attr == "ocr_second_opinion" and not backend:
            yield label, "-", "deferred", "qwen_vl second opinion is deferred in v1 (ADR-0011)"
            continue
        if label == "vad":
            if backend in ("", "off", "mock"):
                yield label, "-", "disabled", "energy end-pointer (mock ASR)"
                continue
            backend = "silero"
        if not backend or backend == "off":
            yield label, backend or "-", "disabled", ""
            continue
        try:
            mod = importlib.import_module(module)
            if label == "vad":
                state, detail = mod.status(settings)
            else:
                state, detail = mod.REGISTRY.status(backend, settings)
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


# ---------------------------------------------------------------- downloads


def _fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"  fetching {url}")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:  # noqa: S310 - fixed https URLs
        shutil.copyfileobj(r, f, 1 << 20)
    tmp.replace(dest)


def download_asr(settings: Settings) -> str:
    from leafi.services.asr import sherpa

    d = Path(settings.asr_model_dir)
    if all((d / f).exists() for f in sherpa.FILES):
        return "present"
    with tempfile.TemporaryDirectory(prefix="leafi-asr-") as tmp:
        archive = Path(tmp) / "model.tar.bz2"
        _fetch(sherpa.DOWNLOAD, archive)
        with tarfile.open(archive, "r:bz2") as tar:
            members = [m for m in tar.getmembers()
                       if m.isfile() and Path(m.name).name in sherpa.FILES and ".." not in m.name]
            d.mkdir(parents=True, exist_ok=True)
            for m in members:
                with tar.extractfile(m) as src, open(d / Path(m.name).name, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
    return "downloaded"


def download_vad(settings: Settings) -> str:
    from leafi.services.asr import vad

    p = vad.model_path(settings)
    if p.exists():
        return "present"
    _fetch(vad.DOWNLOAD, p)
    return "downloaded"


def download_tts(settings: Settings) -> str:
    from leafi.services.tts import kokoro

    got = []
    for p in kokoro._paths(settings):
        if not p.exists():
            _fetch(KOKORO_RELEASE + p.name, p)
            got.append(p.name)
    return "downloaded " + ", ".join(got) if got else "present"


def download_pronunciation(settings: Settings) -> str:
    from leafi.services.pronunciation import openpronounce as op

    state, _ = op.status(settings)
    if state == "ok":
        return "present"
    from huggingface_hub import snapshot_download  # lazy; installed with openpronounce

    cache = op.hf_dir(settings)
    cache.mkdir(parents=True, exist_ok=True)
    for repo in op.HF_REPOS:
        print(f"  fetching {repo}")
        path = snapshot_download(repo, cache_dir=str(cache), allow_patterns=["*.json", "*.txt", "*.safetensors"])
        if not any(Path(path).glob("*.safetensors")):
            snapshot_download(repo, cache_dir=str(cache), allow_patterns=["*.json", "*.txt", "pytorch_model.bin"])
    return "downloaded"


def download_ocr(settings: Settings) -> str:
    """RapidOCR fetches its ONNX files on first use into its package; provision PP-OCRv5 (en) and v6 now."""
    from leafi.services.ocr import rapidocr as backend

    done = []
    for version in backend.VERSIONS:
        engine = backend.engine(version)
        engine(_probe_image())  # models load (and download once) on the first call, not in the constructor
        done.append(version)
    return "present: " + ", ".join(done)


def _probe_image() -> bytes:
    import io

    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (480, 120), "white")
    ImageDraw.Draw(img).text((20, 30), "Leafi page 12", fill="black", font=ImageFont.load_default(size=40))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


DOWNLOADS = [("asr", download_asr), ("vad", download_vad), ("tts en", download_tts),
             ("pronunciation", download_pronunciation), ("ocr", download_ocr)]


def download(settings: Settings, only: set[str] | None = None) -> list[tuple[str, str]]:
    out = []
    for label, fn in DOWNLOADS:
        if only and label not in only:
            continue
        try:
            out.append((label, fn(settings)))
        except Exception as e:  # noqa: BLE001 - report and continue with the next model
            out.append((label, f"failed: {type(e).__name__}: {e}"))
    return out
