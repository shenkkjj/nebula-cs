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

  function waitLabel(ticket) {
    const seconds = ticket.status === "active" ? ticket.active_seconds : ticket.wait_seconds;
    const n = Math.max(0, Math.floor((seconds || 0) / 60));
    if (ticket.status === "closed") return "已结束";
    if (ticket.status === "active") return `已接入 ${n} 分`;
    return n < 1 ? "刚刚" : `等待 ${n} 分`;
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
      queueEl.innerHTML = '<p class="empty">这一栏还没有工单。</p>';
      return;
    }
    queueEl.innerHTML = data.tickets.map((ticket) => {
      const currentMark = current && current.ticket.public_id === ticket.public_id ? ' aria-current="true"' : "";
      const cls = sourceClass[ticket.source] || "";
      return `<button type="button" class="ticket" data-id="${ticket.public_id}"${currentMark}>
        <span class="row"><span>${ticket.public_id}</span><span class="badge ${cls}">${ticket.source_label}</span></span>
        <span class="q">${escapeHtml(ticket.first_question)}</span>
        <span class="row"><span>${waitLabel(ticket)}</span><span>访客 ${escapeHtml(ticket.visitor || "")}</span></span>
      </button>`;
    }).join("");
  }

  function escapeHtml(text) {
    return String(text || "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
  }

  function renderTrace(judgments) {
    if (!judgments || !judgments.length) {
      tracePanel.innerHTML = '<p class="empty">这张工单还没有约束层记录。</p>';
      return;
    }
    tracePanel.innerHTML = judgments.map((item) => {
      const steps = (item.trace || []).map((step) => {
        const klass = step.ok ? "ok" : "bad";
        return `<li class="${klass}"><span class="dot"></span><div><p class="t">${escapeHtml(step.step)}</p><p class="d">${escapeHtml(step.detail || "")}</p></div><span class="ms">${step.ms || 0} ms</span></li>`;
      }).join("");
      return `<section><p class="eyebrow">${escapeHtml(item.decision || "")} · ${fmt(item.created_at)}</p><p class="small">${escapeHtml(item.question_masked || "")}</p><ol class="trace">${steps}</ol></section>`;
    }).join("");
  }

  function renderThread(detail) {
    const ticket = detail.ticket;
    current = detail;
    title.textContent = ticket.public_id + " · " + ticket.first_question;
    sub.textContent = ticket.source_label + " · " + (ticket.assignee_name || "尚未接入");
    badge.hidden = false;
    badge.textContent = ticket.status === "waiting" ? "待接入" : ticket.status === "active" ? "处理中" : "已结束";
    badge.className = "badge " + (ticket.status === "closed" ? "ok" : ticket.status === "active" ? "info" : "");
    const mine = Number(ticket.assignee_id) === Number(me.user_id);
    document.getElementById("btnClose").hidden = ticket.status === "closed" || !mine;
    replyForm.hidden = ticket.status !== "active" || !mine;
    thread.innerHTML = detail.messages.map((msg) => {
      if (msg.role === "system") return `<p class="sys-line">${escapeHtml(msg.body)}</p>`;
      const klass = msg.role === "user" ? "visitor" : msg.role === "agent" ? "agent" : "bot";
      const who = msg.role === "user" ? "访客" : msg.role === "agent" ? (msg.author || "坐席") : "机器人";
      const pick = msg.role === "bot" ? `<div class="msg-tools"><button type="button" class="btn btn-quiet btn-sm" data-pick="${msg.id}">标记这条</button></div>` : "";
      return `<div class="msg ${klass}"><div class="meta">${escapeHtml(who)} · ${fmt(msg.created_at)}</div><div class="bubble">${escapeHtml(msg.body)}</div>${pick}</div>`;
    }).join("") || '<p class="empty">还没有消息。</p>';
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

  thread.addEventListener("click", (event) => {
    const button = event.target.closest("[data-pick]");
    if (!button || !current) return;
    selectedMessage = Number(button.dataset.pick);
    badMessage.value = String(selectedMessage);
    const message = current.messages.find((item) => item.id === selectedMessage);
    badTarget.textContent = "针对：" + ((message && message.body) || "").slice(0, 80);
    selectTab(document.getElementById("tab-bad"));
  });

  document.getElementById("writeForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!current) return;
    const form = event.target;
    writeStatus.hidden = false;
    writeStatus.className = "form-status pending";
    writeStatus.textContent = "正在提交…";
    try {
      const data = await api("/api/agent/tickets/" + current.ticket.public_id + "/writeback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: form.question.value, answer: form.answer.value }),
      });
      const row = data.writeback || {};
      writeStatus.className = "form-status" + (row.status === "completed" ? "" : " pending");
      writeStatus.textContent = row.status === "completed" ? "索引完成。再问同样的问题，机器人应能引用这一条。" : "索引中。可以稍后在知识库文档里看状态。";
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
    const probe = await fetch("/api/portal/state?session=staff-probe").then((r) => r.json()).catch(() => ({}));
    const pill = document.getElementById("kbPill");
    if (probe.maintenance) {
      pill.textContent = "知识库维护中";
      pill.className = "pill bad";
    } else if (probe.probe_ok) {
      pill.textContent = "知识库就绪";
      pill.className = "pill ok";
    }
    await refreshQueue();
    setInterval(() => refreshQueue().catch(() => {}), 5000);
  }

  boot().catch((err) => {
    queueEl.innerHTML = `<p class="empty">${escapeHtml(err.message)}</p>`;
  });
})();
