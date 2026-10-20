"""动作编辑界面:`python -m agent.webui` → 浏览器打开 http://127.0.0.1:8770

只监听回环地址,单用户本地工具,故不做鉴权。用标准库 http.server 而不是 FastAPI:
统共两个接口,不值得为它多两个运行时依赖。

界面改的是 config/tasks.yml。agent 读该文件带 mtime 检查,所以阈值/判据/话术/提问
改完即时生效;**只有排程时刻要重启 agent**(APScheduler 的 job 在启动时注册)。
"""
import json
import logging
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/tasks":
            self._json(200, {"tasks": [s.to_dict() for s in all_specs()], "meta": _meta()})
        else:
            self._json(404, {"error": "没有这个地址"})

    def do_POST(self) -> None:
        if self.path != "/api/tasks":
            self._json(404, {"error": "没有这个地址"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
            specs = [TaskSpec.from_dict(d) for d in payload.get("tasks", [])]
        except (ValueError, TypeError) as e:
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


def main() -> None:
    seed_defaults()  # 首次运行:把内置默认(含话术与终裁提问)落成 tasks.yml
    url = f"http://{HOST}:{PORT}/"
    with ThreadingHTTPServer((HOST, PORT), Handler) as httpd:
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
