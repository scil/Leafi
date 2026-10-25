"""The admin page's OCR tab: page-text versions newest first with their word changes, and a still only on request
(owner 2026-10-25), against the real server on an ephemeral port and a real store."""

import http.client
import json
import threading

import pytest

from agent.webui.__main__ import make_server
from leafi.core.storage import Store
from leafi.services.ocr.mock import MockOcr
from leafi.study import books, page_history
from leafi.study.page_tracker import PageTracker
from tests.fixtures.pages import FakeEye, render


async def _nosleep(_):
    return None


async def _two_reads(settings):
    """A page read twice by the camera: the second read fixes an OCR error, so it is a new revision."""
    store = Store(settings.db_path)
    book = books.find_or_create(store, "The Big Storm")
    eye = FakeEye([])
    tracker = PageTracker(store, eye, MockOcr(), settings, sleep=_nosleep)
    text = "The wind blew through the trees.\nThe leaves fell down."
    eye.show(render(text, number=7, ocr_text=text.replace("through", "though")))
    await tracker.find(book)
    eye.show(render(text, number=7))
    found = await tracker.find(book)
    store.close()
    return found.page_id


def test_word_changes_mark_removed_and_added_words():
    assert page_history.word_changes("The wind blew though the trees.", "The wind blew through the trees.") == [
        ("=", "The wind blew"), ("-", "though"), ("+", "through"), ("=", "the trees.")]


async def test_revisions_come_newest_first_with_changes_and_their_still(settings):
    page_id = await _two_reads(settings)
    with Store(settings.db_path) as store:
        revs = page_history.revisions(store)
        assert [(r["page_id"], r["rev"], r["current"]) for r in revs] == [(page_id, 2, True), (page_id, 1, False)]
        assert revs[0]["changes"] == [["=", "The wind blew"], ["-", "though"], ["+", "through"],
                                      ["=", "the trees. The leaves fell down."]]
        assert revs[1]["changes"] is None and revs[0]["printed_number"] == 7 and revs[0]["book"] == "The Big Storm"
        assert revs[0]["image_id"] is not None and revs[0]["image_id"] != revs[1]["image_id"]
        path = page_history.image_file(store, revs[0]["image_id"], settings.cache_dir / "pages")
        assert path is not None and path.read_bytes()[:4] == b"\x89PNG"


async def test_an_image_row_outside_the_page_folder_is_never_served(settings, tmp_path):
    await _two_reads(settings)
    secret = tmp_path / "elsewhere.png"
    secret.write_bytes(b"\x89PNG not a page")
    with Store(settings.db_path) as store:
        store.insert("page_images", page_id=1, path=str(secret), width=1, captured_at="2026-10-25T00:00:00")
        bad = store.one("SELECT MAX(id) AS id FROM page_images")["id"]
        assert page_history.image_file(store, bad, settings.cache_dir / "pages") is None
        assert page_history.image_file(store, 9999, settings.cache_dir / "pages") is None


@pytest.fixture
def server(settings, tmp_path):
    httpd = make_server("127.0.0.1", 0, env_path=tmp_path / ".env", data_dir=tmp_path / "data",
                        leafi_settings=lambda: settings)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def call(httpd, path, token=True):
    port = httpd.server_address[1]
    headers = {"Host": f"127.0.0.1:{port}"}
    if token:
        headers["X-Leafi-Token"] = httpd.token
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", path, headers=headers)
    r = c.getresponse()
    data, ctype = r.read(), r.getheader("Content-Type")
    c.close()
    return r.status, ctype, data


def test_no_database_yet_is_an_empty_list_and_creates_nothing(server, settings):
    status, _, body = call(server, "/api/ocr")
    assert status == 200 and json.loads(body)["revisions"] == [] and not settings.db_path.exists()


async def test_the_api_lists_revisions_and_serves_a_still_only_with_the_token(server, settings):
    await _two_reads(settings)
    assert call(server, "/api/ocr", token=False)[0] == 403
    status, _, body = call(server, "/api/ocr")
    revs = json.loads(body)["revisions"]
    assert status == 200 and [r["rev"] for r in revs] == [2, 1]
    image = revs[0]["image_id"]
    assert call(server, f"/api/ocr/image?id={image}", token=False)[0] == 403  # an <img> from another page: refused
    status, ctype, data = call(server, f"/api/ocr/image?id={image}")
    assert status == 200 and ctype == "image/png" and data[:4] == b"\x89PNG"
    assert call(server, "/api/ocr/image?id=9999")[0] == 404
    assert call(server, "/api/ocr/image?id=../x")[0] == 404
    with Store(settings.db_path):  # the request closed its store: the lock is free for a writer again
        pass


def test_the_page_has_the_ocr_tab(server):
    status, _, page = call(server, "/", token=False)
    assert status == 200 and "OCR 识别".encode() in page and b"/api/ocr" in page


def test_tab_ocr_opens_the_browser_at_the_tab_when_the_page_is_already_running(server, monkeypatch):
    from agent.webui import __main__ as webui

    opened = []
    monkeypatch.setattr(webui, "PORT", server.server_address[1])
    monkeypatch.setattr(webui, "seed_defaults", lambda: None)
    monkeypatch.setattr(webui.webbrowser, "open", opened.append)
    webui.main(["--tab", "ocr"])  # the port is taken by the running server: only the browser opens
    assert opened == [f"http://127.0.0.1:{server.server_address[1]}/#ocr"]
