"""站点菜单（菜单栏）数据服务。

职责（严格遵循移交文档「极薄代理」红线：不落库、不改写来源内容）：
- 服务端组合「全量菜单」：**顶级导航**（精选 / 全量 / 热点榜 / 检索 / 日报）
  与其下的**分类子菜单**（模型 / 产品 / 论文 / 行业 / 技巧）构成层级结构。
- 「全量获取」：默认返回完整菜单树（不分页、不过滤），含所有菜单项与层级。
- 缓存：组合结果按 TTL 缓存（菜单为低频变更数据，默认 3600s），降低重复组合开销。
- 参数校验辅助：`flat` / `include` 等可选参数做白名单校验，非法值由路由层返回 400。
- 不触发 AIHOT 网络请求；分类词表取自 AIHOT 匿名只读 v1 API 的权威 taxonomy
  （移交文档 3.2 明确 category slug 固定 5 个，以真实 API 为准）。

----------------------------------------------------------------------
返回字段定义（GET /api/menu）
----------------------------------------------------------------------
顶层：
  schemaVersion  string  菜单 schema 版本（如 "1.0"）
  generatedAt    string  ISO8601 组合时间（含时区偏移）
  source         string  固定 "composed"（服务端组合，非上游实时）
  cache          object  缓存元信息 {hit:bool, ttl:int, age:int}
  menu           array   顶级菜单项（层级结构，见下）
  categories     array   分类词表扁平列表（见下）

菜单项（menu[] 元素，含 children 时即层级）：
  id        string   唯一标识（顶级如 "home"/"all"；分类如 "cat-ai-models-all"）
  label     string   展示文案（如 "精选" / "模型"）
  type      string   "view"（视图导航）| "category"（分类子菜单）
  mode      string|null  关联 items 的 mode（selected/all），非资讯类为 null
  route     string   前端 hash 路由（如 "#/home"、"#/search?mode=all&category=ai-models"）
  order     int     同级排序（升序）
  enabled   bool    是否启用
  parent    string|null  父级 id（顶级为 null；分类指向 home/all）
  children  array   子菜单项（分类），无则为空数组

分类词表（categories[] 元素）：
  slug   string   AIHOT category slug（真实取值，如 "ai-models"）
  label  string   中文展示名（如 "模型"）
  order  int      排序
  source string   词表来源（固定 "aihot"）
----------------------------------------------------------------------
"""
from __future__ import annotations

import datetime
import threading
import time
from dataclasses import dataclass
from typing import Optional

from config import CONFIG

SCHEMA_VERSION = "1.0"

# AIHOT 权威分类词表（移交文档 3.2：category slug 固定 5 个，以真实 API 为准）。
# 顺序即展示顺序；分类词表为菜单「全量获取」的可靠来源（非实时网络拉取）。
CATEGORY_TAXONOMY = [
    {"slug": "ai-models", "label": "模型"},
    {"slug": "ai-products", "label": "产品"},
    {"slug": "paper", "label": "论文"},
    {"slug": "industry", "label": "行业"},
    {"slug": "tip", "label": "技巧"},
]

# 顶级导航定义（含「全量」入口，对应 items 的 mode=all）。
# with_categories=True 表示该项展开分类子菜单。
NAV_DEFINITION = [
    {
        "id": "home", "label": "精选", "type": "view", "mode": "selected",
        "route": "#/home", "order": 1, "with_categories": True,
    },
    {
        "id": "all", "label": "全量", "type": "view", "mode": "all",
        "route": "#/search?mode=all", "order": 2, "with_categories": True,
    },
    {
        "id": "hot", "label": "热点榜", "type": "view", "mode": None,
        "route": "#/hot", "order": 3, "with_categories": False,
    },
    {
        "id": "search", "label": "检索", "type": "view", "mode": None,
        "route": "#/search", "order": 4, "with_categories": False,
    },
    {
        "id": "daily", "label": "日报", "type": "view", "mode": None,
        "route": "#/daily", "order": 5, "with_categories": False,
    },
]

# /api/menu 的 include 白名单分组
VALID_INCLUDE = ("nav", "categories")


def _now_iso() -> str:
    """当前时间的 ISO8601 字符串（含本地时区偏移）。"""
    return datetime.datetime.now().astimezone().isoformat()


def _category_children(parent_id: str, mode: str) -> list[dict]:
    """为某个父级（精选 / 全量）生成分类子菜单。

    :param parent_id: 父菜单 id（home / all）
    :param mode: 关联 items 的 mode（selected / all），用于路由拼装
    """
    children = []
    for idx, cat in enumerate(CATEGORY_TAXONOMY, start=1):
        children.append({
            "id": f"cat-{cat['slug']}-{parent_id}",
            "label": cat["label"],
            "type": "category",
            "slug": cat["slug"],
            "parent": parent_id,
            "mode": mode,
            "route": f"#/search?mode={mode}&category={cat['slug']}",
            "order": idx,
            "enabled": True,
            "children": [],
        })
    return children


