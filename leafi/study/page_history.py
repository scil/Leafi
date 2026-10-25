"""Page text history for the admin page (`python -m agent.webui`, tab "OCR"): every page revision, newest first,
with the words it changed against the revision before.

Read-only. The caller opens the store for one request and closes it, so the web UI shares the database lock only
while it reads (`storage.py` names the web UI among the openers). Text only: a page image is handed out on request,
one at a time, and only from the page-image folder (owner 2026-10-25: the saved stills show the home).
"""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path

from leafi.core.storage import Store

IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def word_changes(old: str, new: str) -> list[tuple[str, str]]:
    """`new` against `old` as runs of ("=" | "-" | "+", words), split on whitespace so punctuation shows too."""
    a, b = old.split(), new.split()
    out: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            out.append(("=", " ".join(a[i1:i2])))
            continue
        if i2 > i1:
            out.append(("-", " ".join(a[i1:i2])))
        if j2 > j1:
            out.append(("+", " ".join(b[j1:j2])))
    return out


def revisions(store: Store, limit: int = 100) -> list[dict]:
    """The latest `limit` page revisions across all books, newest first."""
    rows = store.all(
        "SELECT r.id, r.page_id, r.rev, r.text, r.source, r.ocr_backend, r.ocr_confidence, r.created_at, "
        "p.printed_number, b.title FROM page_revisions r JOIN pages p ON p.id = r.page_id "
        "JOIN books b ON b.id = p.book_id ORDER BY r.created_at DESC, r.id DESC LIMIT ?", (int(limit),))
    out = []
    for r in rows:
        prev = store.one("SELECT rev, text FROM page_revisions WHERE page_id=? AND rev<? ORDER BY rev DESC LIMIT 1",
                         (r["page_id"], r["rev"]))
        last = store.one("SELECT MAX(rev) AS rev FROM page_revisions WHERE page_id=?", (r["page_id"],))["rev"]
        # `PageTracker.find` saves the still right after the OCR revision: the first image of the page from then on
        image = store.one("SELECT id FROM page_images WHERE page_id=? AND captured_at>=? ORDER BY captured_at, id "
                          "LIMIT 1", (r["page_id"], r["created_at"])) if r["source"] == "ocr" else None
        out.append({
            "revision_id": r["id"], "page_id": r["page_id"], "rev": r["rev"], "current": r["rev"] == last,
            "book": r["title"], "printed_number": r["printed_number"], "source": r["source"],
            "ocr_backend": r["ocr_backend"], "ocr_confidence": r["ocr_confidence"], "created_at": r["created_at"],
            "text": r["text"], "previous_rev": prev["rev"] if prev else None,
            "changes": [list(c) for c in word_changes(prev["text"], r["text"])] if prev else None,
            "image_id": image["id"] if image else None,
        })
    return out


def image_file(store: Store, image_id: int, pages_dir: Path) -> Path | None:
    """The saved still of `image_id`, only when it is a picture inside `pages_dir` and still on disk (the purge
    after PAGES_RETAIN_DAYS removes files and rows)."""
    row = store.one("SELECT path FROM page_images WHERE id=?", (int(image_id),))
    if row is None:
        return None
    path = Path(row["path"]).resolve()
    if path.suffix.lower() not in IMAGE_TYPES or not path.is_relative_to(pages_dir.resolve()) or not path.is_file():
        return None
    return path
