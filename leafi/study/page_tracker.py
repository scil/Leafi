"""Page tracker (B2): frame-diff settle → OCR → printed number or observation match → page + revision.

Reliability (reliability.md): low OCR confidence → recapture once → ask the learner to read the first line
→ offer typed page text. A frame-diff without a confident match → PAGE_UNCERTAIN: assessment suspended
until the learner confirms. A new OCR never overwrites verified spans (pages.add_ocr_revision).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import io
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from leafi.core.ports import Eye, Frame
from leafi.core.storage import Store, now_iso
from leafi.study import pages

log = logging.getLogger("leafi.page_tracker")
NUMBER_RE = re.compile(r"^\s*(?:page\s+)?(\d{1,4})\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class PageFound:
    status: str  # ready | uncertain | low_confidence | unavailable
    page_id: int | None = None
    revision_id: int | None = None
    message: str = ""
    candidates: tuple[int, ...] = ()
    observations: dict | None = None
    printed_number: int | None = None


def frame_diff(a: Frame, b: Frame, size: int = 64) -> float:
    """Mean absolute grey-level difference of two frames downscaled to `size`×`size` (0..255)."""
    from PIL import Image, ImageChops, ImageStat

    ia = Image.open(io.BytesIO(a.data)).convert("L").resize((size, size))
    ib = Image.open(io.BytesIO(b.data)).convert("L").resize((size, size))
    return float(ImageStat.Stat(ImageChops.difference(ia, ib)).mean[0])


def split_number(lines: list[str]) -> tuple[int | None, list[str]]:
    """A line that is only a number (first or last two lines) is the printed page number."""
    body = list(lines)
    for idx in (0, 1, -1, -2):
        if len(body) > abs(idx) and NUMBER_RE.match(body[idx]):
            n = int(NUMBER_RE.match(body[idx]).group(1))
            del body[idx]
            return n, body
    return None, body


class PageTracker:
    def __init__(self, store: Store, eye: Eye | None, ocr, settings, *, sleep=asyncio.sleep,
                 settle_frames: int = 2, diff_threshold: float = 1.0, interval_s: float = 0.4) -> None:
        # diff_threshold (mean grey diff at 64×64): two different text pages differ by ~1.7, a hand by ~40.
        # Calibrate on real desk captures in prototype P-3.
        self.store = store
        self.eye = eye
        self.ocr = ocr
        self.settings = settings
        self._sleep = sleep
        self.settle_frames = settle_frames
        self.diff_threshold = diff_threshold
        self.interval_s = interval_s
        self.last: Frame | None = None

    async def settle(self, max_frames: int = 12) -> Frame | None:
        """Wait until consecutive frames stop changing (page turn finished, hands out of the way)."""
        if self.eye is None:
            return None
        prev = await self.eye.snapshot(None)
        if prev is None:
            return None
        still = 0
        for _ in range(max_frames):
            await self._sleep(self.interval_s)
            cur = await self.eye.snapshot(None)
            if cur is None:
                return None
            if frame_diff(prev, cur) < self.diff_threshold:
                still += 1
                if still >= self.settle_frames:
                    return cur
            else:
                still = 0
            prev = cur
        return None

    def changed(self, frame: Frame) -> bool:
        return self.last is None or frame_diff(self.last, frame) >= self.diff_threshold

    async def read(self):
        """Settle and OCR; one recapture when confidence is low. Returns (frame, result) or (None, None)."""
        frame = await self.settle()
        if frame is None or self.ocr is None:
            return None, None
        result = await self.ocr.read(frame)
        if result.confidence < self.settings.ocr_min_confidence:
            log.info("OCR confidence %.2f low; recapturing once", result.confidence)
            again = await self.settle()
            if again is not None:
                frame, result = again, await self.ocr.read(again)
        return frame, result

    async def find(self, book_id: int, expected_number: int | None = None) -> PageFound:
        frame, result = await self.read()
        if frame is None:
            return PageFound("unavailable", message="I can't see the page. Which page are you on? (/page N)")
        self.last = frame
        if result.confidence < self.settings.ocr_min_confidence:
            return PageFound("low_confidence",
                             message="The page is hard for me to read. Read me the first line, or type the page.")
        number, body = split_number([ln.text for ln in result.lines])
        text = "\n".join(body)
        obs = pages.observations_of(text)
        match = pages.match_page(self.store, book_id, obs, number)
        if match.status == "uncertain":
            guess = self.store.one("SELECT printed_number FROM pages WHERE id=?", (match.page_id,))
            label = guess["printed_number"] if guess and guess["printed_number"] is not None else "the one we read before"
            return PageFound("uncertain", match.page_id, message=f"Is this page {label}? (yes / no)",
                             candidates=match.candidates, observations=obs, printed_number=number)
        if match.status == "matched":
            page_id = match.page_id
            pages.confirm_observations(self.store, page_id, obs)
        else:
            page_id = pages.create_page(self.store, book_id, number, obs)
        pages.add_ocr_revision(self.store, page_id, text, self.settings.ocr_backend, result.confidence)
        self.save_image(page_id, frame)
        rev = pages.current_revision(self.store, page_id)
        return PageFound("ready", page_id, rev.id, observations=obs, printed_number=number)

    def confirm(self, found: PageFound, page_id: int) -> PageFound:
        """The learner confirmed an uncertain match: store the observation set; assessment resumes."""
        if found.observations:
            pages.confirm_observations(self.store, page_id, found.observations)
        rev = pages.current_revision(self.store, page_id)
        return PageFound("ready", page_id, rev.id if rev else None)

    # ---- page images (retention: PAGES_RETAIN_DAYS)
    def save_image(self, page_id: int, frame: Frame) -> Path:
        d = Path(self.settings.cache_dir) / "pages"
        d.mkdir(parents=True, exist_ok=True)
        ext = ".png" if frame.mime == "image/png" else ".jpg"
        path = d / (hashlib.sha256(frame.data).hexdigest()[:24] + ext)
        path.write_bytes(frame.data)
        self.store.insert("page_images", page_id=page_id, path=str(path), width=frame.width, captured_at=now_iso())
        return path


def purge_page_images(store: Store, retain_days: int, now: dt.datetime | None = None) -> int:
    now = now or dt.datetime.now(dt.UTC)
    cutoff = (now - dt.timedelta(days=retain_days)).isoformat()
    rows = store.all("SELECT id, path FROM page_images WHERE captured_at < ?", (cutoff,))
    for r in rows:
        Path(r["path"]).unlink(missing_ok=True)
        store.execute("DELETE FROM page_images WHERE id=?", (r["id"],))
    return len(rows)
