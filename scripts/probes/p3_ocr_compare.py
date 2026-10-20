"""Prototype P-3: RapidOCR PP-OCRv5 vs PP-OCRv6 on desk captures; frame-diff noise; page-number detection.

Plan → Prototypes: three desk captures (hands, curvature, glare, a spread) at snapshot widths 1920 and 2304;
report reading order, missing lines and page-number detection separately from word accuracy. Without
captures (camera offline) it runs on PIL-rendered fixture pages so the two pipelines are at least exercised.

Owner, to take the captures (silent; nothing is pushed to the camera):
    scripts\\win\\go2rtc-host.bat
    .venv\\Scripts\\python scripts/probes/p3_ocr_compare.py --capture 3 --out cache/desk     (3 stills, 4 s apart, both widths)
    .venv\\Scripts\\python scripts/probes/p3_ocr_compare.py --dir cache/desk                 (compare v5/v6, print the report)
Ground truth: put `<image stem>.txt` next to a capture (the page's text, one line per printed line) to get
word accuracy; otherwise only line counts, confidence, timing and the page number are reported.
Keep the captures out of git unless the owner agrees (book text may be copyrighted); the report prints a hash.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from leafi.core.ports import Frame  # noqa: E402
from leafi.core.text import words as norm_words  # noqa: E402
from leafi.services.ocr import OcrResult  # noqa: E402
from leafi.study.page_tracker import frame_diff, split_number  # noqa: E402

WIDTHS = (1920, 2304)


def engines():
    from leafi.services.ocr import rapidocr as backend

    return {v: backend.engine(v) for v in backend.VERSIONS}


def run(engine, data: bytes) -> tuple[OcrResult, float]:
    from leafi.services.ocr import rapidocr as backend

    t0 = time.perf_counter()
    res = engine(data)
    return backend.to_result(res), time.perf_counter() - t0


def word_accuracy(got: str, truth: str) -> tuple[float, int, int]:
    """1 − word edit distance / truth words, after norm()."""
    from rapidfuzz.distance import Levenshtein

    a, b = norm_words(truth), norm_words(got)
    d = Levenshtein.distance(a, b)
    return (1 - d / max(1, len(a))), d, len(a)


def report_image(name: str, data: bytes, truth: str | None, engs) -> None:
    print(f"\n### {name}  sha256 {hashlib.sha256(data).hexdigest()[:16]}  {len(data)/1024:.0f} KiB")
    for label, eng in engs.items():
        res, dt = run(eng, data)
        number, body = split_number([ln.text for ln in res.lines])
        text = "\n".join(body)
        acc = ""
        if truth:
            a, d, n = word_accuracy(text, truth)
            acc = f" word acc {a:.3f} ({d} edits / {n} words)"
        print(f"- {label}: {len(res.lines)} lines, conf {res.confidence:.3f}, {dt:.2f}s, page number {number}{acc}")
        for ln in res.lines[:40]:
            print(f"    [{ln.conf:.2f}] {ln.text}")
        if len(res.lines) > 40:
            print(f"    … {len(res.lines) - 40} more lines")


def capture(n: int, out: Path, go2rtc: str, stream: str, gap_s: float) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(1, n + 1):
        for w in WIDTHS:
            url = f"{go2rtc}/api/frame.jpeg?src={stream}&width={w}"
            with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310 - loopback go2rtc
                data = r.read()
            p = out / f"cap{i}-{w}.jpg"
            if data:
                p.write_bytes(data)
                paths.append(p)
                print(f"saved {p} ({len(data)/1024:.0f} KiB)")
            else:
                print(f"{url} returned 0 bytes (camera offline? check tools/go2rtc/host.log)")
        if i < n:
            time.sleep(gap_s)
    return paths


def frame_noise(paths: list[Path]) -> None:
    """Mean grey diff (64×64) between consecutive stills of the same width = camera noise floor for
    page_tracker.diff_threshold (1.0 on rendered pages; a different page ≈ 1.7, a hand ≈ 40)."""
    by_width: dict[str, list[Path]] = {}
    for p in sorted(paths):
        m = re.search(r"-(\d+)\.jpe?g$", p.name)
        by_width.setdefault(m.group(1) if m else "?", []).append(p)
    for w, ps in by_width.items():
        diffs = [frame_diff(Frame(a.read_bytes()), Frame(b.read_bytes())) for a, b in zip(ps, ps[1:], strict=False)]
        if diffs:
            print(f"frame-diff noise at width {w}: {[round(d, 2) for d in diffs]} (threshold now 1.0)")


def fixtures() -> list[tuple[str, bytes, str]]:
    from tests.fixtures.pages import PAGES, render

    out = []
    for k, text in enumerate(PAGES[:3], 1):
        out.append((f"rendered fixture p{k}", render(text, number=k, width=1920).data, text))
    # a rotated, blurred variant stands in for curvature/glare
    from PIL import Image, ImageFilter

    im = Image.open(io.BytesIO(out[0][1])).rotate(3, expand=True, fillcolor="white").filter(ImageFilter.GaussianBlur(1.2))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    out.append(("rendered fixture p1 rotated 3° + blur", buf.getvalue(), PAGES[0]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, help="folder of desk captures (*.jpg/*.png)")
    ap.add_argument("--capture", type=int, default=0, help="take N stills from the host go2rtc into --out")
    ap.add_argument("--out", type=Path, default=Path("cache/desk"))
    ap.add_argument("--go2rtc", default="http://127.0.0.1:2984")
    ap.add_argument("--stream", default="cam_xiaomi")
    ap.add_argument("--gap", type=float, default=4.0)
    a = ap.parse_args()
    if a.capture:
        capture(a.capture, a.out, a.go2rtc, a.stream, a.gap)
        a.dir = a.out
    engs = engines()
    if a.dir and a.dir.exists():
        paths = sorted(p for p in a.dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
        if not paths:
            print(f"no captures in {a.dir}")
        frame_noise(paths)
        for p in paths:
            truth = p.with_suffix(".txt")
            report_image(p.name, p.read_bytes(), truth.read_text(encoding="utf-8") if truth.exists() else None, engs)
    else:
        print("no capture folder: running on PIL-rendered fixtures (pipeline check only)")
        for name, data, truth in fixtures():
            report_image(name, data, truth, engs)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
