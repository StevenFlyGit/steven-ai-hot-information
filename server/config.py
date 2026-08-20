"""后端代理配置（环境变量驱动，不写死在代码里）。

所有可调项均可通过环境变量覆盖，便于部署时按环境切换上游 / 端口 / 缓存策略。
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """极薄代理的全局配置。"""

    # AIHOT 匿名只读 v1 API 上游（仅转发，不落库、不改写）
    upstream_base: str = os.environ.get("AIHOT_UPSTREAM", "https://aihot.virxact.com")
    api_prefix: str = os.environ.get("AIHOT_API_PREFIX", "/api/v1")

    # 服务监听
    host: str = os.environ.get("HOST", "0.0.0.0")
    port: int = int(os.environ.get("PORT", "8000"))

    # 节流与缓存：同端点轮询间隔下限（秒）与缓存 TTL（秒）
    # 依据 AIHOT 调用规约：同端点轮询间隔 ≥ 60s；资讯非秒级新鲜度，优先缓存。
    min_poll_interval: int = int(os.environ.get("AIHOT_MIN_POLL_INTERVAL", "60"))
    cache_ttl: int = int(os.environ.get("AIHOT_CACHE_TTL", "300"))

    # 上游要求的 User-Agent（无 .aihot-actor-id 时使用基础标识）
    user_agent: str = os.environ.get(
        "AIHOT_USER_AGENT",
        "aihot-skill/1.5.4 (+https://aihot.virxact.com/aihot-skill/)",
    )

    # 菜单（菜单栏）组合结果缓存时长（秒）。菜单为低频变更数据，
    # 默认 3600s；与资讯缓存（cache_ttl）独立，避免互相干扰。
    menu_cache_ttl: int = int(os.environ.get("MENU_CACHE_TTL", "3600"))

    # 前端静态目录（web/）
    web_dir: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")


CONFIG = Config()
