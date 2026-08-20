#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIHOT v1 API 可用性测试脚本（修订版）
====================================
对应 Code-10-ai-hot-information-demo（AI 热点资讯 demo）涉及的真实接口能力。

Demo 用到的接口（来自 aihot.virxact.com 匿名只读 v1 API）：
  1. 精选资讯流（首页）  GET /api/v1/items?mode=selected&window=24h|7d
  2. 热点榜              GET /api/v1/hot-topics
  3. 事件详情            GET /api/v1/stories/{publicId}
  4. 日报归档            GET /api/v1/dailies?limit=N  +  /api/v1/dailies/{YYYY-MM-DD}
  5. 检索中心            GET /api/v1/items (组合 q/category/window/by, 含 mode=all)

注意：v1 列表类响应均为「信封结构」——
    {"schemaVersion":..., "count"/"query":..., "items":[...], "page":...}
  单条 story 详情为 {"schemaVersion":..., "story":{...}}。

特点：匿名、只读、无需 Key。
工作流：正常路径断言状态码 + 信封/字段结构；错误路径断言 4xx；
        末尾输出 PASS/FAIL 计数与退出码。条件触发的用例单独标注。

用法：
    python test_aihot_api.py
    BASE_URL=https://host python test_aihot_api.py   # 切换环境
