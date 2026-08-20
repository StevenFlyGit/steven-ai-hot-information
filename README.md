# AI·HOT 资讯平台（杂志编辑风 · 版本 B）

面向「AI 热点资讯」的**查看 / 搜索 / 抓取**平台。前端为杂志编辑风（暖白底、衬线大标题、大留白、克制配色），后端为一层**极薄同源代理**，转发 [AIHOT](https://aihot.virxact.com) 匿名只读 v1 API，解决浏览器跨域（CORS），并附 ETag 缓存、限流与离线回退。

> **数据来源与合规**：数据来自 AIHOT 匿名只读 v1 API，**署名 ≠ 授权**。个人非商业 demo 可免费使用；任何对外商业化 / 收费 / 数据转售 / 公开镜像 / 白标，须先取得 AIHOT 书面授权（联系 `wzglyay@virxact.com`）。页面已保留「数据来源：AIHOT」署名与原文跳转。

---

## 一、项目结构

```
Code-10-ai-hot-information-demo/
├── server/                 # 极薄后端代理（Python 标准库，零三方依赖）
│   ├── server.py           # HTTP 服务：静态托管 + /api/proxy 转发 + /api/health + /api/menu
│   ├── config.py           # 环境变量驱动的配置
│   ├── menu.py             # 菜单（菜单栏）服务：全量菜单组合 + 缓存 + 校验
│   ├── aihot_client.py     # 上游转发：ETag 缓存 + 60s 节流 + fixture 回退
│   ├── refresh_fixtures.py # 重新抓取离线样例（可选）
│   ├── requirements.txt    # 零依赖说明
│   └── fixtures/           # 真实抓取样例（仅上游不可达时回退）
├── web/                    # 前端静态站点（H5，原生 JS，无框架依赖）
│   ├── index.html          # 五视图结构壳 + 顶部导航 + 页脚
│   ├── styles.css          # 权威视觉系统（02 文档令牌 + 组件规范）
│   └── app.js              # hash 路由 + 数据层 + 五视图渲染
├── Doc/                    # 设计原型专家团交付物（需求/视觉/质量/原型 HTML）
├── .env.example            # 环境变量示例
├── .gitignore
└── README.md
```

---

## 二、快速开始

### 环境要求
- Python 3.8+（已用 3.11 验证）
- **无需安装任何三方包**（后端仅用标准库）

### 启动

```bash
# 进入项目根目录
cd Code-10-ai-hot-information-demo

# 默认 8000 端口启动
python server/server.py

# 或自定义端口
PORT=8080 python server/server.py
```

启动后浏览器打开：<http://localhost:8000/>

> Windows 用户若 `python` 指向旧版本，请用 `python3` 或完整路径，例如：
> `C:\MyApplication\AI_DataAnalysis\anaconda3\python.exe server\server.py`

---

## 三、功能与页面

| 视图 | 路由（hash） | 数据端点 |
|------|--------------|----------|
| 首页精选流 | `#/` | `/api/proxy/items?mode=selected&window=24h` |
| 热点榜 | `#/hot` | `/api/proxy/hot-topics` |
| 检索中心 | `#/search` | `/api/proxy/items`（组合 q/category/window/by） |
| 日报归档 | `#/daily` | `/api/proxy/dailies` + `/api/proxy/dailies/{date}` |
| 事件详情 | `#/story/{publicId}` | `/api/proxy/stories/{publicId}` |

五大视图均经同源代理加载真实数据，无白屏、无 CORS 报错。

### 菜单栏数据接口（`/api/menu`）

返回站点「全量菜单」—— 顶级导航（精选 / 全量 / 热点榜 / 检索 / 日报）与其下的分类子菜单（模型 / 产品 / 论文 / 行业 / 技巧）构成的层级结构。菜单为服务端组合（非上游实时），按 `MENU_CACHE_TTL` 缓存。

| 查询参数 | 取值 | 说明 |
|----------|------|------|
| `flat` | `1`/`true`/`0`/`false`（默认树形） | 是否将层级菜单拍平为单层列表 |
| `include` | `nav,categories`（默认全部；白名单 `nav`/`categories`） | 仅返回指定分组 |
| `refresh` | `1`/`true` | 忽略缓存，强制重新组合 |

返回字段：`schemaVersion`、`generatedAt`、`source`(固定 `composed`)、`cache{hit,ttl,age}`、`menu[]`(含 `children` 层级)、`categories[]`。参数非法返回 `400 invalid_param`，组合异常返回 `500 internal`。详见 `server/menu.py` 顶部字段定义注释。

---

## 四、五项检索能力 · 诚实边界（不可删减）

| # | 能力 | 实现 | UI 标注 |
|---|------|------|---------|
| 1 | 关键词搜索 | `q` 参数 | 直接 API 能力 |
| 2 | 分类筛选 | `category` 参数（真实 slug：`ai-models`/`ai-products`/`paper`/`industry`/`tip`） | 直接 API 能力 |
| 3 | 时间范围 | `window` + `by` 参数 | 直接 API 能力 |
| 4 | 来源筛选 | 拉取后按 `source.name` **客户端过滤** | 「本地过滤 · 客户端派生」 |
| 5 | 智能/语义检索 | 编辑策展 + AI 综述 + 推荐理由 + 热点编辑智能 | 「智能聚合层 · 非语义检索」 |

> 第 4、5 项**不是独立 API 端点**，不进入请求串；检索中心已用语义着色如实区分「API 参数 / 本地过滤 / 智能聚合」三类。

---

## 五、后端代理设计要点

- **同源转发**：前端经 `/api/proxy/*` 调用，规避 AIHOT 的 CORS 限制（浏览器直连会被跨域拦截）。
- **ETag / 304 复用**：携带 `If-None-Match`，上游返回 304 时直接复用缓存。
- **限流**：同端点轮询间隔下限 60s（缓存期内不再打上游）；全局礼貌限速避免突发。
- **短 TTL 缓存**：默认 300s，降低上游压力（资讯非秒级新鲜度）。
- **离线回退**：上游不可达时回退到 `fixtures/` 真实样例，并在前端显示**演示数据横幅**，明确区分、不伪装实时。
- **不落库、不改写**：代理只转发 + 缓存，来源署名随响应透传。
- **SSRF 防护**：仅允许转发到已知只读端点前缀（`/items`、`/hot-topics`、`/stories`、`/dailies`）。

---

## 六、配置（环境变量）

见 `.env.example`。常用项：

| 变量 | 默认 | 说明 |
|------|------|------|
| `PORT` | `8000` | 监听端口 |
| `HOST` | `0.0.0.0` | 监听地址 |
| `AIHOT_UPSTREAM` | `https://aihot.virxact.com` | 上游域名 |
| `AIHOT_MIN_POLL_INTERVAL` | `60` | 同端点轮询间隔下限（秒） |
| `AIHOT_CACHE_TTL` | `300` | 缓存 TTL（秒） |
| `MENU_CACHE_TTL` | `3600` | 菜单组合结果缓存时长（秒） |

---

## 七、刷新离线样例（可选）

当上游结构演进、或需在无网环境更新演示数据时：

```bash
python server/refresh_fixtures.py
```

---

## 八、验收对照（节选自移交文档）

- [x] 五视图经代理加载真实数据，无白屏 / CORS 报错
- [x] 5 项检索能力映射正确，来源/智能不进请求串且 UI 如实标注
- [x] 精选池为空自动回退 `mode=all` 并灰注「未进入精选」
- [x] 热点榜按 `rank` 显示「第 N 名」，不杜撰热度（空位「—」）
- [x] 事件详情展示 AI 综述 digest + 逆序时间线 + 最新进展 + 原文跳转
- [x] 原文跳转与「数据来源：AIHOT」署名可见
- [x] 视觉 1:1 还原版本 B（暖白底/衬线标题/≤3 彩色/分类 chip 描边/无等宽终端元素）
- [x] 关键元信息用 `--ink-700`（≈7.6:1，达 WCAG AA）
- [x] 响应式 ≤880px 单列
- [x] 后端有 ETag/304 复用、≥60s 同端点限流、错误降级
- [x] `README` 可照着启动；配置外置、模块清晰
