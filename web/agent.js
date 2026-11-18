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
  const btnTake = document.getElementById("btnTake");
  const btnClose = document.getElementById("btnClose");
  const queueStatus = document.getElementById("queueStatus");
  const writeForm = document.getElementById("writeForm");
  const badForm = document.getElementById("badForm");
  let me = null;
  let status = "waiting";
  let current = null;
  let queueRequest = 0;
  let queueMarkup = "";
  let detailRequest = 0;
  let opening = false;
  let actionPending = false;
  let polling = false;

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

  function markSelectedTicket() {
    for (const button of queueEl.querySelectorAll(".ticket")) {
      if (button.dataset.id === current?.ticket.public_id) button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
    }
  }

  async function refreshQueue() {
    const requested = ++queueRequest;
    try {
      const data = await api("/api/agent/tickets?status=" + status);
      if (requested !== queueRequest) return;
      queueStatus.textContent = "每 5 秒刷新";
      document.getElementById("tab-waiting").textContent = "待接入 " + (data.counts.waiting || 0);
      document.getElementById("tab-active").textContent = "处理中 " + (data.counts.active || 0);
      document.getElementById("tab-closed").textContent = "已结束 " + (data.counts.closed || 0);
      const markup = data.tickets.map((ticket) => {
        const id = escapeHtml(ticket.public_id);
        const closed = ticket.status === "closed";
        const cls = closed ? "ok" : (sourceClass[ticket.source] || "");
        const label = closed ? "已结束" : ticket.source_label;
        return `<button type="button" class="ticket" data-id="${id}">
          <span class="row"><span>${id}</span><span class="badge ${cls}">${escapeHtml(label)}</span></span>
          <span class="q">${escapeHtml(ticket.first_question)}</span>
          <span class="row"><span>${escapeHtml(waitLabel(ticket))}</span><span>访客 ${escapeHtml(ticket.visitor)}</span></span>
        </button>`;
      }).join("") || emptyDesk("这一栏还没有工单。");
      if (markup === queueMarkup) return;
      const focusedId = queueEl.contains(document.activeElement) ? document.activeElement.dataset.id : "";
      queueEl.innerHTML = queueMarkup = markup;
      markSelectedTicket();
      if (focusedId) {
        const previous = [...queueEl.querySelectorAll(".ticket")].find((button) => button.dataset.id === focusedId);
        (previous || document.getElementById("tab-" + status)).focus({ preventScroll: true });
      }
    } catch {
      if (requested === queueRequest) queueStatus.textContent = "刷新失败，稍后重试";
    }
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
    const groups = groupStaffCites(meta && meta.citations).filter((group) => group.segments.length > 0);
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

  function syncActions() {
    const ticket = current?.ticket;
    const mine = ticket?.assignee_id === me?.user_id;
    const canReply = ticket?.status === "active" && mine;
    btnTake.hidden = ticket?.status !== "waiting";
    btnClose.hidden = !canReply;
    replyForm.hidden = !canReply;
    for (const button of [btnTake, btnClose, replyForm.querySelector('button[type="submit"]')]) {
      button.disabled = opening || actionPending;
    }
  }

  function renderThread(detail) {
    const ticket = detail.ticket;
    const changedTicket = ticket.public_id !== current?.ticket.public_id;
    const atBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 60;
    if (changedTicket) {
      replyForm.reset();
      writeForm.reset();
      badForm.reset();
      badMessage.value = "";
      badTarget.textContent = "先从对话里选择一条助手回答。";
      writeStatus.hidden = badStatus.hidden = replyStatus.hidden = true;
      writeForm.elements.question.value = ticket.first_question.slice(0, 120);
      selectTab(document.getElementById("tab-trace"));
    }
    current = { ...current, ...detail };
    title.textContent = ticket.public_id + " · " + ticket.first_question;
    const created = fmt(ticket.created_at);
    sub.textContent = "访客 " + (ticket.visitor || "") + " · " + ticket.source_label + (created ? " · " + created + " 创建" : "");
    badge.hidden = false;
    const mine = ticket.assignee_id === me?.user_id;
    badge.textContent = ticket.status === "waiting" ? "待接入" : ticket.status === "active" ? (mine ? "处理中 · 你已接入" : "处理中") : "已结束";
    badge.className = "badge " + (ticket.status === "closed" ? "ok" : ticket.status === "active" ? "info" : "warn");
    syncActions();
    markSelectedTicket();
    if (!detail.messages) return;
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
    if (changedTicket || atBottom) thread.scrollTop = thread.scrollHeight;
  }

  function showReplyStatus(text) {
    replyStatus.hidden = !text;
    replyStatus.textContent = text;
  }

  function ticketPath(id = current.ticket.public_id) {
    return "/api/agent/tickets/" + encodeURIComponent(id);
  }

  async function openTicket(publicId) {
    if (actionPending) return;
    const requested = ++detailRequest;
    opening = true;
    syncActions();
    showReplyStatus("正在加载工单…");
    try {
      const detail = await api(ticketPath(publicId));
      if (requested !== detailRequest) return;
      renderThread(detail);
      showReplyStatus("");
      if (matchMedia("(max-width: 660px)").matches) title.focus();
    } catch (err) {
      if (requested === detailRequest) showReplyStatus(err.message);
    } finally {
      if (requested === detailRequest) {
        opening = false;
        syncActions();
      }
    }
  }

  async function submitAction(action, body) {
    if (!current || opening || actionPending) return null;
    actionPending = true;
    detailRequest++;
    syncActions();
    try {
      const detail = await api(ticketPath() + "/" + action, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      renderThread(detail);
      if (action !== "reply") showQueue(detail.ticket.status);
      return detail;
    } finally {
      actionPending = false;
      syncActions();
    }
  }

  queueEl.addEventListener("click", (event) => {
    const button = event.target.closest(".ticket");
    if (button) openTicket(button.dataset.id);
  });

  btnTake.addEventListener("click", async () => {
    showReplyStatus("");
    try {
      if (await submitAction("take", {})) replyBox.focus();
    } catch (err) {
      showReplyStatus(err.message);
    }
  });

  function showQueue(nextStatus) {
    const tab = document.getElementById("tab-" + nextStatus);
    selectTab(tab);
    if (status !== nextStatus) {
      status = nextStatus;
      queueEl.setAttribute("aria-labelledby", tab.id);
      queueEl.innerHTML = queueMarkup = emptyDesk("正在加载工单…");
    }
    refreshQueue();
  }

  for (const tab of document.querySelectorAll(".queue [role=tab]")) {
    tab.addEventListener("click", () => showQueue(tab.dataset.status));
  }
  for (const tab of document.querySelectorAll(".ctx [role=tab]")) {
    tab.addEventListener("click", () => selectTab(tab));
  }

  replyBox.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
      event.preventDefault();
      replyForm.requestSubmit();
    }
  });
  replyForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!current || opening || actionPending || replyForm.hidden) return;
    showReplyStatus("");
    const text = replyBox.value.trim();
    if (!text) {
      showReplyStatus("回复内容不能为空");
      return;
    }
    try {
      if (await submitAction("reply", { text }) && replyBox.value.trim() === text) replyBox.value = "";
      thread.scrollTop = thread.scrollHeight;
    } catch (err) {
      showReplyStatus(err.message);
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
    const selectedMessage = Number(button.dataset.pick);
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

  btnClose.addEventListener("click", () => {
    closeError.hidden = true;
    closeDialog.showModal();
  });
  document.getElementById("closeCancel").addEventListener("click", () => closeDialog.close());
  document.getElementById("closeDismiss").addEventListener("click", () => closeDialog.close());
  document.getElementById("closeForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (opening || actionPending) return;
    const form = event.currentTarget;
    const note = form.elements.note.value.trim();
    if (!note) {
      closeError.hidden = false;
      closeError.textContent = "请写一句处理说明";
      return;
    }
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    closeError.hidden = true;
    try {
      if (await submitAction("close", { note })) {
        closeDialog.close();
        form.reset();
        title.focus({ preventScroll: true });
      }
    } catch (err) {
      closeError.hidden = false;
      closeError.textContent = err.message;
    } finally {
      submit.disabled = false;
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
    async function refreshOpenTicket() {
      if (!current || opening || actionPending || current.ticket.status === "closed" || thread.contains(document.activeElement)) return;
      const requested = ++detailRequest;
      const params = new URLSearchParams({
        after: current.messages.at(-1)?.id || 0,
        trace_after: current.judgments.at(-1)?.id || 0,
      });
      const detail = await api(`${ticketPath()}?${params}`);
      if (requested === detailRequest) renderThread(detail);
    }

    async function refreshDesk() {
      if (document.hidden || polling) return;
      polling = true;
      try {
        await Promise.allSettled([refreshQueue(), refreshPill(), refreshOpenTicket()]);
      } finally {
        polling = false;
      }
    }
    await refreshDesk();
    setInterval(refreshDesk, 5000);
    document.addEventListener("visibilitychange", refreshDesk);
  }

  boot().catch((err) => {
    queueEl.innerHTML = emptyDesk(escapeHtml(err.message));
  });
})();
