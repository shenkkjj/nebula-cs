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

  function show(name) {
    const page = pages.some((item) => item.dataset.page === name) ? name : "docs";
    for (const item of pages) item.hidden = item.dataset.page !== page;
    for (const item of nav) {
      if (item.dataset.nav === page) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    }
    if (page === "docs") loadDocs();
    if (page === "probe") loadProbe();
    if (page === "audit") loadAudit();
    if (page === "config") loadConfig();
    if (page === "eval") loadEval();
  }

  async function loadDocs() {
    const data = await api("/api/admin/documents");
    document.getElementById("docsHint").textContent = data.hint || data.error || "";
    const body = document.getElementById("docsBody");
    if (!data.documents || !data.documents.length) {
      body.innerHTML = `<tr><td colspan="4">${escapeHtml(data.configured ? "知识库里还没有文档。" : "未配置知识库 API，列表为空。")}</td></tr>`;
      return;
    }
    body.innerHTML = data.documents.map((doc) => `<tr>
      <td>${escapeHtml(doc.name)}</td><td>${escapeHtml(doc.source)}</td><td>${escapeHtml(doc.indexing_status || "")}</td>
      <td><button type="button" class="btn btn-quiet btn-sm" data-del="${escapeHtml(doc.id)}">删除</button></td>
    </tr>`).join("");
  }

  async function loadProbe() {
    const data = await api("/api/admin/probe");
    const probe = data.probe;
    const box = document.getElementById("probeBox");
    if (!probe) {
      box.innerHTML = '<p class="empty">还没有自检记录。点「立即自检」。</p>';
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
      const steps = ((row.detail && row.detail.trace) || []).map((step) => `<li class="${step.ok ? "ok" : "bad"}"><span class="dot"></span><div><p class="t">${escapeHtml(step.step)}</p><p class="d">${escapeHtml(step.detail || "")}</p></div></li>`).join("");
      const toggle = steps ? `<button type="button" class="row-toggle" aria-expanded="false" aria-controls="${id}">›</button>` : "";
      const detail = steps ? `<tr class="detail-row" id="${id}" hidden><td></td><td colspan="6"><div class="detail"><ol class="trace">${steps}</ol></div></td></tr>` : "";
      return `<tr><td>${toggle}</td><td>${escapeHtml(row.created_at)}</td><td>${escapeHtml(row.session_ref)}</td><td class="clip">${escapeHtml(row.question)}</td><td>${escapeHtml(row.decision)}</td><td class="clip">${escapeHtml(row.source)}</td><td class="num">${row.latency_ms ?? "—"}</td></tr>${detail}`;
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
    document.getElementById("configNote").textContent = data.note || "";
  }

  function metricCell(key, metrics, targets) {
    const value = metrics ? metrics[key] : null;
    if (value === undefined || value === null) return "未运行";
    const target = targets && targets[key];
    let text = key.endsWith("_ms") ? value + " ms" : key === "duplicate_citations" ? String(value) : (value * 100).toFixed(1) + "%";
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
      box.innerHTML = '<p class="empty">还没有实测结果。选数据集和组别后运行。B、C 需要本机 Dify，没跑就不填数。</p>';
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
    const head = "<tr><th>指标</th><th>目标</th><th>A 改造前规则引擎</th><th>B Dify 直出</th><th>C 本系统</th></tr>";
    const rows = keys.map(([key, label, goal]) => `<tr><th>${label}</th><td>${goal}</td>` + ["A", "B", "C"].map((group) => {
      const item = byGroup[group];
      return `<td>${item ? metricCell(key, item.metrics, item.targets) : "未运行"}</td>`;
    }).join("") + "</tr>").join("");
    const notes = latest.map((item) => `${item.group} 组 · ${escapeHtml(item.dataset)} · ${item.count} 题。${escapeHtml(item.note || "")}`).join("<br />");
    box.innerHTML = `<div class="table-wrap"><table class="table"><thead>${head}</thead><tbody>${rows}</tbody></table></div><div class="panel-body small">${notes}</div>`;
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

  window.addEventListener("hashchange", () => show(location.hash.slice(1)));
  document.getElementById("docsBody").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-del]");
    if (!button) return;
    if (!confirm("删除这篇文档？")) return;
    await api("/api/admin/documents/" + encodeURIComponent(button.dataset.del), { method: "DELETE" });
    loadDocs();
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
    };
    await api("/api/admin/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    status.hidden = false;
    status.textContent = "已保存，下一次问答即使用新参数。";
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
    show(location.hash.slice(1) || "docs");
  });
})();
