"""Synthetic desk photos with known page text, for the OCR evaluation trial.

    .venv-eval\\Scripts\\python scripts/evals/ocr/make_synthetic.py

Real photos show the family home, so they never leave this PC and no cloud model looks at them. These stand-ins
copy the camera's wide shot (1920×1080, page ≈ a fifth of the frame, capitals ≈ 15 px, the clock overlay) and
carry every condition tag, so the whole workflow can be checked end to end before the owner types real ground
truth. The page text is written for this file (no book is copied). Output: photos/synthetic/*.png plus
synthetic.json (truth and tags), both under the gitignored cache/evals/ocr/.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evalenv  # noqa: E402
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont  # noqa: E402

FONTS = Path("C:/Windows/Fonts")
PLAIN, DECORATIVE = "georgia.ttf", "JOKERMAN.TTF"
PAGES = {
    "s-p4": (4, ["Mia found a small green box", "under the old oak tree.", "It was cold and very quiet.",
                 "She lifted the lid slowly", "and a tiny frog looked up."]),
    "s-p5": (5, ["The frog said hello to Mia.", "Mia was so surprised that", "she sat down in the grass.",
                 "Do you like to sing, asked", "the frog with a big smile."]),
    "s-p6": (6, ["They sang a song together", "about rain and puddles and", "boats made of paper leaves.",
                 "The birds came down to listen", "and the sun began to set."]),
    "s-p7": (7, ["Mia carried the box home", "and put it by her window.", "Every morning the frog sang",
                 "a new song for the street."]),
}
# Spread: two facing pages, read left then right.
SPREAD = ("s-p6", "s-p7")

# name, page, angle (degrees the reader turns the frame counter-clockwise), tilt, layout, hand, desk, light
SHOTS = [
    ("syn-01", "s-p4", 0, 0, "plain", "none", "clean", "normal"),
    ("syn-02", "s-p4", 270, 0, "plain", "none", "clean", "normal"),
    ("syn-03", "s-p4", 90, 0, "plain", "none", "clean", "normal"),
    ("syn-04", "s-p5", 270, 8, "plain", "none", "clean", "normal"),
    ("syn-05", "s-p5", 270, 0, "decorative font", "none", "clean", "normal"),
    ("syn-06", "s-p5", 270, 0, "plain", "edge", "clean", "normal"),
    ("syn-07", "s-p4", 270, 0, "plain", "covering", "clean", "normal"),
    ("syn-08", "s-p6", 270, 0, "plain", "none", "cluttered", "normal"),
    ("syn-09", "s-p6", 270, 0, "plain", "none", "clean", "dim"),
    ("syn-10", "s-p7", 270, 0, "text around picture", "none", "clean", "normal"),
    ("syn-11", SPREAD, 0, 0, "spread", "none", "clean", "normal"),
    ("syn-12", "s-p7", 90, 0, "decorative font", "none", "cluttered", "normal"),
]


def font(name: str, size: int):
    return ImageFont.truetype(str(FONTS / name), size)


def page_image(page: str, layout: str, rng: random.Random) -> Image.Image:
    number, lines = PAGES[page]
    f = font(DECORATIVE if layout == "decorative font" else PLAIN, 21)
    w, h = 400, 520
    img = Image.new("RGBA", (w, h), (246, 242, 230, 255))
    d = ImageDraw.Draw(img)
    y = 40
    for k, line in enumerate(lines):
        if layout == "text around picture" and k == 2:
            d.rectangle((60, y, w - 60, y + 170), fill=(rng.randint(80, 200), 140, 90, 255))
            d.ellipse((150, y + 40, 250, y + 140), fill=(40, 120, 60, 255))
            y += 190
        d.text((36, y), line, font=f, fill=(25, 25, 25, 255))
        y += 36
    d.text((w // 2 - 6, h - 40), str(number), font=font(PLAIN, 18), fill=(25, 25, 25, 255))
    return img


def desk(rng: random.Random) -> Image.Image:
    img = Image.new("RGB", (1920, 1080), (120, 86, 58))
    d = ImageDraw.Draw(img)
    for x in range(0, 1920, 6):
        c = 110 + rng.randint(-12, 12)
        d.line((x, 0, x + rng.randint(-40, 40), 1080), fill=(c, int(c * 0.72), int(c * 0.48)), width=6)
    return img.filter(ImageFilter.GaussianBlur(1.5))


def clutter(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    d.rectangle((1380, 140, 1640, 330), fill=(250, 235, 120))
    d.text((1400, 170), "Buy milk and eggs", font=font("arial.ttf", 24), fill=(30, 30, 30))
    d.text((1400, 220), "Call the dentist", font=font("arial.ttf", 24), fill=(30, 30, 30))
    d.rectangle((260, 760, 620, 900), fill=(200, 200, 205))
    d.text((280, 800), "HANDLE WITH CARE", font=font("arial.ttf", 30), fill=(160, 20, 20))


def shoot(name, page, angle, tilt, layout, hand, desk_kind, light, rng) -> tuple[Image.Image, str, int | None]:
    if layout == "spread":
        a, b = (page_image(p, "plain", rng) for p in page)
        sheet = Image.new("RGBA", (a.width * 2 + 8, a.height), (90, 90, 90, 255))
        sheet.paste(a, (0, 0))
        sheet.paste(b, (a.width + 8, 0))
        truth = "\n".join(PAGES[page[0]][1] + PAGES[page[1]][1])
        number = None  # two printed numbers: the pipeline cannot report one
    else:
        sheet = page_image(page, layout, rng)
        truth = "\n".join(PAGES[page][1])
        number = PAGES[page][0]
    # The page lies so that turning the frame `angle` degrees counter-clockwise makes it upright.
    sheet = sheet.rotate(-angle + tilt, expand=True, resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0))
    img = desk(rng)
    if desk_kind == "cluttered":
        clutter(img)
    x, y = (1920 - sheet.width) // 2 + rng.randint(-60, 60), (1080 - sheet.height) // 2 + rng.randint(-30, 30)
    img.paste(sheet, (x, y), sheet)
    d = ImageDraw.Draw(img)
    skin = (224, 172, 140)
    if hand == "edge":
        d.ellipse((x + sheet.width - 70, y + sheet.height - 120, x + sheet.width + 180, y + sheet.height + 100), fill=skin)
    elif hand == "covering":
        d.ellipse((x + sheet.width // 2 - 40, y + 30, x + sheet.width + 160, y + sheet.height // 2 + 60), fill=skin)
    d.text((24, 18), "2026-10-25 13:14:20", font=font("arial.ttf", 30), fill=(255, 255, 255))
    if light == "dim":
        img = ImageEnhance.Brightness(img).enhance(0.42)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    return img, truth, number


def main() -> None:
    rng = random.Random(20261025)
    out = evalenv.PHOTOS / "synthetic"
    out.mkdir(parents=True, exist_ok=True)
    meta = []
    for name, page, angle, tilt, layout, hand, desk_kind, light in SHOTS:
        img, truth, number = shoot(name, page, angle, tilt, layout, hand, desk_kind, light, rng)
        path = out / f"{name}.png"
        img.save(path)
        meta.append({"file": f"synthetic/{name}.png", "page_id": "+".join(page) if isinstance(page, tuple) else page,
                     "truth": truth, "page_number": number, "angle": "tilted" if tilt else str(angle),
                     "expected_rotation": angle, "hand": hand, "desk": desk_kind, "light": light,
                     "layout": layout, "source": "synthetic"})
    (evalenv.DATA / "synthetic.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"{len(meta)} synthetic photos in {out}")


if __name__ == "__main__":
    main()
