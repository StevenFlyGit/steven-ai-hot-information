#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷新 fixture 样例（仅用于离线回退演示）。

用途：当上游 AIHOT 结构演进、或需要在无网环境中更新演示数据时，
运行本脚本重新抓取真实样例并写入 server/fixtures/。

注意：
- fixture 仅作「上游不可达」时的离线回退，不代表实时数据；
  前端在回退时会显式横幅标注，绝不伪装成实时。
- 真实运行环境仍直连上游，fixture 不会被使用（除非上游失败）。

用法：
    python server/refresh_fixtures.py
    BASE_URL=https://其它主机 python server/refresh_fixtures.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("BASE_URL", "https://aihot.virxact.com").rstrip("/")
UA = "aihot-skill/1.5.4 (+https://aihot.virxact.com/aihot-skill/)"
FX_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def get(path: str, params: dict | None = None, timeout: int = 20):
    url = BASE + "/api/v1" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def save(name: str, obj) -> None:
    os.makedirs(FX_DIR, exist_ok=True)
    with open(os.path.join(FX_DIR, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    print(f"  saved {name}")


def main() -> int:
    print(f"抓取样例 -> {BASE}")
    os.makedirs(FX_DIR, exist_ok=True)

    # 1) items selected 24h
    s, d = get("/items", {"mode": "selected", "window": "24h", "limit": "6"})
    if s == 200:
        save("items_selected_24h.json", json.loads(d))
    else:
        print(f"  [跳过] items 失败: {s}")

    # 2) hot-topics
    s, d = get("/hot-topics")
    if s == 200:
        save("hot_topics.json", json.loads(d))
    else:
        print(f"  [跳过] hot-topics 失败: {s}")

    # 3) dailies index
    s, d = get("/dailies", {"limit": "5"})
    if s == 200:
        save("dailies_index.json", json.loads(d))
        date = (json.loads(d).get("items") or [{}])[0].get("date")
    else:
        print(f"  [跳过] dailies 失败: {s}")
        date = None

    # 4) 单日日报（取索引第一条）
    if date:
        s, d = get(f"/dailies/{date}")
        if s == 200:
            save("daily_report.json", json.loads(d))

    # 5) 一个 story（从 hot-topics 的 links.story 提取 publicId）
    if s == 200 and date:  # 仅当日报成功时再尝试
        pass
    # 直接从 hot-topics 找 story
    try:
        with open(os.path.join(FX_DIR, "hot_topics.json"), encoding="utf-8") as fh:
            hot = json.load(fh)
        pid = None
        for it in (hot.get("items") or []):
            links = it.get("links") or {}
            st = links.get("story") if isinstance(links, dict) else None
            if st and "/story/" in st:
                pid = st.rsplit("/story/", 1)[-1]
                break
        if pid:
            s, d = get(f"/stories/{pid}")
            if s == 200:
                save("story_sample.json", json.loads(d))
    except FileNotFoundError:
        print("  [跳过] 无 hot_topics.json，无法定位 story")

    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
