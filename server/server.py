"""AIHOT 资讯平台 · 极薄后端代理 + 同源静态资源服务。

技术选型：Python 标准库（http.server + urllib），**零三方依赖**，保证开箱即跑。
职责：
- 同源托管 web/ 静态站点，浏览器经自有代理转发，规避 AIHOT 的 CORS 限制。
- /api/proxy/<path> 转发 AIHOT 匿名只读 v1 API（ETag 缓存 + 60s 节流 + fixture 回退）。
- /api/health 健康检查。

启动：
    python server/server.py
自定义端口 / 上游：
    PORT=8080 AIHOT_UPSTREAM=https://aihot.virxact.com python server/server.py
"""
from __future__ import annotations

import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from aihot_client import CLIENT
from config import CONFIG
from menu import (
    MENU_SERVICE,
    VALID_INCLUDE,
    parse_flat,
    parse_include,
    transform,
)

# 仅允许转发到 AIHOT 已知只读端点，避免被当作开放代理（SSRF 防护）
ALLOWED_PREFIXES = ("/items", "/hot-topics", "/stories", "/dailies")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "aihot-proxy/1.0"
    protocol_version = "HTTP/1.1"

    # 简化访问日志（保留错误可见性由调用方处理）
    def log_message(self, fmt: str, *args) -> None:  # noqa: D102
        return

    # ----------------------------------------------------------------- 响应
    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str,
        extra_headers: dict | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # 同源即可，附加宽松 CORS 便于前端独立托管时也兼容
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for key, val in extra_headers.items():
                self.send_header(key, val)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # ----------------------------------------------------------------- 静态
    def _serve_static(self, path: str) -> None:
        if path in ("/", ""):
            path = "/index.html"
        # 规范化并禁止目录穿越
        rel = os.path.normpath(path).lstrip("/\\")
        full = os.path.join(CONFIG.web_dir, rel)
        abs_web = os.path.abspath(CONFIG.web_dir)
        if not os.path.abspath(full).startswith(abs_web):
            self._send(403, b"Forbidden", "text/plain; charset=utf-8")
            return
        if not os.path.isfile(full):
            # SPA 兜底：未知路径回退首页（hash 路由本身不会触发，保留健壮性）
            full = os.path.join(abs_web, "index.html")
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        try:
            with open(full, "rb") as fh:
                data = fh.read()
        except OSError:
            self._send(404, b"Not Found", "text/plain; charset=utf-8")
            return
        self._send(200, data, ctype)

    # ----------------------------------------------------------------- 菜单
    def _serve_menu(self, parsed: "urllib.parse.ParseResult") -> None:
        """GET /api/menu —— 返回全量菜单（含层级结构）。

        可选查询参数（均做白名单校验）：
          flat=1|true|0|false   是否将层级菜单拍平为单层列表（默认树形）
          include=nav,categories 仅返回指定分组（默认全部；合法值 nav / categories）
          refresh=1|true        忽略缓存，强制重新组合

        参数非法 → 400（error=invalid_param）；服务端组合异常 → 500（error=internal）。
        """
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        def first(name: str) -> str | None:
            vals = qs.get(name)
            return vals[0] if vals else None

        flat = parse_flat(first("flat"))
        if flat == "INVALID":  # type: ignore[comparison-overlap]
            self._send(
                400,
                '{"error":"invalid_param","detail":"flat 仅接受 1/true/0/false"}'
                .encode("utf-8"),
                "application/json; charset=utf-8",
            )
            return

        include = parse_include(first("include"))
        if include == "INVALID":  # type: ignore[comparison-overlap]
            allowed = ",".join(VALID_INCLUDE)
            self._send(
                400,
                ('{"error":"invalid_param","detail":"include 仅接受 %s"}' % allowed)
                .encode("utf-8"),
                "application/json; charset=utf-8",
            )
            return

        refresh = parse_flat(first("refresh"))
        force = refresh is True

        try:
            payload = MENU_SERVICE.get_menu(force=force)
        except Exception as exc:  # 组合失败兜底，避免白屏/500 裸露
            err = json.dumps(
                {"error": "internal", "detail": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            ).encode("utf-8")
            self._send(500, err, "application/json; charset=utf-8")
            return

        out = transform(payload, flat is True, include)  # type: ignore[arg-type]
        body = json.dumps(out, ensure_ascii=False).encode("utf-8")
        self._send(200, body, "application/json; charset=utf-8")

    # ----------------------------------------------------------------- 路由
    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        p = parsed.path

        if p == "/api/health":
            payload = (
                '{"ok":true,"upstream":"%s","apiPrefix":"%s","mode":"proxy"}'
                % (CONFIG.upstream_base, CONFIG.api_prefix)
            ).encode("utf-8")
            self._send(200, payload, "application/json; charset=utf-8")
            return

        if p == "/api/menu":
            self._serve_menu(parsed)
            return

        if p.startswith("/api/proxy"):
            proxy_path = p[len("/api/proxy"):]  # 含可能的前导 "/"
            pp = urllib.parse.urlparse(proxy_path)
            path_only = pp.path
            # 查询串以浏览器原始查询为准（已编码，直接透传）
            query = pp.query or parsed.query

            allowed = any(
                path_only == pre or path_only.startswith(pre + "/")
                for pre in ALLOWED_PREFIXES
            )
            if not allowed:
                self._send(
                    404,
                    b'{"error":"unknown_proxy_path"}',
                    "application/json; charset=utf-8",
                )
                return

            result = CLIENT.proxy(path_only, query)
            self._send(
                result.status,
                result.body.encode("utf-8")
                if isinstance(result.body, str)
                else result.body,
                "application/json; charset=utf-8",
                extra_headers={"X-AIHOT-Source": result.source},
            )
            return

        self._serve_static(p)

    do_HEAD = do_GET  # noqa: N815


def main() -> None:
    server = ThreadingHTTPServer((CONFIG.host, CONFIG.port), Handler)
    url = f"http://localhost:{CONFIG.port}"
    print("AIHOT 资讯代理已启动")
    print(f"  前端入口 : {url}/")
    print(f"  代理前缀 : {url}/api/proxy/...")
    print(f"  上游接口 : {CONFIG.upstream_base}{CONFIG.api_prefix}")
    print(f"  缓存 TTL : {CONFIG.cache_ttl}s · 同端点节流 : {CONFIG.min_poll_interval}s")
    print("  Ctrl+C 退出")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
