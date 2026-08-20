"""本地开发服务器 · 模拟 ESA Pages 回源代理行为。

职责：
- 托管 web/ 静态文件（模拟 ESA Pages）
- /api/* 请求代理到后端 FC 函数（模拟 ESA 回源规则）

启动：
    python dev-server.py

访问：http://localhost:8080/
"""
from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:9000")
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
PORT = int(os.environ.get("PORT", "8080"))

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class DevHandler(BaseHTTPRequestHandler):
    server_version = "aihot-dev/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        path = args[0] if args else ""
        if "/api/" in str(path):
            print(f"  [API] {args[0]} {args[1]} {args[2]}")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        p = parsed.path

        # /api/* → 代理到后端（模拟 ESA 回源）
        if p.startswith("/api/"):
            self._proxy_to_backend()
            return

        # 其他路径 → 静态文件
        self._serve_static(p)

    do_HEAD = do_GET  # noqa: N815

    def _proxy_to_backend(self) -> None:
        """将 /api/* 请求转发到后端 FC 函数。"""
        url = BACKEND + self.path
        try:
            req = urllib.request.Request(url, headers={
                "Accept": self.headers.get("Accept", "application/json"),
            })
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read()
                self.send_response(resp.status)
                # 透传关键响应头
                for h in ("Content-Type", "X-AIHOT-Source", "Cache-Control"):
                    val = resp.headers.get(h)
                    if val:
                        self.send_header(h, val)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
        except urllib.error.HTTPError as exc:
            body = exc.read() if exc.fp else b""
            self.send_response(exc.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except Exception as exc:
            msg = f'{{"error":"backend_unreachable","detail":"{exc}"}}'.encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(msg)

    def _serve_static(self, path: str) -> None:
        """托管 web/ 目录的静态文件。"""
        if path in ("/", ""):
            path = "/index.html"
        rel = os.path.normpath(path).lstrip("/\\")
        full = os.path.join(WEB_DIR, rel)
        abs_web = os.path.abspath(WEB_DIR)
        if not os.path.abspath(full).startswith(abs_web):
            self.send_response(403)
            self.end_headers()
            return
        if not os.path.isfile(full):
            full = os.path.join(WEB_DIR, "index.html")
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        try:
            with open(full, "rb") as fh:
                data = fh.read()
        except OSError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), DevHandler)
    print(f"AIHOT 本地开发环境已启动")
    print(f"  前端入口 : http://localhost:{PORT}/")
    print(f"  后端代理 : {BACKEND}（模拟 ESA 回源）")
    print(f"  Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