@dataclass
class MenuCacheEntry:
    payload: dict
    ts: float


class MenuService:
    """线程安全的菜单组合 + 缓存控制器。"""

    def __init__(self) -> None:
        self._cache: Optional[MenuCacheEntry] = None
        self._lock = threading.Lock()

    # ----------------------------------------------------- 全量获取 / 组合
    def _acquire(self) -> dict:
        """全量获取并组合菜单树（服务端处理逻辑）。

        返回完整菜单结构（含层级）。菜单为低频数据，此处为纯服务端组合，
        不触发上游网络请求；分类词表取自 AIHOT 权威 taxonomy（见 CATEGORY_TAXONOMY）。
        """
        nav = []
        for item in NAV_DEFINITION:
            node = {
                "id": item["id"],
                "label": item["label"],
                "type": item["type"],
                "mode": item["mode"],
                "route": item["route"],
                "order": item["order"],
                "enabled": True,
                "parent": None,
                "children": (
                    _category_children(item["id"], item["mode"])
                    if item.get("with_categories")
                    else []
                ),
            }
            nav.append(node)

        categories = [
            {
                "slug": c["slug"],
                "label": c["label"],
                "order": i + 1,
                "source": "aihot",
            }
            for i, c in enumerate(CATEGORY_TAXONOMY)
        ]

        return {
            "schemaVersion": SCHEMA_VERSION,
            "generatedAt": _now_iso(),
            "source": "composed",  # 服务端组合，非上游实时
            "categories": categories,
            "menu": nav,
        }

    # ---------------------------------------------------------------- 入口
    def get_menu(self, force: bool = False) -> dict:
        """返回全量菜单（带缓存）。

        :param force: True 时忽略缓存，强制重新组合（用于刷新场景）
        """
        now = time.time()
        with self._lock:
            cached = self._cache
        fresh = False
        if not force and cached is not None and (now - cached.ts) < CONFIG.menu_cache_ttl:
            payload = dict(cached.payload)
        else:
            payload = self._acquire()
            with self._lock:
                self._cache = MenuCacheEntry(payload, now)
            fresh = True
        payload = dict(payload)
        payload["cache"] = {
            "hit": (not fresh),
            "ttl": CONFIG.menu_cache_ttl,
            "age": 0 if fresh else int(now - cached.ts),  # type: ignore[union-attr]
        }
        return payload

    def refresh(self) -> dict:
        """强制刷新菜单缓存并返回最新组合结果。"""
        return self.get_menu(force=True)


MENU_SERVICE = MenuService()


# ----------------------------------------------------------- 输出变换 / 校验
def parse_flat(raw: Optional[str]) -> Optional[bool]:
    """校验并解析 flat 参数。

    仅接受 "1" / "true"（→ True）、"0" / "false"（→ False）；未提供返回 None。
    其余取值视为非法，返回特殊标记字符串 "INVALID" 供路由层判 400。
    """
    if raw is None:
        return None
    v = raw.strip().lower()
    if v in ("1", "true"):
        return True
    if v in ("0", "false"):
        return False
    return "INVALID"  # type: ignore[return-value]


def parse_include(raw: Optional[str]) -> tuple[str, ...] | str:
    """校验并解析 include 参数（分组白名单）。

    合法分组：nav / categories，逗号分隔。
    返回合法分组元组；若包含未知分组，返回 "INVALID" 供路由层判 400；
    未提供则返回全部合法分组。
    """
    if raw is None:
        return VALID_INCLUDE
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return VALID_INCLUDE
    if any(p not in VALID_INCLUDE for p in parts):
        return "INVALID"  # type: ignore[return-value]
    # 保持白名单固定顺序，去重
    return tuple(p for p in VALID_INCLUDE if p in parts)


def flatten_menu(menu: list[dict]) -> list[dict]:
    """将层级菜单拍平为单层列表（分类项保留 parent 指向父级 id）。"""
    out: list[dict] = []
    for node in menu:
        flat_node = {k: v for k, v in node.items() if k != "children"}
        flat_node["parent"] = node.get("parent")
        out.append(flat_node)
        for child in node.get("children", []):
            out.append(dict(child))
    return out


def transform(payload: dict, flat: bool, include: tuple[str, ...]) -> dict:
    """按 flat / include 参数变换输出（不影响缓存中的原始 payload）。"""
    result: dict = {
        "schemaVersion": payload["schemaVersion"],
        "generatedAt": payload["generatedAt"],
        "source": payload["source"],
        "cache": payload.get("cache"),
    }
    if "nav" in include:
        result["menu"] = flatten_menu(payload["menu"]) if flat else payload["menu"]
    if "categories" in include:
        result["categories"] = payload["categories"]
    return result
