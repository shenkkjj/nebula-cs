"use strict";
(() => {
  const pages = [...document.querySelectorAll("[data-page]")];
  const nav = [...document.querySelectorAll("[data-nav]")];

  function escapeHtml(text) {
    return String(text ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
  }

  async function api(path, options) {
    const res = await fetch(path, options);
    const text = await res.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
    if (res.status === 401) {
      location.href = "/login?next=/admin";
      throw new Error("请先登录");
    }
    if (!res.ok && data.error) throw new Error(data.error);
    if (!res.ok) throw new Error("请求失败");
    return data;
  }

  async function loadOverview() {
    const status = document.getElementById("overviewStatus");
    const panel = document.getElementById("overviewData");
    const refresh = document.getElementById("btnOverview");
    if (refresh.disabled) return;
    refresh.disabled = true;
    status.className = "overview-status small muted";
    status.textContent = "正在加载数据…";
    const put = (id, value) => { document.getElementById(id).textContent = value; };
    const number = new Intl.NumberFormat("zh-CN");
    const time = (value) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "暂无记录";
    try {
      const data = await api("/api/admin/overview");
      put("metricWaiting", number.format(data.tickets.waiting));
      put("metricActive", number.format(data.tickets.active));
      put("metricClosed", number.format(data.tickets.closed));
      put("metricHelpful", data.feedback.total ? `${(100 * data.feedback.helpful / data.feedback.total).toFixed(1)}%` : "—");
      put("metricFeedbackCount", data.feedback.total ? `共 ${number.format(data.feedback.total)} 条评价` : "近七日暂无评价");
      const probe = document.getElementById("overviewProbe");
      probe.className = `pill${data.probe ? (data.probe.ok ? " ok" : " warn") : ""}`;
      probe.textContent = data.probe ? (data.probe.ok ? "自检通过" : "维护中") : "尚未自检";
      const engines = { campus: "本地校园知识库", dify: "Dify 知识库", lite: "规则问答（演示）" };
      put("overviewEngine", engines[data.engine] || "未知");
      put("overviewChecked", time(data.probe?.checked_at));
      document.getElementById("overviewDocuments").hidden = !data.local_knowledge;
      if (data.local_knowledge) {
        put("overviewKnowledge", `${number.format(data.local_knowledge.documents)} 份文档 · ${number.format(data.local_knowledge.segments)} 个启用分段`);
      }
      status.textContent = `更新于 ${time(data.updated_at)}`;
      panel.hidden = false;
    } catch {
      status.className = "overview-status form-status";
      status.textContent = panel.hidden ? "数据暂不可用，请重试。" : "刷新失败，当前显示上次加载的数据。";
    } finally {
      refresh.disabled = false;
    }
  }

  function show(name) {
    const page = pages.some((item) => item.dataset.page === name) ? name : "overview";
    for (const item of pages) item.hidden = item.dataset.page !== page;
    for (const item of nav) {
      if (item.dataset.nav === page) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    }
    if (page === "overview") loadOverview();
    if (page === "docs") loadDocs();
    if (page === "segments") loadSegments();
    if (page === "handoffs") loadHandoffs();
    if (page === "feedback") loadFeedback();
    if (page === "probe") loadProbe();
    if (page === "audit") loadAudit();
    if (page === "config") loadConfig();
    if (page === "eval") loadEval();
  }

  function renderFaqCheck(data) {
    const box = document.getElementById("faqCheck");
    if (!box) return;
    const segments = data.segment_count == null ? "还不知道" : String(data.segment_count);
    const hits = (data.title_hits || []).map((item) => {
      const mark = item.seen == null ? "未核对" : item.seen ? "片段里能看到" : "片段里没看到";
      return `<li>${escapeHtml(item.title)} · ${mark}</li>`;
    }).join("");
    const sample = (data.title_sample || []).map((title) => `<li>${escapeHtml(title)}</li>`).join("");
    box.innerHTML = `<div class="panel-body">
      <p>本地 FAQ <strong>${data.local_count || 0}</strong> 条（${escapeHtml(data.document || "")}）· 知识库分段 <strong>${escapeHtml(segments)}</strong></p>
      ${data.warning ? `<p class="form-status pending">${escapeHtml(data.warning)}</p>` : ""}
      <p class="small muted">标题抽查</p>
      <ul class="small">${hits || sample || "<li>没有标题</li>"}</ul>
    </div>`;
  }

  async function loadDocs() {
    api("/api/admin/faq-check").then(renderFaqCheck).catch(() => {
      const box = document.getElementById("faqCheck");
      if (box) box.innerHTML = '<p class="empty">条数核对暂时失败，文档列表仍可查看。</p>';
    });
    const data = await api("/api/admin/documents");
    document.getElementById("docsHint").textContent = data.hint || data.error || "";
    const body = document.getElementById("docsBody");
    if (!data.documents || !data.documents.length) {
      body.innerHTML = `<tr><td colspan="4">${escapeHtml(data.configured ? "知识库里还没有文档。" : "未配置知识库 API，列表为空。")}</td></tr>`;
      return;
    }
    body.innerHTML = data.documents.map((doc) => {
      const segments = data.engine === "campus"
        ? `<button type="button" class="btn btn-quiet btn-sm" data-open="${escapeHtml(doc.id)}">分段</button> `
        : "";
      const count = doc.segment_count == null ? "" : ` · ${doc.segment_count} 段`;
      return `<tr>
      <td>${escapeHtml(doc.name)}</td><td>${escapeHtml(doc.source)}</td><td>${escapeHtml(doc.indexing_status || "")}${escapeHtml(count)}</td>
      <td>${segments}<button type="button" class="btn btn-quiet btn-sm" data-del="${escapeHtml(doc.id)}">删除</button></td>
    </tr>`;
    }).join("");
  }

  async function loadSegmentDocs(selected) {
    const data = await api("/api/admin/documents");
    const select = document.getElementById("segmentDoc");
    const hint = document.getElementById("segmentHint");
    if (data.engine !== "campus") {
      if (hint) hint.textContent = "分段编辑只在自建知识库里。当前引擎不使用这套分段。";
      select.innerHTML = "";
      document.getElementById("segmentBody").innerHTML = '<tr><td colspan="3">当前不是自建知识库。</td></tr>';
      return null;
    }
    if (hint) hint.textContent = "改一条就重新索引。校规只来自这里的正文。";
    select.innerHTML = (data.documents || []).map((doc) => {
      const mark = String(doc.id) === String(selected) ? " selected" : "";
      return `<option value="${escapeHtml(doc.id)}"${mark}>${escapeHtml(doc.name)}</option>`;
    }).join("");
    return data;
  }

  let pendingSegmentId = "";

  async function loadSegments(preferredId) {
    const select = document.getElementById("segmentDoc");
    const wanted = preferredId || pendingSegmentId || (select && select.value) || "";
    pendingSegmentId = "";
    const data = await loadSegmentDocs(wanted);
    if (!data || data.engine !== "campus") return;
    if (wanted && [...select.options].some((opt) => opt.value === String(wanted))) {
      select.value = String(wanted);
    }
    const id = (select && select.value) || (data.documents[0] && data.documents[0].id);
    if (!id) {
      document.getElementById("segmentBody").innerHTML = '<tr><td colspan="3">还没有文档。</td></tr>';
      return;
    }
    const detail = await api("/api/admin/documents/" + encodeURIComponent(id));
    const rows = (detail.document && detail.document.segments) || [];
    const body = document.getElementById("segmentBody");
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="3">这篇还没有分段。</td></tr>';
      return;
    }
    body.innerHTML = rows.map((row) => `<tr>
      <td>${escapeHtml(row.title)}</td>
      <td class="clip">${escapeHtml(row.body)}</td>
      <td>
        <button type="button" class="btn btn-quiet btn-sm" data-edit="${escapeHtml(row.id)}">编辑</button>
        <button type="button" class="btn btn-quiet btn-sm" data-drop="${escapeHtml(row.id)}">删除</button>
      </td>
    </tr>`).join("");
    body.querySelectorAll("[data-edit]").forEach((button) => {
      button.addEventListener("click", () => {
        const row = rows.find((item) => String(item.id) === button.dataset.edit);
        if (!row) return;
        const form = document.getElementById("segmentForm");
        form.segment_id.value = row.id;
        form.title.value = row.title;
        form.body.value = row.body;
      });
    });
  }

  async function loadHandoffs() {
    const data = await api("/api/admin/handoffs");
    const tickets = document.getElementById("handoffBody");
    const sessions = document.getElementById("sessionBody");
    if (!data.tickets.length) {
      tickets.innerHTML = '<tr><td colspan="6">还没有转人工。</td></tr>';
    } else {
      tickets.innerHTML = data.tickets.map((row) => {
        const steps = (row.traces || []).map((item) => {
          const inner = (item.trace || []).map((step) => `<li>${escapeHtml(step.step)} · ${escapeHtml(step.detail || "")}</li>`).join("");
          return `<div><p>${escapeHtml(item.created_at)} · ${escapeHtml(item.decision)} · ${escapeHtml(item.question)}</p><ul>${inner}</ul></div>`;
        }).join("");
        return `<tr>
          <td>${escapeHtml(row.created_at)}</td>
          <td>${escapeHtml(row.public_id)}</td>
          <td>${escapeHtml(row.status)}</td>
          <td>${escapeHtml(row.source)}</td>
          <td class="clip">${escapeHtml(row.first_question)}</td>
          <td>${escapeHtml(row.assignee_name || "—")}</td>
        </tr>${steps ? `<tr><td colspan="6">${steps}</td></tr>` : ""}`;
      }).join("");
    }
    if (!data.sessions.length) {
      sessions.innerHTML = '<tr><td colspan="5">还没有问答记录。</td></tr>';
      return;
    }
    sessions.innerHTML = data.sessions.map((row) => `<tr>
      <td>${escapeHtml(row.created_at)}</td>
      <td>${escapeHtml(row.session)}</td>
      <td class="clip">${escapeHtml(row.question)}</td>
      <td class="clip">${escapeHtml(row.rewritten)}</td>
      <td>${escapeHtml(row.decision)}</td>
    </tr>`).join("");
  }

  async function loadFeedback() {
    const form = document.getElementById("feedbackFilters");
    const helpful = form ? new FormData(form).get("helpful") : "";
    const query = helpful ? "?helpful=" + encodeURIComponent(helpful) : "";
    const data = await api("/api/admin/feedback" + query);
    document.getElementById("feedbackExport").href = "/api/admin/feedback.csv" + query;
    const summary = data.summary || {};
    const rate = summary.total ? `差评率 ${(summary.unhappy_rate * 100).toFixed(1)}%` : "还没有评价";
    document.getElementById("feedbackSummary").textContent = `近 ${summary.days || 7} 日：有帮助 ${summary.helpful || 0}，没解决 ${summary.unhappy || 0}。${rate}`;
    const body = document.getElementById("feedbackBody");
    if (!data.rows.length) {
      body.innerHTML = '<tr><td colspan="5">还没有评价。</td></tr>';
      return;
    }
    body.innerHTML = data.rows.map((row) => {
      const action = row.helpful
        ? "—"
        : `<select class="select" aria-label="坏例类型"><option value="wrong">答错</option><option value="cite">引用不对</option><option value="miss-refuse">该拒没拒</option><option value="over-refuse">不该拒却拒</option><option value="other">其他</option></select> <button type="button" class="btn btn-quiet btn-sm" data-bad="${row.message_id}">加入评测坏例</button>`;
      return `<tr>
      <td>${escapeHtml(row.updated_at)}</td>
      <td>${row.helpful ? "有帮助" : "没解决"}</td>
      <td class="clip">${escapeHtml(row.question)}</td>
      <td class="clip">${escapeHtml(row.answer)}</td>
      <td>${action}</td>
    </tr>`;
    }).join("");
  }

  async function loadProbe() {
    const data = await api("/api/admin/probe");
    const probe = data.probe;
    const box = document.getElementById("probeBox");
    if (!probe) {
      box.innerHTML = '<div class="empty"><span class="mark" aria-hidden="true">云</span><p>还没有自检记录。点「立即自检」。</p></div>';
      return;
    }
    const checks = (probe.checks || []).map((item) => `<li class="${item.ok ? "ok" : "bad"}"><span class="dot"></span><div><p class="t">${escapeHtml(item.name)}</p><p class="d">${escapeHtml(item.detail || "")}</p></div></li>`).join("");
    box.innerHTML = `<div class="panel-body"><p><span class="badge ${probe.ok ? "ok" : "bad"}">${probe.ok ? "正常" : "失败"}</span> <span class="small muted">${escapeHtml(probe.checked_at || "")}</span></p><ol class="trace" style="margin-top:16px">${checks}</ol></div>`;
  }

  async function loadAudit() {
    const form = document.getElementById("auditFilters");
    const params = new URLSearchParams(new FormData(form));
    const data = await api("/api/admin/audit?" + params.toString());
    const body = document.getElementById("auditBody");
    document.getElementById("auditExport").href = "/api/admin/audit.csv?" + params.toString();
    if (!data.rows.length) {
      body.innerHTML = '<tr><td colspan="7">没有符合条件的记录。</td></tr>';
      return;
    }
    body.innerHTML = data.rows.map((row, index) => {
      const id = "ad-" + index;
      const steps = ((row.detail && row.detail.trace) || []).map((step, index) => `<li class="${step.ok ? "ok" : "bad"}"><span class="dot">${index + 1}</span><div><p class="t">${escapeHtml(step.step)}</p><p class="d">${escapeHtml(step.detail || "")}</p></div></li>`).join("");
      const toggle = steps ? `<button type="button" class="row-toggle" aria-expanded="false" aria-controls="${id}">›</button>` : "";
      const detail = steps ? `<tr class="detail-row" id="${id}" hidden><td></td><td colspan="6"><div class="detail"><ol class="trace">${steps}</ol></div></td></tr>` : "";
      const tone = /拒|拦截|失败/.test(row.decision || "") ? "bad" : /通过/.test(row.decision || "") ? "ok" : /转人工|维护/.test(row.decision || "") ? "info" : "";
      return `<tr><td>${toggle}</td><td>${escapeHtml(row.created_at)}</td><td>${escapeHtml(row.session_ref)}</td><td class="clip">${escapeHtml(row.question)}</td><td><span class="badge ${tone}">${escapeHtml(row.decision || "—")}</span></td><td class="clip">${escapeHtml(row.source)}</td><td class="num">${row.latency_ms ?? "—"}</td></tr>${detail}`;
    }).join("");
  }

  async function loadConfig() {
    const data = await api("/api/admin/config");
    const form = document.getElementById("configForm");
    const cfg = data.config || {};
    form.score_threshold.value = cfg.score_threshold;
    form.max_citations.value = cfg.max_citations;
    form.refusal_text.value = cfg.refusal_text || "";
    form.probe_question.value = cfg.probe_question || "";
    form.probe_expect.value = cfg.probe_expect || "";
    form.auto_ticket_on_refusal.checked = !!cfg.auto_ticket_on_refusal;
    form.faq_shortcut.checked = !!cfg.faq_shortcut;
    document.getElementById("configNote").textContent = data.note || "";
  }

  function metricCell(key, metrics, targets, item) {
    const value = metrics ? metrics[key] : null;
    if (value === undefined || value === null) return "未运行";
    const text = key.endsWith("_ms") ? value + " ms" : key === "duplicate_citations" ? String(value) : (value * 100).toFixed(1) + "%";
    if (item && item.historical) return `${text} <span class="badge">历史记录</span>`;
    const target = targets && targets[key];
    if (!target) return text;
    const goal = target.value;
    const ok = target.op === ">=" ? value >= goal : target.op === "<=" ? value <= goal : value === goal;
    return `<span class="badge ${ok ? "ok" : "warn"}">${text}</span>`;
  }

  function renderEval(latest) {
    const box = document.getElementById("evalTable");
    const byGroup = {};
    for (const item of latest || []) {
      if (!byGroup[item.group]) byGroup[item.group] = item;
    }
    if (!latest || !latest.length) {
      box.innerHTML = '<div class="empty"><span class="mark" aria-hidden="true">云</span><p>还没有实测结果。选数据集和组别后运行。B、C 需要连上知识库，没跑就不填数。</p></div>';
      document.getElementById("evalExport").hidden = true;
      return;
    }
    const keys = [
      ["in_scope_accuracy", "范围内回答正确率", "≥ 85%"],
      ["hit_at_3", "检索命中率 Hit@3", "≥ 90%"],
      ["out_of_scope_refusal", "库外拒答率", "≥ 90%"],
      ["false_refusal", "范围内误拒率", "≤ 10%"],
      ["duplicate_citations", "重复引用同一文档", "0"],
      ["first_token_p50_ms", "首字 p50", "≤ 3 秒"],
      ["first_token_p95_ms", "首字 p95", "≤ 6 秒"],
    ];
    const head = '<tr><th scope="col">指标</th><th scope="col" class="num">目标</th><th scope="col" class="num">A 改造前规则引擎</th><th scope="col" class="num">B 知识库直出</th><th scope="col" class="num">C 本系统</th></tr>';
    const rows = keys.map(([key, label, goal]) => `<tr><th scope="row">${label}</th><td class="num">${goal}</td>` + ["A", "B", "C"].map((group) => {
      const item = byGroup[group];
      return `<td class="num">${item ? metricCell(key, item.metrics, item.targets, item) : "未运行"}</td>`;
    }).join("") + "</tr>").join("");
    const notes = latest.map((item) => {
      const stamp = item.historical ? "历史记录，不是当前引擎的成绩，数字未改写。" : "";
      return `${item.group} 组 · ${escapeHtml(item.dataset)} · ${item.count} 题。${stamp}${escapeHtml(item.note || "")}`;
    }).join("<br />");
    const missed = latest.map((item) => {
      if (item.historical) {
        return `<p class="small" style="padding:8px 20px">${escapeHtml(item.group)} 组是历史记录。当时的未通过清单不作为当前成绩。</p>`;
      }
      if (item.failure_count == null) return "";
      if (!item.failures || !item.failures.length) {
        return `<p class="small" style="padding:0 20px 12px">${escapeHtml(item.group)} 组这次没有未通过的题。</p>`;
      }
      const rows = item.failures.map((row) => `<tr><td>${escapeHtml(row.id)}</td><td class="clip">${escapeHtml(row.question)}</td><td>${escapeHtml(row.type)}</td><td><span class="badge bad">${escapeHtml(row.label || "未通过")}</span></td></tr>`).join("");
      const more = item.failure_count > item.failures.length ? `<p class="small muted" style="padding:8px 20px">还有 ${item.failure_count - item.failures.length} 条未通过，导出 CSV 可看全部。</p>` : "";
      return `<h2 class="panel-title" style="font-size:21px;padding:16px 20px 8px">${escapeHtml(item.group)} 组未通过</h2><div class="table-wrap"><table class="table"><thead><tr><th>题号</th><th>问题</th><th>类型</th><th>判分</th></tr></thead><tbody>${rows}</tbody></table></div>${more}`;
    }).join("");
    const watches = latest.filter((item) => item.metrics && item.metrics.span_observation).map((item) => {
      const watch = item.metrics.span_observation;
      return `${item.group} 组附加观察：期望证据片段 ${watch.hits}/${watch.count}。${escapeHtml(watch.note || "")}`;
    }).join("<br />");
    box.innerHTML = `<div class="table-wrap"><table class="table"><thead>${head}</thead><tbody>${rows}</tbody></table></div><div class="panel-body small">${notes}${watches ? "<br />" + watches : ""}</div>${missed}`;
    const first = latest[0];
    const foot = document.getElementById("evalExport");
    foot.hidden = false;
    foot.innerHTML = `<a class="btn btn-ghost btn-sm" href="/api/admin/eval/export.md?group=${first.group}&dataset=${first.dataset}">导出 Markdown</a> <a class="btn btn-ghost btn-sm" href="/api/admin/eval/export.csv?group=${first.group}&dataset=${first.dataset}">导出 CSV</a>`;
  }

  async function loadEval() {
    const sets = await api("/api/admin/datasets");
    const select = document.getElementById("evalSet");
    if (!select.options.length) {
      select.innerHTML = (sets.datasets || []).map((item) => `<option value="${item.id}">${item.file} · ${item.count} 题</option>`).join("");
    }
    const status = await api("/api/admin/eval");
    const job = status.job || {};
    const line = document.getElementById("evalStatus");
    if (job.running) {
      line.hidden = false;
      line.textContent = `运行中 ${job.progress || 0} / ${job.total || "?"} ${job.message || ""}`;
    } else if (job.error) {
      line.hidden = false;
      line.textContent = job.error;
    } else {
      line.hidden = true;
    }
    renderEval(status.latest || []);
    if (job.running) setTimeout(loadEval, 1500);
  }

  window.addEventListener("hashchange", () => {
    show(location.hash.slice(1));
    const heading = document.querySelector("[data-page]:not([hidden]) h1");
    heading?.setAttribute("tabindex", "-1");
    heading?.focus();
    window.scrollTo(0, 0);
  });
  document.getElementById("btnOverview").addEventListener("click", loadOverview);
  document.getElementById("docsBody").addEventListener("click", async (event) => {
    const open = event.target.closest("[data-open]");
    if (open) {
      pendingSegmentId = open.dataset.open;
      if (location.hash === "#segments") loadSegments(pendingSegmentId);
      else location.hash = "segments";
      return;
    }
    const button = event.target.closest("[data-del]");
    if (!button) return;
    if (!confirm("删除这篇文档？")) return;
    await api("/api/admin/documents/" + encodeURIComponent(button.dataset.del), { method: "DELETE" });
    loadDocs();
  });
  document.getElementById("btnReseed").addEventListener("click", async () => {
    const status = document.getElementById("uploadStatus");
    status.hidden = false;
    status.textContent = "正在导入样例…";
    try {
      const data = await api("/api/admin/documents/reseed", { method: "POST" });
      status.textContent = data.already ? "样例文档还在，没有重复导入。" : "已重新导入样例 FAQ。";
      loadDocs();
    } catch (err) {
      status.textContent = err.message;
    }
  });
  document.getElementById("btnEmbed").addEventListener("click", async () => {
    const status = document.getElementById("uploadStatus");
    status.hidden = false;
    status.textContent = "正在请求远程向量…";
    try {
      const data = await api("/api/admin/embeddings", { method: "POST" });
      status.textContent = data.ok ? `已写入 ${data.count || 0} 条向量到 Chroma。` : (data.error || "没有生成向量");
    } catch (err) {
      status.textContent = err.message;
    }
  });
  document.getElementById("segmentPick").addEventListener("submit", (event) => {
    event.preventDefault();
    loadSegments().catch((err) => alert(err.message));
  });
  document.getElementById("btnSegmentNew").addEventListener("click", () => {
    const form = document.getElementById("segmentForm");
    form.segment_id.value = "";
    form.title.value = "";
    form.body.value = "";
  });
  document.getElementById("segmentForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const status = document.getElementById("segmentStatus");
    const segmentId = form.segment_id.value;
    const path = segmentId ? "/api/admin/segments/" + encodeURIComponent(segmentId) : "/api/admin/segments";
    status.hidden = false;
    status.textContent = "正在保存…";
    try {
      await api(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: document.getElementById("segmentDoc").value,
          title: form.title.value,
          body: form.body.value,
        }),
      });
      status.textContent = "已保存，下一次问答会用到这条。";
      form.segment_id.value = "";
      loadSegments();
    } catch (err) {
      status.textContent = err.message;
    }
  });
  document.getElementById("segmentBody").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-drop]");
    if (!button) return;
    if (!confirm("删除这个分段？")) return;
    await api("/api/admin/segments/" + encodeURIComponent(button.dataset.drop), { method: "DELETE" });
    loadSegments();
  });
  document.getElementById("uploadForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("uploadStatus");
    const body = new FormData(event.target);
    status.hidden = false;
    status.textContent = "正在上传…";
    const res = await fetch("/api/admin/documents", { method: "POST", body });
    const data = await res.json().catch(() => ({}));
    status.textContent = res.ok ? "已提交，索引状态以列表为准。" : (data.error || "上传失败");
    if (res.ok) loadDocs();
  });
  document.getElementById("btnProbe").addEventListener("click", async () => {
    document.getElementById("probeBox").innerHTML = '<p class="empty">正在自检…</p>';
    await api("/api/admin/probe", { method: "POST" });
    loadProbe();
  });
  document.getElementById("feedbackFilters").addEventListener("submit", (event) => {
    event.preventDefault();
    loadFeedback().catch((err) => alert(err.message));
  });
  document.getElementById("feedbackBody").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-bad]");
    if (!button) return;
    const kind = button.parentElement.querySelector("select");
    button.disabled = true;
    try {
      await api("/api/admin/feedback/bad-case", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: Number(button.dataset.bad), kind: kind ? kind.value : "other" }),
      });
      button.textContent = "已加入";
    } catch (err) {
      button.disabled = false;
      alert(err.message);
    }
  });
  document.getElementById("auditFilters").addEventListener("submit", (event) => {
    event.preventDefault();
    loadAudit();
  });
  document.getElementById("auditBody").addEventListener("click", (event) => {
    const button = event.target.closest(".row-toggle");
    if (!button) return;
    const open = button.getAttribute("aria-expanded") !== "true";
    button.setAttribute("aria-expanded", String(open));
    const row = document.getElementById(button.getAttribute("aria-controls"));
    if (row) row.hidden = !open;
  });
  document.getElementById("configForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const status = document.getElementById("configStatus");
    const payload = {
      score_threshold: Number(form.score_threshold.value),
      max_citations: Number(form.max_citations.value),
      refusal_text: form.refusal_text.value,
      probe_question: form.probe_question.value,
      probe_expect: form.probe_expect.value,
      auto_ticket_on_refusal: form.auto_ticket_on_refusal.checked,
      faq_shortcut: form.faq_shortcut.checked,
    };
    await api("/api/admin/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    status.hidden = false;
    status.textContent = "已保存。下一次问答会用这个引用阈值。";
  });
  document.getElementById("btnEval").addEventListener("click", async () => {
    const line = document.getElementById("evalStatus");
    line.hidden = false;
    line.textContent = "已提交…";
    try {
      await api("/api/admin/eval/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dataset: document.getElementById("evalSet").value, group: document.getElementById("evalGroup").value }),
      });
      loadEval();
    } catch (err) {
      line.textContent = err.message;
    }
  });
  document.getElementById("btnLogout").addEventListener("click", async () => {
    await fetch("/api/logout", { method: "POST" });
    location.href = "/login";
  });

  fetch("/api/me").then(async (res) => {
    if (!res.ok) {
      location.href = "/login?next=/admin";
      return;
    }
    const data = await res.json();
    if (data.user.role !== "admin") {
      location.href = "/agent";
      return;
    }
    document.getElementById("who").textContent = data.user.display_name + " · 管理员";
    show(location.hash.slice(1));
  }).catch(() => {
    document.getElementById("overviewStatus").textContent = "身份校验暂不可用，请刷新页面重试。";
  });
})();
