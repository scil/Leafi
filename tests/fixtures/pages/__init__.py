"""PIL-rendered page fixtures (generated at test time; no binary fixtures in git).

`render(text)` draws the text on a white page and embeds the ground truth in PNG text chunks that the mock
OCR backend reads: `leafi:text`, optional `leafi:ocr` (a simulated misread), `leafi:conf`, `leafi:isbn`.
"""

from __future__ import annotations

import io

from leafi.core.ports import Frame


def render(text: str, *, number: int | None = None, ocr_text: str | None = None, conf: float = 0.95,
           isbn: str | None = None, width: int = 1200, shift: int = 0) -> Frame:
    from PIL import Image, ImageDraw, ImageFont
    from PIL.PngImagePlugin import PngInfo

    lines = text.splitlines()
    if number is not None:
        lines = [*lines, str(number)]
    font = ImageFont.load_default(size=36)
    img = Image.new("RGB", (width, 120 + 60 * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    for k, line in enumerate(lines):
        draw.text((60 + shift, 50 + 60 * k), line, fill="black", font=font)
    info = PngInfo()
    full = "\n".join(lines)
    info.add_text("leafi:text", full)
    if ocr_text is not None:
        info.add_text("leafi:ocr", ocr_text + (f"\n{number}" if number is not None else ""))
    info.add_text("leafi:conf", str(conf))
    if isbn:
        info.add_text("leafi:isbn", isbn)
    buf = io.BytesIO()
    img.save(buf, "PNG", pnginfo=info)
    return Frame(buf.getvalue(), "image/png", width)


def blank(seed: int = 0, width: int = 400) -> Frame:
    """A frame of a hand moving over the page: different content per seed."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (width, 300), "white")
    ImageDraw.Draw(img).rectangle((seed * 37 % 300, 20, seed * 37 % 300 + 90, 280), fill="black")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return Frame(buf.getvalue(), "image/png", width)


PAGES = [
    "Tom had a red kite.\nHe ran up the hill.\nThe wind was strong.",
    "Mia found a shell.\nShe took it home.\nIt was pink inside.",
    "The boat was small.\nIt rocked on the waves.\nDad held the rope.",
    "At night the stars came out.\nOwls called from the trees.\nEveryone slept.",
    "In the morning it rained.\nThe puddles were deep.\nWe jumped in them all.",
]


class FakeEye:
    def __init__(self, frames: list[Frame | None]) -> None:
        self.frames = list(frames)
        self.calls = 0

    def show(self, *frames: Frame | None) -> None:
        self.frames = list(frames)

    async def snapshot(self, max_width: int | None = None) -> Frame | None:
        self.calls += 1
        if len(self.frames) > 1:
            return self.frames.pop(0)
        return self.frames[0] if self.frames else None
