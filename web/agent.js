"use strict";
(() => {
  const queueEl = document.getElementById("queue");
  const thread = document.getElementById("thread");
  const title = document.getElementById("c-title");
  const sub = document.getElementById("c-sub");
  const badge = document.getElementById("c-badge");
  const replyForm = document.getElementById("replyForm");
  const replyBox = document.getElementById("reply");
  const replyStatus = document.getElementById("replyStatus");
  const tracePanel = document.getElementById("panel-trace");
  const writeStatus = document.getElementById("writeStatus");
  const badStatus = document.getElementById("badStatus");
  const badTarget = document.getElementById("badTarget");
  const badMessage = document.getElementById("badMessage");
  const closeDialog = document.getElementById("closeDialog");
  const closeError = document.getElementById("closeError");
  let me = null;
  let status = "waiting";
  let current = null;
  let selectedMessage = null;

  const sourceClass = { user: "", refusal: "bad", maintenance: "warn" };

  function fmt(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    const p = (n) => String(n).padStart(2, "0");
    return `${p(date.getHours())}:${p(date.getMinutes())}`;
  }

  function emptyDesk(text) {
    return `<div class="empty"><span class="mark" aria-hidden="true">云</span><p>${text}</p></div>`;
  }

  function waitLabel(ticket) {
    const seconds = ticket.status === "active" ? ticket.active_seconds : ticket.wait_seconds;
    const n = Math.max(0, Math.floor((seconds || 0) / 60));
    if (ticket.status === "closed") {
      return ticket.assignee_name ? `${ticket.assignee_name} 已结束` : "已结束";
    }
    if (ticket.status === "active") {
      const mine = me && Number(ticket.assignee_id) === Number(me.user_id);
      if (mine) return `你已接入 ${n} 分`;
      return `${ticket.assignee_name || "坐席"}接入 · ${n} 分`;
    }
    return n < 1 ? "等待不到 1 分" : `等待 ${n} 分`;
  }

  async function api(path, options) {
    const res = await fetch(path, options);
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) {
      location.href = "/login?next=/agent";
      throw new Error("请先登录");
    }
    if (!res.ok) throw new Error(data.error || "请求失败");
    return data;
  }

  function selectTab(button) {
    const list = button.closest('[role="tablist"]');
    for (const tab of list.querySelectorAll('[role="tab"]')) {
      const on = tab === button;
      tab.setAttribute("aria-selected", String(on));
      tab.tabIndex = on ? 0 : -1;
      const panel = document.getElementById("panel-" + tab.dataset.panel);
      if (panel) panel.hidden = !on;
    }
  }

  async function refreshQueue() {
    const data = await api("/api/agent/tickets?status=" + status);
    document.getElementById("tab-waiting").textContent = "待接入 " + (data.counts.waiting || 0);
    document.getElementById("tab-active").textContent = "处理中 " + (data.counts.active || 0);
    document.getElementById("tab-closed").textContent = "已结束 " + (data.counts.closed || 0);
    if (!data.tickets.length) {
      queueEl.innerHTML = emptyDesk("这一栏还没有工单。");
      return;
    }
    queueEl.innerHTML = data.tickets.map((ticket) => {
      const currentMark = current && current.ticket.public_id === ticket.public_id ? ' aria-current="true"' : "";
      const closed = ticket.status === "closed";
      const cls = closed ? "ok" : (sourceClass[ticket.source] || "");
      const label = closed ? "已结束" : ticket.source_label;
      return `<button type="button" class="ticket" data-id="${ticket.public_id}"${currentMark}>
        <span class="row"><span>${ticket.public_id}</span><span class="badge ${cls}">${label}</span></span>
        <span class="q">${escapeHtml(ticket.first_question)}</span>
        <span class="row"><span>${waitLabel(ticket)}</span><span>访客 ${escapeHtml(ticket.visitor || "")}</span></span>
      </button>`;
    }).join("");
  }

  function escapeHtml(text) {
    return String(text || "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
  }

  function decisionClass(decision) {
    const text = decision || "";
    if (/拒|拦截|失败/.test(text)) return "bad";
    if (/维护/.test(text)) return "warn";
    if (/转人工|接入|等待/.test(text)) return "info";
    if (text) return "ok";
    return "";
  }

  function groupStaffCites(citations) {
    const groups = [];
    const index = new Map();
    (citations || []).forEach((raw) => {
      if (!raw) return;
      const key = String(raw.document_id || raw.document_name || "文档");
      let group = index.get(key);
      if (!group) {
        group = { name: raw.document_name || "文档", segments: [] };
        index.set(key, group);
        groups.push(group);
      }
      const pieces = [{ content: raw.content || "", score: typeof raw.score === "number" ? raw.score : -1, title: raw.title || "" }];
      (raw.segments || []).forEach((seg) => {
        if (!seg || !seg.content || seg.content === raw.content) return;
        pieces.push({ content: seg.content, score: typeof seg.score === "number" ? seg.score : -1, title: seg.title || "" });
      });
      pieces.forEach((piece) => {
        if (!piece.content) return;
        if (group.segments.some((item) => item.content === piece.content)) return;
        group.segments.push(piece);
      });
    });
    groups.forEach((group) => group.segments.sort((a, b) => b.score - a.score));
    return groups;
  }

  function inlineCites(meta) {
    const groups = groupStaffCites(meta && meta.citations);
    if (!groups.length) return "";
    return `<div class="hits">${groups.map((group) => {
      const top = group.segments[0];
      const rest = group.segments.slice(1).map((seg) => `<div class="hit merged"><span>${escapeHtml((seg.title ? seg.title + " · " : "") + String(seg.content).slice(0, 80))}</span></div>`).join("");
      const score = typeof top.score === "number" && top.score >= 0 ? top.score.toFixed(2) : "";
      const title = top.title ? " · " + escapeHtml(top.title) : "";
      return `<div class="hit"><span>${escapeHtml(group.name)}${title}</span>${score ? `<span class="s">${score}</span>` : ""}</div>${rest}`;
    }).join("")}</div>`;
  }

  function renderTrace(judgments) {
    if (!judgments || !judgments.length) {
      tracePanel.innerHTML = emptyDesk("这张工单还没有约束层记录。");
      return;
    }
    tracePanel.innerHTML = judgments.map((item) => {
      const steps = (item.trace || []).map((step, index) => {
        const detail = step.detail || "";
        const klass = step.ok === false ? "bad" : /维护/.test(detail) ? "warn" : "ok";
        const timing = typeof step.ms === "number" ? `${step.ms} ms` : (step.ms || "");
        return `<li class="${klass}"><span class="dot">${index + 1}</span><div><p class="t">${escapeHtml(step.step)}</p><p class="d">${escapeHtml(detail)}</p></div><span class="ms">${escapeHtml(String(timing))}</span></li>`;
      }).join("");
      return `<section id="tr-${item.id}"><p class="eyebrow">${escapeHtml(item.decision || "")} · ${fmt(item.created_at)}</p><p class="small">${escapeHtml(item.question_masked || "")}</p><ol class="trace">${steps}</ol></section>`;
    }).join("");
  }

  function renderThread(detail) {
    const ticket = detail.ticket;
    current = detail;
    title.textContent = ticket.public_id + " · " + ticket.first_question;
    const created = fmt(ticket.created_at);
    sub.textContent = "访客 " + (ticket.visitor || "") + " · " + ticket.source_label + (created ? " · " + created + " 创建" : "");
    badge.hidden = false;
    const mine = Number(ticket.assignee_id) === Number(me && me.user_id);
    badge.textContent = ticket.status === "waiting" ? "待接入" : ticket.status === "active" ? (mine ? "处理中 · 你已接入" : "处理中") : "已结束";
    badge.className = "badge " + (ticket.status === "closed" ? "ok" : ticket.status === "active" ? "info" : "");
    document.getElementById("btnClose").hidden = ticket.status === "closed" || !mine;
    replyForm.hidden = ticket.status !== "active" || !mine;
    const byMessage = new Map((detail.judgments || []).filter((item) => item.message_id).map((item) => [item.message_id, item]));
    thread.innerHTML = detail.messages.map((msg) => {
      if (msg.role === "system") return `<p class="sys-line">${escapeHtml(msg.body)}</p>`;
      const klass = msg.role === "user" ? "visitor" : msg.role === "agent" ? "agent" : "bot";
      const who = msg.role === "user" ? "访客" : msg.role === "agent" ? (msg.author || "坐席") + " · 人工客服" : "机器人";
      const judgment = byMessage.get(msg.id);
      const badge = judgment ? `<span class="badge ${decisionClass(judgment.decision)}">${escapeHtml(judgment.decision || "")}</span>` : "";
      const cites = msg.role === "bot" ? inlineCites(msg.meta) : "";
      const refused = judgment && decisionClass(judgment.decision) === "bad" ? " refused" : "";
      const tools = msg.role === "bot"
        ? `<div class="msg-tools"><button type="button" class="btn btn-quiet btn-sm" data-pick="${msg.id}">标记这条</button>${judgment ? `<button type="button" class="btn btn-quiet btn-sm" data-trace="${judgment.id}">查看判定</button>` : ""}</div>`
        : "";
      return `<div class="msg ${klass}${refused}"><div class="meta">${escapeHtml(who)} · ${fmt(msg.created_at)} ${badge}</div><div class="bubble">${escapeHtml(msg.body)}</div>${cites}${tools}</div>`;
    }).join("") || emptyDesk("还没有消息。");
    renderTrace(detail.judgments);
    const question = document.querySelector("#writeForm [name=question]");
    if (question && !question.value) question.value = ticket.first_question;
  }

  async function openTicket(publicId) {
    let detail = await api("/api/agent/tickets/" + encodeURIComponent(publicId));
    if (detail.ticket.status === "waiting") {
      try {
        detail = await api("/api/agent/tickets/" + encodeURIComponent(publicId) + "/take", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
      } catch (err) {
        if (!String(err.message || "").includes("已被")) throw err;
      }
    }
    renderThread(detail);
    await refreshQueue();
  }

  document.getElementById("queue").addEventListener("click", (event) => {
    const button = event.target.closest(".ticket");
    if (!button) return;
    openTicket(button.dataset.id).catch((err) => alert(err.message));
  });

  for (const tab of document.querySelectorAll(".queue [role=tab]")) {
    tab.addEventListener("click", () => {
      status = tab.dataset.status;
      for (const item of document.querySelectorAll(".queue [role=tab]")) {
        const on = item === tab;
        item.setAttribute("aria-selected", String(on));
        item.tabIndex = on ? 0 : -1;
      }
      refreshQueue().catch(() => {});
    });
  }
  for (const tab of document.querySelectorAll(".ctx [role=tab]")) {
    tab.addEventListener("click", () => selectTab(tab));
  }

  replyBox.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      replyForm.requestSubmit();
    }
  });
  replyForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    replyStatus.hidden = true;
    if (!current) return;
    const text = replyBox.value.trim();
    if (!text) {
      replyStatus.hidden = false;
      replyStatus.textContent = "回复内容不能为空";
      return;
    }
    try {
      const detail = await api("/api/agent/tickets/" + current.ticket.public_id + "/reply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      replyBox.value = "";
      renderThread(detail);
    } catch (err) {
      replyStatus.hidden = false;
      replyStatus.textContent = err.message;
    }
  });

  function bindArrowTabs(selector) {
    const tabs = [...document.querySelectorAll(selector)];
    for (const tab of tabs) {
      tab.addEventListener("keydown", (event) => {
        const index = tabs.indexOf(tab);
        const move = { ArrowRight: 1, ArrowLeft: -1, Home: "home", End: "end" }[event.key];
        if (move === undefined) return;
        event.preventDefault();
        const target = move === "home" ? tabs[0] : move === "end" ? tabs[tabs.length - 1] : tabs[(index + move + tabs.length) % tabs.length];
        target.focus();
        target.click();
      });
    }
  }
  bindArrowTabs(".queue [role=tab]");
  bindArrowTabs(".ctx [role=tab]");

  thread.addEventListener("click", (event) => {
    const jump = event.target.closest("[data-trace]");
    if (jump) {
      for (const node of thread.querySelectorAll(".msg")) node.classList.toggle("is-selected", node.contains(jump));
      selectTab(document.getElementById("tab-trace"));
      const node = document.getElementById("tr-" + jump.dataset.trace);
      if (node) node.scrollIntoView({ block: "nearest" });
      return;
    }
    const button = event.target.closest("[data-pick]");
    if (!button || !current) return;
    selectedMessage = Number(button.dataset.pick);
    badMessage.value = String(selectedMessage);
    const message = current.messages.find((item) => item.id === selectedMessage);
    badTarget.textContent = "针对：" + ((message && message.body) || "").slice(0, 80);
    selectTab(document.getElementById("tab-bad"));
  });

  async function pollWriteback(id) {
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const data = await api("/api/agent/writebacks/" + id);
      const row = data.writeback || {};
      if (row.status === "completed") {
        writeStatus.className = "form-status";
        writeStatus.textContent = "索引完成";
        return;
      }
      if (row.status === "failed") {
        writeStatus.className = "form-status pending";
        writeStatus.textContent = (row.error || "写入失败") + " 草稿还在上面，可以再提交。";
        return;
      }
      writeStatus.className = "form-status pending";
      writeStatus.textContent = "索引中";
      await new Promise((resolve) => setTimeout(resolve, 700));
    }
  }

  document.getElementById("writeForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!current) return;
    const form = event.target;
    writeStatus.hidden = false;
    writeStatus.className = "form-status pending";
    writeStatus.textContent = "索引中";
    try {
      const data = await api("/api/agent/tickets/" + current.ticket.public_id + "/writeback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: form.question.value, answer: form.answer.value }),
      });
      const row = data.writeback || {};
      if (row.status === "completed") {
        writeStatus.className = "form-status";
        writeStatus.textContent = "索引完成";
      } else if (row.status === "indexing" && row.id) {
        await pollWriteback(row.id);
      } else {
        writeStatus.className = "form-status pending";
        writeStatus.textContent = "索引中";
      }
    } catch (err) {
      writeStatus.className = "form-status pending";
      writeStatus.textContent = err.message + " 草稿还在上面，可以再提交。";
    }
  });

  document.getElementById("badForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    badStatus.hidden = true;
    if (!badMessage.value) {
      badStatus.hidden = false;
      badStatus.textContent = "请先在对话里选择一条机器人回答";
      return;
    }
    const form = event.target;
    const kind = (new FormData(form).get("kind") || "").toString();
    if (!kind) {
      badStatus.hidden = false;
      badStatus.textContent = "请选择问题类型";
      return;
    }
    try {
      const data = await api("/api/agent/bad-cases", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: Number(badMessage.value), kind, expect: form.expect.value }),
      });
      badStatus.hidden = false;
      badStatus.className = "form-status";
      badStatus.textContent = "已加入评测集 " + data.bad_case.id;
    } catch (err) {
      badStatus.hidden = false;
      badStatus.textContent = err.message;
    }
  });

  document.getElementById("btnClose").addEventListener("click", () => {
    closeError.hidden = true;
    closeDialog.showModal();
  });
  document.getElementById("closeCancel").addEventListener("click", () => closeDialog.close());
  document.getElementById("closeDismiss").addEventListener("click", () => closeDialog.close());
  document.getElementById("closeForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const note = event.target.note.value.trim();
    if (!note) {
      closeError.hidden = false;
      closeError.textContent = "请写一句处理说明";
      return;
    }
    try {
      const detail = await api("/api/agent/tickets/" + current.ticket.public_id + "/close", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note }),
      });
      closeDialog.close();
      event.target.reset();
      renderThread(detail);
      await refreshQueue();
    } catch (err) {
      closeError.hidden = false;
      closeError.textContent = err.message;
    }
  });

  document.getElementById("btnLogout").addEventListener("click", async () => {
    await fetch("/api/logout", { method: "POST" });
    location.href = "/login";
  });

  async function boot() {
    const res = await fetch("/api/me");
    if (!res.ok) {
      location.href = "/login?next=/agent";
      return;
    }
    me = (await res.json()).user;
    document.getElementById("who").textContent = me.display_name + " · " + (me.role === "admin" ? "管理员" : "坐席");
    async function refreshPill() {
      const probe = await fetch("/api/portal/state?session=staff-probe").then((res) => res.json()).catch(() => ({}));
      const pill = document.getElementById("kbPill");
      if (!pill) return;
      if (probe.maintenance) {
        pill.textContent = "知识库维护中";
        pill.className = "pill warn";
      } else if (probe.probe_ok) {
        pill.textContent = "知识库就绪";
        pill.className = "pill ok";
      }
    }
    await refreshPill();
    await refreshQueue();
    setInterval(() => {
      refreshQueue().catch(() => {});
      refreshPill().catch(() => {});
    }, 5000);
  }

  boot().catch((err) => {
    queueEl.innerHTML = emptyDesk(escapeHtml(err.message));
  });
})();
