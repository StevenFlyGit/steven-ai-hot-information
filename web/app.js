/* ============================================================
 * AI·HOT 资讯 · 前端应用逻辑（原生 JS，无框架依赖）
 *
 * 设计基线：02-视觉风格方案-版本B.md（杂志编辑风）
 * 数据源：AIHOT 匿名只读 v1 API，经同源后端代理 /api/proxy 转发。
 *
 * 关键诚实边界（不可删减，移交文档红线）：
 *  - 来源筛选 = 客户端本地过滤（非 API 参数）
 *  - 智能聚合 = 编辑策展 + AI 综述 + 推荐理由 + 热点编辑智能（非向量语义检索）
 *  - 热点榜仅按 rank 排印，不杜撰内部热度值（空位统一「—」）
 *  - 精选池为空时自动回退 mode=all 并灰注「未进入精选」
 *  - 上游不可达时回退 fixture 并显式横幅标注，不伪装实时
 * ============================================================ */
(function () {
  "use strict";

  var API = "/api/proxy";

  /* ---------- 分类映射（slug ↔ 中文/英文 kicker） ----------
   * 真实合法 slug 来自 AIHOT（见接口测试报告）：ai-models / ai-products / paper / industry / tip
   * 注意：原型曾用 model/product 等直觉 slug，真实 API 会 400，必须以真实 slug 为准。 */
  var CATEGORY = {
    "ai-models": { zh: "模型", en: "MODEL" },
    "ai-products": { zh: "产品", en: "PRODUCT" },
    "paper": { zh: "论文", en: "PAPER" },
    "industry": { zh: "行业", en: "INDUSTRY" },
    "tip": { zh: "技巧", en: "TIPS" }
  };
  var ZH_TO_SLUG = {};
  Object.keys(CATEGORY).forEach(function (slug) {
    ZH_TO_SLUG[CATEGORY[slug].zh] = slug;
  });

  function catInfo(slug) {
    return CATEGORY[slug] || { zh: slug || "未分类", en: (slug || "").toUpperCase() };
  }
  function catSlug(zh) {
    return ZH_TO_SLUG[zh] || null;
  }

  /* ---------- 工具函数 ---------- */
  function esc(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // 北京时间（UTC+8）格式化
  function fmtBJ(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "—";
    var bj = new Date(d.getTime() + 8 * 3600 * 1000);
    function p(n) { return String(n).padStart(2, "0"); }
    return p(bj.getUTCMonth() + 1) + "-" + p(bj.getUTCDate()) + " " +
      p(bj.getUTCHours()) + ":" + p(bj.getUTCMinutes());
  }
  function fmtBJDate(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "—";
    var bj = new Date(d.getTime() + 8 * 3600 * 1000);
    function p(n) { return String(n).padStart(2, "0"); }
    return bj.getUTCFullYear() + "-" + p(bj.getUTCMonth() + 1) + "-" + p(bj.getUTCDate());
  }
  var WEEK = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
  function weekday(dateStr) {
    var d = new Date(dateStr + "T00:00:00Z");
    return WEEK[d.getUTCDay()];
  }

  function skeleton(n) {
    n = n || 3;
    var s = '<div class="skeleton">';
    var cls = ["s1", "s2", "s3", "s4"];
    for (var i = 0; i < n; i++) {
      s += '<div class="skel-line ' + (cls[i % cls.length]) + '"></div>';
    }
    return s + "</div>";
  }

  /* ---------- 数据层 ---------- */
  // 经同源代理请求，并返回响应头中的 X-AIHOT-Source（upstream/cache/fixture）
  async function apiGet(path, params) {
    var url = API + path;
    if (params) {
      var q = new URLSearchParams(params);
      url += "?" + q.toString();
    }
    try {
      var resp = await fetch(url, { headers: { Accept: "application/json" } });
      var source = resp.headers.get("X-AIHOT-Source") || "upstream";
      var data = null;
      try { data = await resp.json(); } catch (e) { data = null; }
      return { ok: resp.ok, status: resp.status, source: source, data: data };
    } catch (e) {
      return { ok: false, status: 0, source: "error", data: null };
    }
  }

  // items 拉取：精选为空自动回退 mode=all（移交文档旅程 2 / 验收标准 3）
  async function fetchItems(params) {
    var r = await apiGet("/items", params);
    var items = (r.ok && r.data && Array.isArray(r.data.items)) ? r.data.items : [];
    if (r.ok && items.length === 0 && params.mode === "selected") {
      var r2 = await apiGet("/items", Object.assign({}, params, { mode: "all" }));
      var items2 = (r2.ok && r2.data && Array.isArray(r2.data.items)) ? r2.data.items : [];
      if (r2.ok) {
        return { ok: true, status: r2.status, source: r2.source, data: r2.data, items: items2, fellBack: true };
      }
    }
    return { ok: r.ok, status: r.status, source: r.source, data: r.data, items: items, fellBack: false };
  }

  /* ---------- 演示数据横幅 ---------- */
  function applySourceBanner(source) {
    var b = document.getElementById("fbBanner");
    if (source === "fixture") {
      b.style.display = "block";
    } else {
      b.style.display = "none";
    }
  }

  /* ---------- 通用卡片渲染（首页精选流 / 检索结果共用） ---------- */
  function renderCard(item, windowLabel) {
    var ci = catInfo(item.category);
    var src = (item.source && item.source.name) ? item.source.name : "—";
    var aihot = (item.links && (item.links.aihot || item.links.original)) || "#";
    var orig = (item.links && (item.links.original || item.links.aihot)) || "#";
    var reason = item.reason ? '<p class="reason">' + esc(item.reason) + "</p>" : "";
    return (
      '<article class="card" data-cat="' + esc(ci.zh) + '">' +
        '<div class="cat">' + esc(ci.zh) + " · " + esc(ci.en) + "</div>" +
        '<h3><a href="' + esc(aihot) + '" target="_blank" rel="noopener">' + esc(item.title) + "</a></h3>" +
        '<p class="summary">' + esc(item.summary || "") + "</p>" +
        '<div class="meta">' +
          "<span>来源 · " + esc(src) + "</span>" +
          '<span class="muted">北京时间 ' + fmtBJ(item.publishedAt) + "</span>" +
          '<span class="muted">' + esc(windowLabel) + "</span>" +
        "</div>" +
        reason +
        '<div class="card-foot">' +
          '<a href="' + esc(orig) + '" target="_blank" rel="noopener">原文 &rarr;</a>' +
          '<span class="muted">数据来源：AIHOT</span>' +
        "</div>" +
      "</article>"
    );
  }

  /* 绑定动态生成内容中的动作链接（避免内联 JS 转义问题） */
  function bindActions(root) {
    root.querySelectorAll("[data-story]").forEach(function (a) {
      a.addEventListener("click", function (e) {
        e.preventDefault();
        navigate("story", a.getAttribute("data-story"));
      });
    });
    root.querySelectorAll("[data-nav]").forEach(function (a) {
      a.addEventListener("click", function (e) {
        e.preventDefault();
        navigate(a.getAttribute("data-nav"));
      });
    });
  }

  /* ============================================================
   * 视图 1 · 首页
   * ============================================================ */
  async function renderHome() {
    var feedEl = document.getElementById("feedList");
    feedEl.innerHTML = skeleton(4);

    // 并行拉取：精选流 + 热点榜(Top5) + 今日日报索引
    var results = await Promise.all([
      fetchItems({ mode: "selected", window: "24h", limit: "24" }),
      apiGet("/hot-topics"),
      apiGet("/dailies", { limit: "1" })
    ]);
    var itemsRes = results[0], hotRes = results[1], dailyRes = results[2];
    applySourceBanner(itemsRes.source);

    var items = itemsRes.items || [];
    var windowLabel = "window 24h";

    // 回退标注
    var prefix = "";
    if (itemsRes.fellBack) {
      prefix = '<div class="feed-empty"><b>未进入精选 ·</b> 当前精选池暂无命中，已回退至全部公开结果（mode=all）。</div>';
    }
    if (items.length === 0) {
      feedEl.innerHTML = '<div class="feed-empty">暂无资讯，请稍后重试。</div>';
    } else {
      feedEl.innerHTML = prefix + items.map(function (it) { return renderCard(it, windowLabel); }).join("");
    }

    // Hero = 首条精选
    if (items[0]) renderHero(items[0]);

    // 本期日期
    var today = fmtBJDate(new Date().toISOString());
    document.getElementById("homeDate").textContent =
      "本期 · " + today + " · " + weekday(today);

    renderMiniHot(hotRes);
    renderHomeDaily(dailyRes);
  }

  /* ============================================================
   * 视图 1.5 · 全量热点（mode=all）
   * ============================================================ */
  async function renderAll() {
    var feedEl = document.getElementById("allList");
    feedEl.innerHTML = skeleton(6);
    // 全量池：直接拉取 mode=all（fetchItems 仅在 mode=selected 时空回退，此处不会触发）
    var r = await fetchItems({ mode: "all", window: "24h", limit: "48" });
    applySourceBanner(r.source);
    var items = r.items || [];
    if (items.length === 0) {
      feedEl.innerHTML = '<div class="feed-empty">全量池暂无公开条目，请稍后重试。</div>';
      return;
    }
    feedEl.innerHTML = items.map(function (it) { return renderCard(it, "window 24h"); }).join("");
  }

  /* 全量页分类快捷筛选（与原型一致：视觉过滤，作用域隔离到 #allList） */
  function initAllFilter() {
    var filter = document.getElementById("allFilter");
    if (!filter) return;
    filter.addEventListener("click", function (e) {
      var c = e.target.closest(".qchip"); if (!c) return;
      this.querySelectorAll(".qchip").forEach(function (x) { x.classList.remove("on"); });
      c.classList.add("on");
      var cat = c.getAttribute("data-cat");
      var shown = 0;
      document.querySelectorAll("#allList .card").forEach(function (card) {
        var ok = cat === "all" || card.getAttribute("data-cat") === cat;
        card.style.display = ok ? "" : "none";
        if (ok) shown++;
      });
      var empty = document.getElementById("allEmpty");
      if (shown === 0) {
        if (!empty) {
          empty = document.createElement("div");
          empty.id = "allEmpty"; empty.className = "feed-empty";
          document.getElementById("allList").appendChild(empty);
        }
        empty.textContent = "全量池暂无匹配 · 当前分类下无公开条目。";
      } else if (empty) { empty.remove(); }
    });
  }

  function renderHero(item) {
    var ci = catInfo(item.category);
    var src = (item.source && item.source.name) ? item.source.name : "—";
    var orig = (item.links && (item.links.original || item.links.aihot)) || "#";
    document.getElementById("heroKicker").textContent = ci.zh + " · " + ci.en;
    document.getElementById("heroTitle").textContent = item.title;
    document.getElementById("heroSummary").textContent = item.summary || "";
    document.getElementById("heroByline").innerHTML =
      "<span>来源 · " + esc(src) + "</span>" +
      '<span class="muted">北京时间 ' + fmtBJ(item.publishedAt) + "</span>" +
      '<span class="muted">编辑精选</span>';
    var read = document.getElementById("heroRead");
    read.href = esc(orig);
  }

  function renderMiniHot(hotRes) {
    var el = document.getElementById("miniHot");
    var items = (hotRes.ok && hotRes.data && Array.isArray(hotRes.data.items)) ? hotRes.data.items : [];
    if (items.length === 0) { el.innerHTML = ""; return; }
    el.innerHTML = items.slice(0, 5).map(function (h) {
      var storyId = (h.links && h.links.story) ? h.links.story.split("/story/").pop() : null;
      var titleHtml = esc(h.title);
      if (storyId) {
        titleHtml += '<span class="story" data-story="' + esc(storyId) + '">含事件脉络 &rarr;</span>';
      }
      // 含事件脉络 &rarr; 进事件详情；否则 &rarr; 直接打开原文（新标签）
      var attrs = storyId
        ? 'href="#" data-story="' + esc(storyId) + '"'
        : 'href="' + esc((h.links && h.links.original) || "#") + '" target="_blank" rel="noopener"';
      return '<li><a class="t" ' + attrs + ">" + titleHtml + "</a></li>";
    }).join("");
    bindActions(el);
  }

  function renderHomeDaily(dailyRes) {
    var dateEl = document.getElementById("homeDailyDate");
    var descEl = document.getElementById("homeDailyDesc");
    var items = (dailyRes.ok && dailyRes.data && Array.isArray(dailyRes.data.items)) ? dailyRes.data.items : [];
    if (items.length === 0) {
      dateEl.textContent = "—";
      descEl.textContent = "日报暂未生成。";
      return;
    }
    var d = items[0];
    dateEl.textContent = d.date + " · 已生成";
    descEl.textContent = d.leadTitle ? d.leadTitle : "当日 AI 日报已生成，点击查看完整归档。";
  }

  /* ============================================================
   * 视图 2 · 热点榜
   * ============================================================ */
  async function renderHot() {
    var el = document.getElementById("hotList");
    el.innerHTML = skeleton(6);
    var r = await apiGet("/hot-topics");
    applySourceBanner(r.source);
    var items = (r.ok && r.data && Array.isArray(r.data.items)) ? r.data.items : [];
    if (items.length === 0) {
      el.innerHTML = '<div class="feed-empty">暂无热点，请稍后重试。</div>';
      return;
    }
    el.innerHTML = items.map(function (h) {
      var rank = h.rank != null ? h.rank : "—";
      var storyId = (h.links && h.links.story) ? h.links.story.split("/story/").pop() : null;
      var src = (h.source && h.source.name) ? h.source.name : "";
      var sub = [];
      if (src) sub.push("<span>" + esc(src) + "</span>");
      if (storyId) sub.push('<a class="story-link" data-story="' + esc(storyId) + '">含事件脉络 &rarr;</a>');
      return (
        '<div class="hot-item"' + (storyId ? ' data-story="' + esc(storyId) + '"' : "") + ">" +
          '<div class="hot-rank">第<span class="rn">' + esc(rank) + "</span>名</div>" +
          '<div class="hot-body">' +
            '<div class="hot-title">' + esc(h.title) + "</div>" +
            '<div class="hot-sub">' + sub.join("") + "</div>" +
          "</div>" +
          '<div class="hot-score">—</div>' + // 不杜撰热度值
        "</div>"
      );
    }).join("");
    bindActions(el);
    // 整行点击（含 story 的条目）&rarr; 进入事件详情
    el.querySelectorAll(".hot-item[data-story]").forEach(function (row) {
      row.addEventListener("click", function (e) {
        if (e.target.closest(".story-link")) return; // 已由 bindActions 处理
        navigate("story", row.getAttribute("data-story"));
      });
    });
  }

  /* ============================================================
   * 视图 3 · 检索中心
   * ============================================================ */
  var searchState = { kw: "", cat: "all", win: "24h", by: "timeline", src: "", smart: true };

  function refreshSourceOptions(items) {
    var sel = document.getElementById("srcSel");
    var current = searchState.src;
    var names = [];
    items.forEach(function (it) {
      var n = (it.source && it.source.name) || null;
      if (n && names.indexOf(n) < 0) names.push(n);
    });
    names.sort();
    var html = '<option value="">全部来源（本地过滤）</option>';
    names.forEach(function (n) {
      html += '<option value="' + esc(n) + '"' + (n === current ? " selected" : "") + ">" + esc(n) + "</option>";
    });
    sel.innerHTML = html;
    // 若当前选择已不存在于新结果集，归零
    if (current && names.indexOf(current) < 0) {
      searchState.src = "";
      sel.value = "";
    }
  }

  // 实时拼出 API 请求示意（语义着色，非等宽终端元素）
  function buildApiDisplay() {
    var p = searchState;
    var params = ["mode=selected"];
    if (p.kw.trim()) params.push("q=" + encodeURIComponent(p.kw.trim()));
    if (p.cat !== "all") params.push("category=" + catSlug(p.cat));
    params.push("window=" + p.win);
    params.push("by=" + p.by);
    var query = "?" + params.join("&");
    document.getElementById("apiCode").innerHTML =
      '<span class="verb">GET</span> /api/v1/items<span class="param">' + esc(query) + "</span>";

    var note = '<span class="k">诚实标注：</span> 上述为 skill 直接支持的 <span class="key">API 参数</span>（q / category / window / by）。';
    if (p.src) {
      note += ' 来源「' + esc(p.src) + '」为 <span class="local">本地过滤</span>（客户端按 source.name 派生，非 API 参数）。';
    } else {
      note += ' 来源未选，默认 <span class="local">本地过滤</span> 不生效（结果集全量）。';
    }
    if (p.smart) {
      note += ' 智能聚合层已开启：由 <span class="smart">编辑策展+AI 综述+推荐理由+热点编辑智能</span> 构成，<span class="smart">非向量语义检索</span>，不映射为 API 参数。';
    }
    document.getElementById("apiNote").innerHTML = note;
  }

  async function runSearch() {
    var p = searchState;
    var params = { mode: "selected", window: p.win, by: p.by };
    if (p.kw.trim()) params.q = p.kw.trim();
    if (p.cat !== "all") params.category = catSlug(p.cat);

    var res = await fetchItems(params);
    applySourceBanner(res.source);
    var items = res.items || [];

    // 客户端二次过滤：分类 + 来源（真实模式下与 API 参数幂等；fixture 回退模式下使筛选仍可用）
    if (p.cat !== "all") {
      var slug = catSlug(p.cat);
      items = items.filter(function (it) { return it.category === slug; });
    }
    if (p.src) {
      items = items.filter(function (it) { return it.source && it.source.name === p.src; });
    }

    refreshSourceOptions(res.items || []);
    buildApiDisplay();

    var box = document.getElementById("searchResults");
    var head = "";
    if (res.fellBack) {
      head += '<div class="feed-empty"><b>未进入精选 ·</b> 精选池暂无命中，已回退全部公开结果（mode=all）。</div>';
    }
    head += '<div class="count">命中 <b>' + items.length + "</b> 条" +
      (p.src ? " · 来源本地过滤：" + esc(p.src) : "") + "</div>";

    if (items.length === 0) {
      box.innerHTML = head + '<div class="feed-empty">未找到匹配结果，试试调整关键词或分类。</div>';
      return;
    }
    var windowLabel = "window " + p.win;
    box.innerHTML = head + items.map(function (it) { return renderCard(it, windowLabel); }).join("");
  }

  function initSearchControls() {
    var kw = document.getElementById("kw");
    kw.addEventListener("input", function () { searchState.kw = kw.value; runSearch(); });

    document.getElementById("catChips").addEventListener("click", function (e) {
      var c = e.target.closest(".chip"); if (!c) return;
      this.querySelectorAll(".chip").forEach(function (x) { x.classList.remove("on"); });
      c.classList.add("on");
      searchState.cat = c.getAttribute("data-cat");
      runSearch();
    });

    document.getElementById("winSeg").addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b) return;
      this.querySelectorAll("button").forEach(function (x) { x.classList.remove("on"); });
      b.classList.add("on");
      searchState.win = b.getAttribute("data-v");
      runSearch();
    });

    document.getElementById("bySeg").addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b) return;
      this.querySelectorAll("button").forEach(function (x) { x.classList.remove("on"); });
      b.classList.add("on");
      searchState.by = b.getAttribute("data-v");
      runSearch();
    });

    document.getElementById("srcSel").addEventListener("change", function () {
      searchState.src = this.value;
      runSearch();
    });

    document.getElementById("smartToggle").addEventListener("click", function () {
      searchState.smart = !searchState.smart;
      this.classList.toggle("on", searchState.smart);
      buildApiDisplay();
    });
  }

  async function renderSearch(arg) {
    // 从全局搜索进入时带入关键词
    if (arg) {
      searchState.kw = decodeURIComponent(arg);
      document.getElementById("kw").value = searchState.kw;
    }
    await runSearch();
  }

  /* ============================================================
   * 视图 4 · 日报归档
   * ============================================================ */
  async function renderDaily(dateArg) {
    var idxEl = document.getElementById("dailyIndex");
    var cardEl = document.getElementById("dailyCard");
    idxEl.innerHTML = skeleton(4);
    var r = await apiGet("/dailies", { limit: "30" });
    applySourceBanner(r.source);
    var items = (r.ok && r.data && Array.isArray(r.data.items)) ? r.data.items : [];
    if (items.length === 0) {
      idxEl.innerHTML = '<div class="feed-empty">暂无日报。</div>';
      cardEl.innerHTML = "";
      return;
    }
    idxEl.innerHTML = items.map(function (d, i) {
      var sub = d.leadTitle ? d.leadTitle.slice(0, 20) : "AI 日报";
      return '<li data-date="' + esc(d.date) + '"' + (i === 0 ? ' class="on"' : "") + ">" +
        '<span class="di-date">' + esc(d.date.slice(5)) + "</span>" +
        '<span class="di-sub">' + weekday(d.date) + " · " + esc(sub) + "</span>" +
        "</li>";
    }).join("");

    idxEl.querySelectorAll("li").forEach(function (li) {
      li.addEventListener("click", function () {
        idxEl.querySelectorAll("li").forEach(function (x) { x.classList.remove("on"); });
        li.classList.add("on");
        loadDailyReport(li.getAttribute("data-date"));
      });
    });

    var target = dateArg || items[0].date;
    var li = idxEl.querySelector('li[data-date="' + target + '"]');
    if (li) {
      idxEl.querySelectorAll("li").forEach(function (x) { x.classList.remove("on"); });
      li.classList.add("on");
    }
    await loadDailyReport(target);
  }

  async function loadDailyReport(date) {
    var cardEl = document.getElementById("dailyCard");
    cardEl.innerHTML = skeleton(3);
    var r = await apiGet("/dailies/" + date);
    applySourceBanner(r.source);
    var rep = (r.ok && r.data && r.data.report) || {};
    if (!rep.date) {
      cardEl.innerHTML = '<div class="feed-empty">该日报暂不可用。</div>';
      return;
    }
    var aihotLink = (rep.links && rep.links.aihot) || (rep.attribution && rep.attribution.url) || "#";

    var sectionsHtml = "";
    (rep.sections || []).forEach(function (sec) {
      var flashes = (sec.items || []).map(function (it) {
        var orig = (it.links && it.links.original) || aihotLink;
        var sname = (it.source && it.source.name) || "";
        return '<div class="dc-flash"><span class="idx">•</span><span>' +
          "<b>" + esc(it.title) + "</b> — " + esc(it.summary || "") + "<br>" +
          '<span class="muted">来源 · ' + esc(sname) + ' · <a href="' + esc(orig) +
          '" target="_blank" rel="noopener">原文 &rarr;</a></span></span></div>';
      }).join("");
      sectionsHtml += '<div class="dc-section"><div class="sec-h">' + esc(sec.label) + "</div>" + flashes + "</div>";
    });

    var flashHtml = "";
    if (Array.isArray(rep.flashes) && rep.flashes.length) {
      var fh = rep.flashes.map(function (f, i) {
        var t = (typeof f === "string") ? f : (f.title || f.text || "");
        return '<div class="dc-flash"><span class="idx">' + (i + 1) + "</span><span>" + esc(t) + "</span></div>";
      }).join("");
      flashHtml = '<div class="dc-section"><div class="sec-h">快讯</div>' + fh + "</div>";
    }

    var title = (rep.lead && rep.lead.title) ? rep.lead.title : "AI 日报 · " + rep.date;
    cardEl.innerHTML =
      '<div class="dc-head">' +
        '<div class="dc-kicker">AI 日报 · DAILY</div>' +
        "<h3>" + esc(title) + "</h3>" +
        '<div class="dc-meta"><span>日期 ' + esc(rep.date) + "</span>" +
        '<span class="muted">' + weekday(rep.date) + "</span></div>" +
      "</div>" +
      sectionsHtml + flashHtml +
      '<div class="dc-foot"><a href="' + esc(aihotLink) + '" target="_blank" rel="noopener">在 AIHOT 查看完整日报（links.aihot）&rarr;</a></div>';
  }

  /* ============================================================
   * 视图 5 · 事件详情（stories/{publicId}）
   * ============================================================ */
  async function renderStory(publicId) {
    var box = document.getElementById("eventBox");
    box.innerHTML = skeleton(4);
    if (!publicId) {
      box.innerHTML = '<div class="feed-empty">缺少事件 ID。<a href="#/hot">返回热点榜 &rarr;</a></div>';
      return;
    }
    var r = await apiGet("/stories/" + publicId);
    applySourceBanner(r.source);
    var st = (r.ok && r.data && r.data.story) || {};
    if (!st.publicId && !st.title) {
      box.innerHTML = '<div class="feed-empty">事件不存在或暂不可用（ID 可能有误）。<a href="#/hot">返回热点榜 &rarr;</a></div>';
      return;
    }

    var active = st.status === "active";
    var hasDigest = !!st.digest;
    var badge = (active ? "事件进行中" : "事件已归档") + (hasDigest ? " · 含 AI 综述" : "");
    var digest = hasDigest
      ? '<span class="label">AI 综述：</span>' + esc(st.digest)
      : '<span class="label">AI 综述：</span>综述随事件演化更新，暂未生成。';

    // 时间线：reports 逆序（最新在前）
    var reports = (st.reports || []).slice().sort(function (a, b) {
      return new Date(b.publishedAt) - new Date(a.publishedAt);
    });
    var tl = reports.length
      ? reports.map(function (rp) {
          var sname = (rp.source && rp.source.name) || "";
          return '<div class="tl-item">' +
            '<div class="when">' + fmtBJ(rp.publishedAt) + " · " + esc(sname) + "</div>" +
            '<div class="what">' + esc(rp.title) + "</div></div>";
        }).join("")
      : '<div class="feed-empty">暂无报道时间线。</div>';

    var latest = st.latest
      ? '<div class="latest"><span class="label">最新进展：</span>' + esc(st.latest) + "</div>"
      : "";

    // 相关事件脉络（同故事线，排除自身）
    var storyline = (st.storyline || []).filter(function (x) { return x.publicId && x.publicId !== publicId; });
    var slHtml = "";
    if (storyline.length) {
      slHtml = '<div class="tl-title" style="margin-top:26px">相关事件脉络</div><div class="timeline">' +
        storyline.map(function (x) {
          return '<div class="tl-item"><div class="what"><a href="#/story/' + esc(x.publicId) +
            '" data-nav="story">' + esc(x.title) + '</a> · <span class="muted">' + esc(x.relation || "") + "</span></div></div>";
        }).join("") + "</div>";
    }

    var aihot = (st.links && st.links.aihot) || "#";
    var srcCount = (st.sourceCount != null) ? "来源 · " + st.sourceCount + " 家媒体报道" : "";

    box.innerHTML =
      '<div class="event-head">' +
        '<div class="event-badge ' + (active ? "" : "archived") + '"><span class="dot"></span>' + esc(badge) + "</div>" +
        "<h2>" + esc(st.title) + "</h2>" +
        '<div class="event-meta">' +
          (srcCount ? "<span>" + esc(srcCount) + "</span>" : "") +
          '<span class="muted">公开 ID · ' + esc(st.publicId) + "</span>" +
          '<span class="muted">更新于 北京时间 ' + fmtBJ(st.latestAt || st.firstReportAt) + "</span>" +
        "</div>" +
      "</div>" +
      '<div class="digest">' + digest + "</div>" +
      '<div class="tl-title">报道时间线（逆序）</div>' +
      '<div class="timeline">' + tl + "</div>" +
      latest + slHtml +
      '<div class="event-foot"><a href="' + esc(aihot) + '" target="_blank" rel="noopener">在 AIHOT 查看事件全貌（links.aihot）&rarr;</a></div>';
  }

  /* ============================================================
   * 路由（hash 路由，刷新安全、无需服务端 SPA 兜底）
   * ============================================================ */
  var VIEW_SECTION = {
    home: "view-home", all: "view-all", hot: "view-hot", search: "view-search",
    daily: "view-daily", story: "view-event"
  };

  function currentRoute() {
    var h = location.hash.replace(/^#/, "");
    var parts = h.split("/").filter(Boolean);
    if (parts.length === 0) return { name: "home", arg: null };
    return { name: parts[0], arg: parts[1] || null };
  }

  function navigate(name, arg) {
    var h = "#/" + name + (arg ? "/" + encodeURIComponent(arg) : "");
    if (location.hash === h) { render(); }
    else { location.hash = h; }
  }

  async function render() {
    var r = currentRoute();
    var sec = VIEW_SECTION[r.name] || "view-home";

    // 隐藏首页「演示」态由横幅控制；切换视图时重置所有视图显示
    document.querySelectorAll(".view").forEach(function (v) { v.classList.remove("on"); });
    document.getElementById(sec).classList.add("on");

    // 导航高亮（事件详情归属热点榜高亮）
    document.querySelectorAll(".navlinks a").forEach(function (a) {
      var v = a.getAttribute("data-view");
      a.classList.toggle("on", v === r.name || (r.name === "story" && v === "hot"));
    });
    window.scrollTo(0, 0);

    try {
      if (r.name === "home") await renderHome();
      else if (r.name === "hot") await renderHot();
      else if (r.name === "search") await renderSearch(r.arg);
      else if (r.name === "daily") await renderDaily(r.arg);
      else if (r.name === "all") await renderAll();
      else if (r.name === "story") await renderStory(r.arg);
      else await renderHome();
    } catch (e) {
      // 兜底：任何视图异常都不白屏
      var el = document.getElementById(sec);
      var box = el.querySelector("#feedList, #hotList, #searchResults, #dailyCard, #eventBox");
      if (box) box.innerHTML = '<div class="feed-empty">加载失败，请稍后重试。</div>';
    }
  }

  /* 首页分类快捷筛选（视觉过滤，与原型一致） */
  function initHomeFilter() {
    var filter = document.getElementById("homeFilter");
    filter.addEventListener("click", function (e) {
      var c = e.target.closest(".qchip"); if (!c) return;
      this.querySelectorAll(".qchip").forEach(function (x) { x.classList.remove("on"); });
      c.classList.add("on");
      var cat = c.getAttribute("data-cat");
      var shown = 0;
      document.querySelectorAll("#feedList .card").forEach(function (card) {
        var ok = cat === "all" || card.getAttribute("data-cat") === cat;
        card.style.display = ok ? "" : "none";
        if (ok) shown++;
      });
      var empty = document.getElementById("feedEmpty");
      if (shown === 0) {
        if (!empty) {
          empty = document.createElement("div");
          empty.id = "feedEmpty"; empty.className = "feed-empty";
          document.getElementById("feedList").appendChild(empty);
        }
        empty.innerHTML = '<b>未进入精选 ·</b> 当前分类下暂无策展条目，已回退至全部结果（视觉示意）。';
      } else if (empty) {
        empty.remove();
      }
    });
  }

  /* 全局搜索：回车 / 提交 &rarr; 跳转检索中心并带入关键词 */
  function initGlobalSearch() {
    var form = document.getElementById("globalSearchForm");
    var input = document.getElementById("globalSearch");
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var q = input.value.trim();
      navigate("search", q);
    });
  }

  /* 顶部品牌 / 导航点击 */
  function initNav() {
    /* data-nav: 动态内容中的导航链接（如"查看完整热点榜 →"、品牌 logo） */
    document.querySelectorAll("[data-nav]").forEach(function (a) {
      a.addEventListener("click", function (e) {
        e.preventDefault();
        navigate(a.getAttribute("data-nav"));
      });
    });
    /* data-view: 顶部导航栏四个主按钮（精选 / 热点榜 / 检索 / 日报） */
    document.querySelectorAll(".navlinks a[data-view]").forEach(function (a) {
      a.addEventListener("click", function (e) {
        e.preventDefault();
        navigate(a.getAttribute("data-view"));
      });
    });
  }

  /* ---------- 启动 ---------- */
  function boot() {
    initNav();
    initGlobalSearch();
    initHomeFilter();
    initAllFilter();
    initSearchControls();
    window.addEventListener("hashchange", render);
    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
