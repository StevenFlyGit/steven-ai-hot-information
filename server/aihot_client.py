"""AIHOT 上游极薄客户端。

职责（严格遵循移交文档「极薄代理」红线）：
- 同域转发 AIHOT 匿名只读 v1 API（仅 GET）。
- 附 ETag / If-None-Match；上游返回 304 时复用缓存（短路，不再传输 body）。
- 同端点轮询间隔下限（默认 60s）节流，降低上游压力。
- 上游不可达时回退到内置 fixture（真实抓取的样例响应），并标注 X-AIHOT-Source: fixture，
  避免前端白屏；fixture 与真实数据明确区分，不伪装成实时数据。

不落库、不改写来源内容；来源署名随响应透传。
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

from config import CONFIG

# fixture 目录：存放真实抓取样例，仅作「上游不可达」时的离线回退
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

# 全局礼貌限速：两次上游调用之间的最小间隔（秒），避免突发打爆上游
GLOBAL_MIN_GAP = 0.2


@dataclass
class CacheEntry:
    etag: Optional[str]
    body: str
    ts: float


@dataclass
class ProxyResult:
    status: int
    body: str
    source: str  # "upstream" | "cache" | "fixture" | "error"
    content_type: str = "application/json; charset=utf-8"


class AihotClient:
    """线程安全的上游转发 + 缓存控制器。"""

    def __init__(self) -> None:
        self._cache: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()
        self._last_global = 0.0

    # ---------------------------------------------------------------- fixture
    @staticmethod
    def _resolve_fixture(proxy_path: str) -> Optional[str]:
        """根据 proxy 路径（不含查询串）映射到 fixture 文件。

        注意：fixture 仅用于离线回退演示，不代表实时数据；
        同名端点（如不同 window/category）共用同一份样例。
        """
        if proxy_path == "/items":
            return "items_selected_24h.json"
        if proxy_path == "/hot-topics":
            return "hot_topics.json"
        if proxy_path == "/stories" or proxy_path.startswith("/stories/"):
            return "story_sample.json"
        if proxy_path == "/dailies":
            return "dailies_index.json"
        if proxy_path.startswith("/dailies/"):
            return "daily_report.json"
        return None

    @staticmethod
    def _load_fixture(name: str) -> Optional[str]:
        path = os.path.join(FIXTURE_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return None

    # ---------------------------------------------------------------- 节流
    def _throttle_global(self) -> None:
        with self._lock:
            now = time.time()
            wait = GLOBAL_MIN_GAP - (now - self._last_global)
            if wait > 0:
                time.sleep(wait)
            self._last_global = time.time()

    # ---------------------------------------------------------------- 上游
    @staticmethod
    def _request_upstream(url: str, etag: Optional[str]):
        """发起一次上游 GET。

        返回 (status, body_or_None, etag_or_None, error_or_None)。
        - 2xx：返回 body 与 ETag。
        - 4xx/5xx：返回状态码与错误体（可能为空），error=None（交由调用方决定是否回退）。
        - 网络/超时异常：status=None，error 为异常信息。
        """
        headers = {
            "User-Agent": CONFIG.user_agent,
            "Accept": "application/json",
        }
        if etag:
            headers["If-None-Match"] = etag
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return resp.status, raw, resp.headers.get("ETag"), None
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read().decode("utf-8", "replace")
            except Exception:
                raw = ""
            return exc.code, raw, None, None
        except Exception as exc:  # 超时 / DNS / 连接失败
            return None, None, None, f"{type(exc).__name__}: {exc}"

    # ---------------------------------------------------------------- 入口
    def proxy(self, proxy_path: str, query_string: str) -> ProxyResult:
        """统一转发入口。

        :param proxy_path: 形如 /items、/stories/<id>、/dailies/<date>（不含 /api/proxy 前缀）
        :param query_string: 原始查询串（已编码），直接透传给上游
        """
        cache_key = proxy_path + ("?" + query_string if query_string else "")
        url = CONFIG.upstream_base + CONFIG.api_prefix + proxy_path
        if query_string:
            url += "?" + query_string

        now = time.time()
        with self._lock:
            cached = self._cache.get(cache_key)

        # 节流：同端点 60s 内且有缓存 → 直接复用，不再打上游（满足轮询间隔下限）
        if cached is not None and (now - cached.ts) < CONFIG.min_poll_interval:
            return ProxyResult(200, cached.body, "cache")

        # 正常路径：打上游（携带缓存 ETag 以支持 304 复用）
        self._throttle_global()
        status, body, etag, err = self._request_upstream(
            url, cached.etag if cached else None
        )

        # 304：内容未变，复用缓存并刷新时间戳
        if status == 304 and cached is not None:
            with self._lock:
                self._cache[cache_key] = CacheEntry(cached.etag, cached.body, now)
            return ProxyResult(200, cached.body, "cache")

        # 200：更新缓存
        if status == 200 and body is not None:
            with self._lock:
                self._cache[cache_key] = CacheEntry(etag, body, now)
            return ProxyResult(200, body, "upstream")

        # 上游失败（网络/超时/5xx）→ fixture 离线回退（明确标注，不伪装实时）
        if err is not None or status is None or (status >= 500):
            fb_name = self._resolve_fixture(proxy_path)
            if fb_name:
                fb = self._load_fixture(fb_name)
                if fb is not None:
                    with self._lock:
                        self._cache[cache_key] = CacheEntry(None, fb, now)
                    return ProxyResult(200, fb, "fixture")
            err_body = json.dumps(
                {"error": "upstream_unavailable", "detail": err or f"status={status}"},
                ensure_ascii=False,
            )
            return ProxyResult(502, err_body, "error")

        # 上游 4xx（如非法参数）：原样透传给前端，不回退 fixture
        return ProxyResult(status or 500, body or "", "upstream")


CLIENT = AihotClient()
