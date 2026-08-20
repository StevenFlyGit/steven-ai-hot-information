# AIHOT v1 API 可用性测试报告

> 测试对象：`Code-10-ai-hot-information-demo` 所依赖的真实接口能力，来源 `https://aihot.virxact.com/aihot-skill/SKILL.md`（AIHOT 匿名只读 v1 API）
> 测试时间：2026-08-18
> 测试方式：Python 标准库（urllib）自包含脚本 `test_aihot_api.py`，逐端点断言 HTTP 状态码 + 信封/字段结构；覆盖正常路径与错误路径。
> **结论：18/18 全部 PASS，demo 涉及的 5 类接口能力当前均可正常调用。**

---

## 一、demo 能力 ↔ 接口映射

| # | Demo 能力（页面） | 对应端点 | 用途 |
|---|---|---|---|
| 1 | 精选资讯流（首页） | `GET /api/v1/items?mode=selected&window=24h\|7d` | 编辑精选池 |
| 2 | 热点榜 | `GET /api/v1/hot-topics` | 当前热点 Top10，按 `rank` 排序 |
| 3 | 事件详情 | `GET /api/v1/stories/{publicId}` | 逆序时间线 + AI 综述 + 最新进展 |
| 4 | 日报归档 | `GET /api/v1/dailies?limit=N` + `/api/v1/dailies/{YYYY-MM-DD}` | 固定日切成品 |
| 5 | 检索中心 | `GET /api/v1/items`（组合 `q`/`category`/`window`/`by`，含 `mode=all`） | 关键词 + 分类检索 |

认证：匿名、只读、无需 Key，仅需设置 `User-Agent: aihot-skill/1.5.4 (+https://aihot.virxact.com/aihot-skill/)`。

---

## 二、测试结果（18 项）

### 正常路径（13 项，全部 PASS）
| 用例 | 端点 | 结果 |
|---|---|---|
| items·selected·24h | `/items?mode=selected&window=24h` | 200 · items=11 |
| items·selected·7d·limit10 | `/items?mode=selected&window=7d&limit=10` | 200 · items=10 |
| items·all·7d | `/items?mode=all&window=7d&limit=10` | 200 · items=10 |
| items·q=OpenAI | `/items?mode=selected&q=OpenAI&window=7d` | 200 · items=17 |
| items·category=ai-models | `/items?mode=selected&category=ai-models&window=7d` | 200 · items=17 |
| items·category=paper | 同上 `category=paper` | 200 · items=8 |
| items·category=ai-products | 同上 `category=ai-products` | 200 · items=15 |
| items·category=industry | 同上 `category=industry` | 200 · items=13 |
| items·category=tip | 同上 `category=tip` | 200 · items=19 |
| hot-topics | `/hot-topics` | 200 · items=3 |
| dailies·index·limit3 | `/dailies?limit=3` | 200 · items=3 |
| stories·{真实id} | `/stories/fdc2b29b-…` | 200 · 含 `story` 对象 |
| dailies·2026-08-18 | `/dailies/2026-08-18` | 200 · 含 `report` 对象 |

### 错误路径（5 项，全部 PASS — 校验接口做了合法参数校验）
| 用例 | 端点 | 期望 | 实际 |
|---|---|---|---|
| stories·无效 id | `/stories/this-id-does-not-exist-0000` | 404 | 404 ✅ |
| dailies·历史空日期 | `/dailies/1900-01-01` | 404/400 | 404 ✅ |
| items·非法 window | `/items?window=999d` | 200/400 | 400 ✅（参数强校验） |
| items·非法 category | `/items?category=model` | 200/400 | 400 ✅（slug 强约束） |
| items·冷门词 | `/items?q=zzz_nonexistent_keyword_xyz` | 200 | 200 · items=0（前端可据此回退 `mode=all`）✅ |

---

## 三、⚠️ 对 demo 的重要契约发现（需修正设计/原型）

1. **分类 slug 与 demo 假设不一致（关键）**
   - demo 设计/原型曾按 `category=model` 这类直觉 slug 设计；**真实合法 slug 为**：`tip`、`ai-products`、`industry`、`paper`、`ai-models`。
   - 传 `category=model` 会返回 **400**。检索中心若硬编码 `model` 会直接报错，必须改用 `ai-models`（或动态拉取真实 slug 列表）。

2. **响应为「信封结构」，不是裸数组**
   - 列表类端点返回 `{"schemaVersion", "count"/"query", "items":[...], "page":...}`，单条在 `items` 数组内。
   - 单篇 story 详情返回 `{"schemaVersion", "story":{...}}`；日报详情返回 `{"schemaVersion", "report":{...}}`。
   - 前端/原型若按「直接拿到数组」解析会取不到数据，需先读 `.items` / `.story` / `.report`。

3. **事件详情（stories）是条件触发能力**
   - 仅当 `hot-topics` 条目含 `links.story`（如 `…/story/<uuid>`）时才有可用的 `publicId`。
   - 实测当前 hot-topics 已有 story 入口，`/stories/{id}` 可正常返回 200；但该事件对象的 `digest`/`latest` 字段当前为 `null`（事件层内容随演化更新，部分事件暂未填充）。原型需对空 digest/latest 做降级展示。

4. **CORS 仍未解决（与接口可用性无关，但影响浏览器部署）**
   - 本次测试用服务端 Python 直连，绕过浏览器同源策略。若 demo 要在 H5/小程序里由前端直接 `fetch`，仍受 CORS / 微信域名白名单限制，**必须保留设计文档要求的「极薄后端代理」**，前端不直接跨域请求 `aihot.virxact.com`。

---

## 四、如何复跑
```bash
cd Code-10-ai-hot-information-demo
python test_aihot_api.py            # 默认打全部 18 项用例
BASE_URL=https://其它主机 python test_aihot_api.py   # 切换环境
```
脚本末尾输出 PASS/FAIL 计数并以退出码（0=无硬失败）结束，可接入 CI。
