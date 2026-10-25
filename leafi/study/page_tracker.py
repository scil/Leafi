"""Page tracker (B2): frame-diff settle → OCR → printed number or observation match → page + revision.

Reliability (reliability.md): a read that needs help (unsure angle or low confidence) → recapture once, but only
when the frame changed → otherwise ask the learner at once. A frame-diff without a confident match →
PAGE_UNCERTAIN: assessment suspended until the learner confirms. A new OCR never overwrites verified spans
(pages.add_ocr_revision), and a read that lost a stored page's words adds no revision (missing-words guard).
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
from leafi.core.text import words
from leafi.study import pages

log = logging.getLogger("leafi.page_tracker")
NUMBER_RE = re.compile(r"^\s*(?:page\s+)?(\d{1,4})\s*$", re.IGNORECASE)
OCR_TIMEOUT_S = 15.0  # performance.md: the timeout that bounds an OCR stall
MISSING = 0.2  # a read that lost more than this share of a stored page's words (and at least MISSING_MIN) is partial
MISSING_MIN = 3
PARTIAL_MESSAGE = ("I can only see part of the page. Move your hand away and type /page to look again, "
                   "or /page N --text <file> to type it.")


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


def split_number(lines, min_conf: float) -> tuple[int | None, list[str]]:
    """A line that is only a number (first or last two lines) is the printed page number when it was read with
    confidence ≥ `min_conf` (ADR-0010: a confidently read number); a number-only line read below it gives no number
    and is dropped from the text, since a page number is never reading text (OCR design 2026-10-25 O7)."""
    n = len(lines)
    drop: set[int] = set()
    number = None
    for idx in (0, 1, -1, -2):
        k = idx % n if n > abs(idx) else None
        if k is None or k in drop or not NUMBER_RE.match(lines[k].text):
            continue
        drop.add(k)
        if lines[k].conf >= min_conf:
            number = int(NUMBER_RE.match(lines[k].text).group(1))
            break
    return number, [ln.text for k, ln in enumerate(lines) if k not in drop]


def missing_words(old_text: str, new_text: str) -> tuple[int, int]:
    """(words of `old_text` the new read lost, words of `old_text`). Substitutions, a moved line and the shifts
    SequenceMatcher makes on repeated words are not losses: leftover old and new words are paired by similarity
    first (OCR design 2026-10-25 O7, round 6 W1/W2)."""
    from difflib import SequenceMatcher

    from rapidfuzz import fuzz

    old = [w.lower() for w in words(old_text)]
    new = [w.lower() for w in words(new_text)]
    uo: list[str] = []
    un: list[str] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        k = min(i2 - i1, j2 - j1) if tag == "replace" else 0  # paired in place: substitutions
        uo += old[i1 + k:i2]
        un += new[j1 + k:j2]
    missing = 0
    for w in uo:
        b = max(un, key=lambda x: fuzz.ratio(w, x), default=None)
        if b is not None and fuzz.ratio(w, b) >= 60:
            un.remove(b)
        else:
            missing += 1
    return missing, len(old)


def is_partial(old_text: str, new_text: str) -> bool:
    missing, total = missing_words(old_text, new_text)
    return total > 0 and missing >= MISSING_MIN and missing / total > MISSING


class PageTracker:
    def __init__(self, store: Store, eye: Eye | None, ocr, settings, *, sleep=asyncio.sleep,
                 settle_frames: int = 2, diff_threshold: float | None = None, interval_s: float = 0.4) -> None:
        # diff_threshold (mean grey diff at 64×64) defaults to PAGE_DIFF_THRESHOLD (6.0). Measured in P-3 on the
        # desk camera (2026-10-20): consecutive stills of a still scene differ by 2.3–3.0 (sensor + JPEG noise),
        # a hand or a person moving by 37–66; two different PIL-rendered pages differ by ~1.7, so tests pass 1.0.
        # A quiet page turn in a wide shot (the page is ~20 % of the frame) stays below the noise and is caught
        # by the learner's "next page", not by pixels.
        self.store = store
        self.eye = eye
        self.ocr = ocr
        self.settings = settings
        self._sleep = sleep
        self.settle_frames = settle_frames
        self.diff_threshold = float(getattr(settings, "page_diff_threshold", 6.0)) if diff_threshold is None \
            else diff_threshold
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

    async def _ocr(self, frame: Frame):
        try:
            return await asyncio.wait_for(self.ocr.read(frame), OCR_TIMEOUT_S)
        except TimeoutError:
            log.warning("OCR took longer than %.0f s; the page is treated as not seen", OCR_TIMEOUT_S)
            return None

    async def read(self):
        """Settle and OCR; when the read needs help, recapture once, but only if the frame changed (an unchanged
        frame would read the same: the learner is asked at once). Returns (frame, result) or (None, None)."""
        frame = await self.settle()
        if frame is None or self.ocr is None:
            return None, None
        result = await self._ocr(frame)
        if result is None:
            return None, None
        if result.needs_help(self.settings.ocr_min_confidence):
            again = await self.settle()
            if again is not None and frame_diff(frame, again) >= self.diff_threshold:
                log.info("OCR needs help (state %s, confidence %.2f); the frame changed: reading again",
                         result.state, result.confidence)
                second = await self._ocr(again)
                if second is None:
                    return None, None
                frame, result = again, second
        return frame, result

    async def find(self, book_id: int, expected_number: int | None = None) -> PageFound:
        frame, result = await self.read()
        if frame is None:
            return PageFound("unavailable", message="I can't see the page. Which page are you on? (/page N)")
        self.last = frame
        if result.needs_help(self.settings.ocr_min_confidence):
            return PageFound("low_confidence",
                             message="The page is hard for me to read. Read me the first line, or type the page.")
        number, body = split_number(result.lines, self.settings.ocr_min_confidence)
        text = "\n".join(body)
        obs = pages.observations_of(text)
        match = pages.match_page(self.store, book_id, obs, number)
        if match.status == "matched":
            stored = pages.current_text(self.store, match.page_id)
            if stored is not None and is_partial(stored, text):
                log.info("OCR read lost words of stored page %s; no revision added", match.page_id)
                return PageFound("low_confidence", match.page_id, message=PARTIAL_MESSAGE)
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
