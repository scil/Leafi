"""动作编辑界面:`python -m agent.webui` → 浏览器打开 http://127.0.0.1:8770

只监听回环地址,单用户本地工具,故不做鉴权。用标准库 http.server 而不是 FastAPI:
统共两个接口,不值得为它多两个运行时依赖。

界面改的是 config/tasks.yml。agent 读该文件带 mtime 检查,所以阈值/判据/话术/提问
改完即时生效;**只有排程时刻要重启 agent**(APScheduler 的 job 在启动时注册)。

第二个标签页编辑 .env(leafi/envedit.py,设计见 docs/plans/active/2026-10-21-env-settings-page.md)。
只听回环挡不住"浏览器里别的网页"往 127.0.0.1 发请求,所以每个请求都查 Host,
POST 再查 Content-Type、Origin 和启动时生成、嵌在页面里的 token(§6)。

第三个标签页"OCR"只读:页面文字的每个版本(新的在前)和相对上一版改了哪些词(leafi/study/page_history.py)。
它的两个 GET 也要 token:页面照片拍的是家里,别的网页不能用 <img> 把它载进来(主人 2026-10-25:点了才看照片)。
`--tab ocr` 直接打开这一页;服务已经在跑时只开浏览器。

The fourth tab, "Reading" (`--tab read`), is the session panel (docs/plans/active/2026-10-25-study-session-panel-design.md
D5, D6): it shows the live study session started with `python -m leafi study --panel` and sends it typed lines from a
fixed table (`agent/webui/study.py`). Its status needs the page token; its actions need our Origin too.
"""
import argparse
import json
import logging
import os
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from leafi import envedit

from . import study

from ..config import settings
from ..tasks import (
    BUILTIN_PROMPT_KINDS,
    PHRASE_KINDS,
    SCORER_FIELDS,
    VERIFY_MODES,
    TaskSpec,
    all_specs,
    save,
    seed_defaults,
    validate_all,
)
from ..vision.scorer import PRESETS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-9s %(message)s")
log = logging.getLogger("webui")

HOST, PORT = "127.0.0.1", 8770
PAGE = Path(__file__).with_name("index.html")
TABS = ("tasks", "env", "ocr", "read")


def _ocr_store(settings_factory):
    """(leafi Settings, an open Store) or (Settings, None) when there is no database yet; never creates one."""
    from leafi.core.storage import Store

    s = settings_factory()
    return s, (Store(s.db_path) if s.db_path.exists() else None)


def _leafi_settings():
    from leafi.core.config import Settings

    return Settings()