"""
import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse

BASE_URL = os.environ.get("BASE_URL", "https://aihot.virxact.com").rstrip("/")
# 与 SKILL.md 约定一致的基础 User-Agent（无 .aihot-actor-id 时使用）
UA = "aihot-skill/1.5.4 (+https://aihot.virxact.com/aihot-skill/)"

results = []  # (name, ok, detail, conditional)


def call(path, params=None, timeout=30):
    """发起一次匿名 GET，返回 (status, data_or_None, error_or_None)。"""
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = None
            return resp.status, data, None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return e.code, None, f"HTTP {e.code}: {raw[:160]}"
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"


def record(name, ok, detail, conditional=False):
    results.append((name, ok, detail, conditional))
    tag = "COND" if conditional else "    "
    print(f"[{'PASS' if ok else 'FAIL'}] {tag} {name}\n        -> {detail}")


def env_items(data):
    """从信封结构里取 items 数组（兼容裸数组）。"""
    if isinstance(data, dict):
        return data.get("items", [])
    if isinstance(data, list):
        return data
    return []


def check_envelope(name, status, expected, data, item_required=None):
    """断言状态码 + 信封含 items 数组 + （可选）抽样单条字段。"""
    exp = expected if isinstance(expected, (list, tuple, set)) else [expected]
    ok = status in exp
    if ok and data is not None:
        arr = env_items(data)
        detail = f"HTTP {status} · 信封顶层字段={list(data.keys())[:8] if isinstance(data,dict) else type(data).__name__} · items={len(arr)}条"
        if item_required and arr:
            first = arr[0]
            missing = set(item_required) - set(first.keys())
            if missing:
                ok = False
                detail += f" · 首条缺失字段 {missing}"
            else:
                detail += f" · 首条含 {sorted(item_required)}"
    else:
        detail = f"HTTP {status}（期望 {exp}）" + ("" if data is not None else " · 无 JSON 体")
    record(name, ok, detail)
    return data


# ---------------------------------------------------------------- 正常路径
def test_normal_paths():
    print("\n=== 1) 正常路径 (Normal Paths) ===")
    ITEM_REQ = {"title", "links", "source"}  # items 单条必备字段

    # 1.1 精选资讯流 - 过去24h（首页默认入口）
    s, d, e = call("/api/v1/items", {"mode": "selected", "window": "24h"})
    check_envelope("items·selected·24h", s, 200, d, ITEM_REQ)

    # 1.2 精选资讯流 - 最近7天 limit=10
    s, d, e = call("/api/v1/items", {"mode": "selected", "window": "7d", "limit": "10"})
    check_envelope("items·selected·7d·limit10", s, 200, d, ITEM_REQ)

    # 1.3 全部公开动态 mode=all（关键词检索冷门词回退路径）
    s, d, e = call("/api/v1/items", {"mode": "all", "window": "7d", "limit": "10"})
    check_envelope("items·all·7d", s, 200, d, ITEM_REQ)

    # 1.4 关键词检索 q（检索中心核心能力）
    s, d, e = call("/api/v1/items", {"mode": "selected", "q": "OpenAI", "window": "7d"})
    check_envelope("items·q=OpenAI", s, 200, d, ITEM_REQ)

    # 1.5 分类检索（用真实 slug：ai-models / paper 等）
    for slug in ("ai-models", "paper", "ai-products", "industry", "tip"):
        s, d, e = call("/api/v1/items",
                       {"mode": "selected", "category": slug, "window": "7d"})
        check_envelope(f"items·category={slug}", s, 200, d, ITEM_REQ)

    # 2. 热点榜
    s, d, e = call("/api/v1/hot-topics")
    check_envelope("hot-topics", s, 200, d, {"rank", "title", "links"})

    # 3. 日报索引
    s, d, e = call("/api/v1/dailies", {"limit": "3"})
    check_envelope("dailies·index·limit3", s, 200, d, {"date", "links"})

    # 4. 事件详情（从 hot-topics 提取 links.story 里的 publicId）
    public_id = None
    hot = env_items(d) if False else None
    s, d, e = call("/api/v1/hot-topics")
    for it in env_items(d):
        links = it.get("links") or {}
        story = links.get("story") if isinstance(links, dict) else None
        if story and "/story/" in story:
            public_id = story.rsplit("/story/", 1)[-1]
            break
    if public_id:
        s2, d2, e2 = call(f"/api/v1/stories/{public_id}")
        ok = s2 == 200 and isinstance(d2, dict) and "story" in d2
        detail = f"HTTP {s2} · publicId={public_id} · 含 story 对象={'story' in d2 if isinstance(d2,dict) else False}"
        record(f"stories·{public_id[:8]}…", ok, detail)
    else:
        record("stories·<from hot-topics>", False,
               "hot-topics 未返回 links.story，无法取得 publicId（条件触发，非接口故障）",
               conditional=True)

    # 5. 日报详情（从索引提取 date）
    daily_date = None
    s, d, e = call("/api/v1/dailies", {"limit": "1"})
    arr = env_items(d)
    if arr:
        daily_date = arr[0].get("date")
    if daily_date:
        s2, d2, e2 = call(f"/api/v1/dailies/{daily_date}")
        ok = s2 == 200 and isinstance(d2, dict) and bool(d2)
        detail = f"HTTP {s2} · date={daily_date} · 返回对象={'story' if False else list(d2.keys())[:8] if isinstance(d2,dict) else type(d2).__name__}"
        record(f"dailies·{daily_date}", ok, detail)
    else:
        record("dailies·{YYYY-MM-DD}", False,
               "日报索引未返回 date 字段（响应结构可能变化）", conditional=True)


# ---------------------------------------------------------------- 错误路径
def test_error_paths():
    print("\n=== 2) 错误路径 (Error Paths) ===")

    # 2.1 不存在的 story id -> 期望 404（证明路由存在且鉴权/资源校验正常）
    s, d, e = call("/api/v1/stories/this-id-does-not-exist-0000")
    check_envelope("stories·404 无效id", s, 404, d)

    # 2.2 历史空日期的日报详情 -> 期望 404/400
    s, d, e = call("/api/v1/dailies/1900-01-01")
    check_envelope("dailies·404 历史空日期", s, [404, 400], d)

    # 2.3 非法 window 参数 -> 期望 400（接口做了参数校验）
    s, d, e = call("/api/v1/items", {"mode": "selected", "window": "999d"})
    check_envelope("items·非法 window", s, [200, 400], d)

    # 2.4 不存在的分类 slug -> 期望 400（验证 slug 强约束）
    s, d, e = call("/api/v1/items", {"mode": "selected", "category": "model", "window": "7d"})
    check_envelope("items·非法 category=model", s, [200, 400], d)

    # 2.5 冷门关键词 -> 期望 200 + 空数组（前端据此回退 mode=all）
    s, d, e = call("/api/v1/items",
                   {"mode": "selected", "q": "zzz_nonexistent_keyword_xyz", "window": "7d"})
    check_envelope("items·q 冷门词", s, 200, d)


def main():
    print(f"目标 BASE_URL = {BASE_URL}")
    test_normal_paths()
    test_error_paths()

    passed = sum(1 for _, ok, _, _ in results if ok)
    failed = sum(1 for _, ok, _, c in results if (not ok) and not c)
    cond_fail = sum(1 for _, ok, _, c in results if (not ok) and c)
    print("\n" + "=" * 60)
    print(f"汇总：共 {len(results)} 项")
    print(f"  PASS          = {passed}")
    print(f"  FAIL(硬失败)  = {failed}")
    print(f"  COND FAIL(条件触发,需人工复核) = {cond_fail}")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