def _meta() -> dict:
    """界面要用的选项与默认值,免得前端把规则再抄一遍。"""
    return {
        "verifyModes": list(VERIFY_MODES),
        "phraseKinds": list(PHRASE_KINDS),
        "scorerFields": list(SCORER_FIELDS),
        "presets": PRESETS,
        "builtinPromptKinds": list(BUILTIN_PROMPT_KINDS),
        "globals": {
            "target_active_seconds": settings.target_active_seconds,
            "min_visible_active_seconds": settings.min_visible_active_seconds,
            "inside_credit_cap": settings.inside_credit_cap,
            "verify_window_s": settings.verify_window_s,
            "verify_mode": settings.verify_mode,
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "LeafiTaskEditor/1.0"

    def log_message(self, fmt, *args):  # 用项目的 logger,别往 stderr 刷原始格式
        log.info("%s %s", self.address_string(), fmt % args)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        # charset 必须写:浏览器按规范默认 UTF-8,但严格的 HTTP 客户端会猜成 Latin-1,
        # 中文全变问号(界面看着好好的,curl/PowerShell 拿到的却是乱码)。
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    # ---- request checks (design §6): a failed check is a bare 403
    def _origins(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self._origins()

    def _post_ok(self) -> bool:
        origin = self.headers.get("Origin")
        fetch_site = self.headers.get("Sec-Fetch-Site")  # another 127.0.0.1 port is `same-site`: refused too
        return (self._host_ok()
                and (self.headers.get("Content-Type") or "").split(";")[0].strip() == "application/json"
                and (origin is None or origin in {f"http://{o}" for o in self._origins()})
                and (fetch_site is None or fetch_site in ("same-origin", "none"))
                and secrets.compare_digest(self.headers.get("X-Leafi-Token", ""), self.server.token))

    def _origin_present(self) -> bool:
        """The Reading tab's actions move a child's session: a missing Origin is not taken as our own page."""
        return self.headers.get("Origin") in {f"http://{o}" for o in self._origins()}

    def _token_ok(self) -> bool:
        return self._host_ok() and secrets.compare_digest(self.headers.get("X-Leafi-Token", ""), self.server.token)

    def _ocr(self, query: dict) -> None:
        """GET /api/ocr (the revisions) and /api/ocr/image?id=N (one still); read-only, the store closed after."""
        from leafi.core.storage import DatabaseInUse, SchemaError
        from leafi.study import page_history

        image = query.get("id", [None])[0] if self.path.startswith("/api/ocr/image") else None
        try:
            settings_, store = _ocr_store(self.server.leafi_settings)
        except (SchemaError, DatabaseInUse) as e:
            self._json(200, {"revisions": [], "error": str(e)})
            return
        if store is None:
            self._json(200, {"revisions": [], "error": f"还没有数据库 {settings_.db_path}"})
            return
        try:
            if image is None:
                self._json(200, {"revisions": page_history.revisions(store)})
                return
            path = page_history.image_file(store, int(image), Path(settings_.cache_dir) / "pages") \
                if image.isdigit() else None
        finally:
            store.close()
        if path is None:
            self._json(404, {"error": "照片已过保留期被删除,或不存在"})
            return
        self._send(200, path.read_bytes(), page_history.IMAGE_TYPES[path.suffix.lower()])

    def _forbidden(self) -> None:
        # 先读掉请求体再回 403:不读就关连接,Windows 会发 RST,客户端连 403 都收不到
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 1 << 20)
            if n:
                self.rfile.read(n)
        except (ValueError, OSError):
            pass
        self._send(403, b"", "text/plain")

    def _body(self) -> dict:
        """请求体必须是 JSON 对象;其它一律 ValueError(过深的嵌套 json 会抛 RecursionError,也归到这里)。"""
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except RecursionError:
            raise ValueError("JSON nested too deeply") from None
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        return body

    def do_GET(self) -> None:
        if not self._host_ok():
            self._forbidden()
            return
        if self.path in ("/", "/index.html"):
            meta = f'<meta name="leafi-token" content="{self.server.token}">\n</head>'
            self._send(200, PAGE.read_text(encoding="utf-8").replace("</head>", meta, 1).encode("utf-8"),
                       "text/html; charset=utf-8")
        elif self.path == "/api/tasks":
            self._json(200, {"tasks": [s.to_dict() for s in all_specs()], "meta": _meta()})
        elif self.path == "/api/env":
            self._json(200, envedit.view(self.server.env_path))
        elif urlsplit(self.path).path in ("/api/ocr", "/api/ocr/image"):
            if not self._token_ok():
                self._forbidden()
                return
            self._ocr(parse_qs(urlsplit(self.path).query))
        elif urlsplit(self.path).path == "/api/study/status":
            if not self._token_ok():  # the child's words and name: other pages may not read them
                self._forbidden()
                return
            since = parse_qs(urlsplit(self.path).query).get("since", [None])[0]
            code, view = study.status(self.server.leafi_settings(), since)
            if code == 204:
                self._send(204, b"", "application/json")
            else:
                self._json(code, view)
        else:
            self._json(404, {"error": "没有这个地址"})

    def do_POST(self) -> None:
        if not self._post_ok():
            self._forbidden()
            return
        if self.path == "/api/env":
            try:
                payload = self._body()
            except ValueError:
                self._json(400, {"ok": False, "error": "请求体不是 JSON"})
                return
            result = envedit.save(payload, path=self.server.env_path, data_dir=self.server.data_dir)
            self._json(result.status, result.body)
            return
        if self.path == "/api/study/action":
            if not self._origin_present():
                self._forbidden()
                return
            try:
                payload = self._body()
            except ValueError:
                self._json(400, {"error": "the body is not a JSON object"})
                return
            code, result = study.action(self.server.leafi_settings(), payload)
            self._json(code, result)
            return
        if self.path != "/api/tasks":
            self._json(404, {"error": "没有这个地址"})
            return
        try:
            payload = self._body()
            specs = [TaskSpec.from_dict(d) for d in payload.get("tasks", [])]
        except (ValueError, TypeError, AttributeError) as e:
            self._json(400, {"error": f"请求体解析失败:{e}"})
            return

        errors = validate_all(specs)
        if errors:
            self._json(200, {"ok": False, "errors": errors})
            return
        try:
            save(specs)
        except OSError as e:
            self._json(500, {"error": f"写 config/tasks.yml 失败:{e}"})
            return
        log.info("已保存 %d 个动作", len(specs))
        self._json(200, {"ok": True, "tasks": [s.to_dict() for s in all_specs()]})


class _Server(ThreadingHTTPServer):
    # Windows 上 SO_REUSEADDR 允许第二个进程绑同一端口(2026-10-25 实测:第二次 bind 成功),两个界面会同时"在跑";
    # 关掉它,第二次启动才会失败,main() 才能改成只开浏览器。别的系统保留(重启时免等 TIME_WAIT)。
    allow_reuse_address = os.name != "nt"


def make_server(host: str = HOST, port: int = PORT, env_path: Path = Path(".env"),
                data_dir: Path = Path("data"), leafi_settings=_leafi_settings) -> ThreadingHTTPServer:
    httpd = _Server((host, port), Handler)
    httpd.token = secrets.token_urlsafe(32)  # 每次启动换一个;页面从 <meta> 里读
    httpd.env_path, httpd.data_dir = env_path, data_dir
    httpd.leafi_settings = leafi_settings  # 每次请求现读:.env 改了数据库路径也跟得上
    return httpd


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Leafi 动作与设置界面")
    p.add_argument("--tab", choices=TABS, default="tasks", help="打开哪个标签页")
    args = p.parse_args(argv)
    seed_defaults()  # 首次运行:把内置默认(含话术与终裁提问)落成 tasks.yml
    url = f"http://{HOST}:{PORT}/" + ("" if args.tab == "tasks" else f"#{args.tab}")
    try:
        server = make_server(HOST, PORT)
    except OSError:  # 已经有一个在跑(端口被占):只把浏览器开到那一页
        log.info("界面已在运行,打开 %s", url)
        webbrowser.open(url)
        return
    with server as httpd:
        log.info("动作编辑界面已启动:%s (Ctrl+C 退出)", url)
        try:
            webbrowser.open(url)
        except Exception:  # 没有默认浏览器时不该让服务起不来
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            log.info("已退出")


if __name__ == "__main__":
    main()
