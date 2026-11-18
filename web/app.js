(() => {
  "use strict";

  const LS_KEY = "nebula-cs-sessions-v1";
  const LS_ACTIVE = "nebula-cs-active-session";

  const el = {
    messages: document.getElementById("messages"),
    citeList: document.getElementById("citeList"),
    sourcePanel: document.getElementById("sourcePanel"),
    sourceQuestion: document.getElementById("sourceQuestion"),
    sourceCount: document.getElementById("sourceCount"),
    emptyTemplate: document.getElementById("emptyTemplate"),
    ticketProgress: document.getElementById("ticketProgress"),
    sessionList: document.getElementById("sessionList"),
    composer: document.getElementById("composer"),
    input: document.getElementById("queryInput"),
    btnSend: document.getElementById("btnSend"),
    btnStop: document.getElementById("btnStop"),
    btnNewChat: document.getElementById("btnNewChat"),
    statusText: document.getElementById("statusText"),
    ticketModal: document.getElementById("ticketModal"),
    ticketForm: document.getElementById("ticketForm"),
    ticketResult: document.getElementById("ticketResult"),
    btnNav: document.getElementById("btnNav"),
    btnExport: document.getElementById("btnExport"),
    navModal: document.getElementById("navModal"),
    navSearch: document.getElementById("navSearch"),
    navCats: document.getElementById("navCats"),
    navList: document.getElementById("navList"),
    btnCloseNav: document.getElementById("btnCloseNav"),
    btnTicketTop: document.getElementById("btnTicketTop"),
    btnCloseTicket: document.getElementById("btnCloseTicket"),
    btnCancelTicket: document.getElementById("btnCancelTicket"),
    btnMyTickets: document.getElementById("btnMyTickets"),
    myTicketsModal: document.getElementById("myTicketsModal"),
    myTicketsHint: document.getElementById("myTicketsHint"),
    myTicketsStatus: document.getElementById("myTicketsStatus"),
    myTicketsContent: document.getElementById("myTicketsContent"),
    btnRefreshMyTickets: document.getElementById("btnRefreshMyTickets"),
    btnCloseMyTickets: document.getElementById("btnCloseMyTickets"),
    btnBackMyTickets: document.getElementById("btnBackMyTickets"),
    btnMoreMyTickets: document.getElementById("btnMoreMyTickets"),
    noticeBar: document.getElementById("noticeBar"),
    onlinePill: document.getElementById("onlinePill"),
  };

  const state = {
    conversationId: "",
    userId: loadUserId(),
    busy: false,
    abort: null,
    taskId: "",
    sessionId: "",
    messages: [], // {role, text, refuse?, suggestions?}
    historyCutoff: 0,
    ticketId: "",
    agentName: "",
    maintenance: false,
    ticketStatus: "",
    pollRequest: null,
    portalCursor: 0,
    ticketSubmitting: false,
  };
  const myTickets = { id: "", before: null, request: null };

  function loadUserId() {
    try {
      const k = "nebula-cs-user";
      let u = localStorage.getItem(k);
      if (!u) {
        u = "nebula-" + Math.random().toString(36).slice(2, 10);
        localStorage.setItem(k, u);
      }
      return u;
    } catch {
      return "nebula-" + Math.random().toString(36).slice(2, 10);
    }
  }

  function clockNow() {
    const date = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return pad(date.getHours()) + ":" + pad(date.getMinutes());
  }

  function clockOf(iso) {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    const pad = (n) => String(n).padStart(2, "0");
    return pad(date.getHours()) + ":" + pad(date.getMinutes());
  }

  function queuedLine(ticketId) {
    return clockNow() + " 你点了「转人工」，工单 " + ticketId + " 已登记，排队中…";
  }

  function clarifyLabel(label) {
    const text = String(label || "").replace(/(如何|怎么)[^？?]{0,12}[？?]?$/, "").trim();
    return text || label;
  }

  function clearThread() {
    el.messages.replaceChildren();
  }

  function setStatus(text) {
    if (!el.statusText) return;
    el.statusText.textContent = text;
    el.statusText.classList.remove("warn");
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatAnswer(text) {
    let s = escapeHtml(text);
    s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    const lines = s.split("\n");
    const out = [];
    let inList = false;
    for (const line of lines) {
      const m = line.match(/^\s*[-*•]\s+(.+)/);
      if (m) {
        if (!inList) {
          out.push("<ul>");
          inList = true;
        }
        out.push("<li>" + m[1] + "</li>");
      } else {
        if (inList) {
          out.push("</ul>");
          inList = false;
        }
        out.push(line || "<br>");
      }
    }
    if (inList) out.push("</ul>");
    return out.join("\n");
  }

  const rowAnswers = new WeakMap();

  function linkCitationMarks(html, citations) {
    if (!citations?.length) return html;
    return html.replace(/\[(\d+)\]/g, (original, raw) => {
      const mark = Number(raw);
      if (!citations.some((card) => card.mark === mark)) return original;
      return `<button type="button" class="cite-mark" data-cite="${mark}" aria-label="查看出处 ${mark}">[${mark}]</button>`;
    });
  }

  function citationSnapshot(citations) {
    if (!Array.isArray(citations)) return [];
    const piece = (item) => ({
      title: String(item.title || "").slice(0, 160),
      content: String(item.content || "").slice(0, 800),
      score: typeof item.score === "number" ? item.score : -1,
    });
    return citations.slice(0, 8).flatMap((item, index) => {
      if (!item || typeof item !== "object") return [];
      return [{
        ...piece(item),
        mark: Number(item.mark) || index + 1,
        document_id: String(item.document_id || "").slice(0, 160),
        document_name: String(item.document_name || "文档").slice(0, 160),
        segments: Array.isArray(item.segments) ? item.segments.filter(Boolean).slice(0, 3).map(piece) : [],
      }];
    });
  }

  function attachSources(row, answer) {
    if (!answer?.citations?.length) return;
    rowAnswers.set(row, answer);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "mini";
    button.dataset.cite = "";
    button.textContent = "查看依据";
    const bar = row.querySelector(".bot-tools");
    if (bar) bar.prepend(button);
    else row.appendChild(button);
  }

  const PHASE_TEXT = { retrieving: "正在查找依据", generating: "正在作答" };

  function showPhase(phase) {
    const label = PHASE_TEXT[phase];
    if (!label) return;
    setStatus(label);
    const body = document.querySelector("#streamRow .stream-body");
    if (body && !body.dataset.answer) body.textContent = label;
  }

  function maskPhone(text) {
    return globalThis.nebulaMask.maskPhone(text);
  }

  function loadSessions() {
    try {
      const raw = localStorage.getItem(LS_KEY);
      const list = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(list)) return [];
      const cleaned = list.map((item) => globalThis.nebulaMask.maskStoredSession(item));
      const changed = cleaned.some((item, index) => {
        const before = list[index] || {};
        return item.title !== before.title || JSON.stringify(item.messages) !== JSON.stringify(before.messages);
      });
      if (changed) saveSessions(cleaned);
      return cleaned;
    } catch {
      return [];
    }
  }

  function saveSessions(list) {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(list.slice(0, 20)));
    } catch {
      /* ignore quota */
    }
  }

  function fmtTime(ts) {
    try {
      const d = new Date(ts);
      const pad = (n) => String(n).padStart(2, "0");
      return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    } catch {
      return "";
    }
  }

  function persistCurrentSession() {
    if (!state.sessionId) return;
    const list = loadSessions();
    const idx = list.findIndex((s) => s.id === state.sessionId);
    state.messages = state.messages.map((message) => {
      if (!message || message.role !== "user") return message;
      return Object.assign({}, message, { text: maskPhone(message.text) });
    });
    const entry = globalThis.nebulaMask.maskStoredSession({
      id: state.sessionId,
      conversationId: state.conversationId || "",
      updatedAt: Date.now(),
      historyCutoff: Math.max(0, state.historyCutoff - Math.max(0, state.messages.length - 40)),
      portalCursor: state.portalCursor,
      messages: state.messages.slice(-40).map((message, index, rows) => {
        if (!message.citations || index >= rows.length - 12) return message;
        const { citations, ...rest } = message;
        return rest;
      }),
    });
    if (idx >= 0) list[idx] = entry;
    else list.unshift(entry);
    list.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
    saveSessions(list);
    try {
      localStorage.setItem(LS_ACTIVE, state.sessionId);
    } catch {
      /* ignore */
    }
    renderSessionList();
  }

  function renderSessionList() {
    const list = loadSessions();
    if (!list.length) {
      el.sessionList.innerHTML = `<div class="session-empty">本机暂无历史。发送问题后会出现在这里。</div>`;
      return;
    }
    el.sessionList.innerHTML = list
      .map((s) => {
        const active = s.id === state.sessionId ? " active" : "";
        return `<button type="button" class="session-item${active}" data-sid="${escapeHtml(s.id)}">
          <div class="t">${escapeHtml(globalThis.nebulaMask.sessionTitle(s.title || "未命名"))}</div>
          <div class="d">${escapeHtml(fmtTime(s.updatedAt))} · ${s.messages ? s.messages.length : 0} 条</div>
        </button>`;
      })
      .join("");
    el.sessionList.querySelectorAll(".session-item").forEach((btn) => {
      btn.addEventListener("click", () => restoreSession(btn.getAttribute("data-sid")));
    });
  }

  function restoreSession(sid) {
    if (state.busy || state.ticketSubmitting) return false;
    const list = loadSessions();
    const s = list.find((x) => x.id === sid);
    if (!s) return false;
    resetTicket();
    hydrateSession(s);
    try {
      localStorage.setItem(LS_ACTIVE, sid);
    } catch {
      /* ignore */
    }
    renderMessagesFromState();
    restoreSources();
    renderSessionList();
    setStatus("已切换会话 · 可继续追问");
    pollPortal();
    return true;
  }

  function hydrateSession(session) {
    state.sessionId = session.id;
    state.conversationId = session.conversationId || "";
    state.historyCutoff = session.historyCutoff || 0;
    state.messages = session.messages.slice();
    state.portalCursor = state.messages.reduce((cursor, row) => Math.max(cursor, Number(row.serverId) || 0), Number(session.portalCursor) || 0);
  }

  function renderMessagesFromState() {
    clearThread();
    if (!state.messages.length) {
      renderEmpty();
      return;
    }
    state.messages.forEach((m) => {
      if (m.role === "system") {
        appendSystem(m.text);
        return;
      }
      if (m.role === "user") {
        appendMessage("user", escapeHtml(m.text), { persist: false });
      } else {
        const row = appendMessage("bot", formatAnswer(m.text), {
          refuse: !!m.refuse,
          handoff: !!m.handoff,
          suggestions: m.suggestions || [],
          clarify: m.action === "clarify",
          agent: m.role === "agent",
          who: m.role === "agent" ? agentLabel(m) : "",
          answer: m,
        });
        if (m.handoff && !m.refuse) mountHandoffAction(row, m.ticketId);
      }
    });
  }

  function newSessionId() {
    return "s-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 7);
  }

  function startNewChat() {
    if (state.busy || state.ticketSubmitting) return;
    resetTicket();
    state.conversationId = "";
    state.taskId = "";
    state.historyCutoff = 0;
    state.messages = [];
    state.sessionId = newSessionId();
    try { localStorage.removeItem(LS_ACTIVE); } catch { /* optional storage */ }
    renderEmpty();
    renderSessionList();
    setStatus("新对话已开始");
    el.input.focus();
  }

  function renderEmpty() {
    el.messages.replaceChildren(el.emptyTemplate.content.cloneNode(true));
    document.body.classList.remove("in-conversation");
    renderCitations([]);
  }

  function enterThread() {
    el.messages.querySelector(".empty-state")?.remove();
    document.body.classList.add("in-conversation");
  }

  function appendMessage(role, html, opts = {}) {
    enterThread();

    const wrap = document.createElement("div");
    const handoffClass = opts.handoff && !opts.refuse ? " handoff" : "";
    wrap.className = "msg " + (opts.agent ? "agent-msg" : role) + (opts.refuse ? " refuse" : "") + handoffClass;
    const who = opts.who || (role === "user" ? "你" : "校园助手");
    wrap.innerHTML = `<div class="who">${escapeHtml(who)}</div><div class="bubble">${linkCitationMarks(html, opts.answer?.citations)}</div>`;
    if (opts.refuse) {
      const actions = document.createElement("div");
      actions.className = "msg-actions";
      actions.innerHTML = `<button type="button" class="solid" data-action="ticket">转人工坐席</button>`;
      actions.querySelector("button").addEventListener("click", openTicket);
      wrap.appendChild(actions);
    }
    mountSuggestions(wrap, opts.suggestions, opts.clarify);
    if (role === "bot" && !opts.agent && !opts.clarify) mountBotTools(wrap, opts.answer?.serverMessageId);
    attachSources(wrap, opts.answer);
    el.messages.appendChild(wrap);
    el.messages.scrollTop = el.messages.scrollHeight;
    return wrap;
  }

  function appendSystem(text) {
    enterThread();
    const line = document.createElement("p");
    line.className = "sys-line";
    line.textContent = text;
    el.messages.appendChild(line);
    el.messages.scrollTop = el.messages.scrollHeight;
  }

  function setPill(text, kind) {
    if (!el.onlinePill) return;
    if (el.onlinePill.textContent !== text) el.onlinePill.textContent = text;
    el.onlinePill.classList.toggle("warn", kind === "warn");
    el.onlinePill.classList.toggle("live", kind === "live");
  }

  function showMaintenance(on) {
    const next = !!on;
    state.maintenance = next;
    if (!el.onlinePill) return;
    if (!on) {
      el.noticeBar.hidden = true;
      return;
    }
    if (el.noticeBar.hidden) {
      el.noticeBar.innerHTML = "<strong>知识库维护中</strong>校园办事问题将交给人工坐席处理。";
      el.noticeBar.hidden = false;
    }
    setPill("知识库维护中", "warn");
  }

  const TICKET_LABELS = {
    waiting: "等待坐席接入",
    active: "坐席处理中",
    closed: "已结束",
  };

  function resetTicket() {
    state.pollRequest?.abort();
    state.pollRequest = null;
    state.portalCursor = 0;
    setTicketProgress(null);
  }

  function setTicketProgress(ticket) {
    const id = ticket?.public_id || "";
    const status = ticket?.status || "";
    const name = ticket?.assignee_name || "";
    const changed = state.ticketId !== id || state.ticketStatus !== status || state.agentName !== name;
    state.ticketId = id;
    state.ticketStatus = status;
    state.agentName = name;
    el.ticketProgress.hidden = !id;
    if (changed && id) {
      el.ticketProgress.dataset.status = status;
      const label = TICKET_LABELS[status] || "状态待确认";
      const next = status === "closed" ? " · 可继续向助手提问" : "";
      el.ticketProgress.innerHTML = `<strong>工单 ${escapeHtml(id)}</strong><span>${label}${next}${name ? " · " + escapeHtml(name) : ""}</span>`;
    }
    if (!state.maintenance) {
      if (status === "waiting") setPill("等待人工", "live");
      else if (status === "active") setPill("人工已接入", "live");
      else setPill("助手在线", "");
    }
  }

  function noteTicket(ticket) {
    if (!ticket?.public_id) return;
    const isNew = state.ticketId !== ticket.public_id;
    setTicketProgress(ticket);
    if (isNew && ticket.status === "waiting") {
      const line = queuedLine(ticket.public_id);
      appendSystem(line);
      state.messages.push({ role: "system", text: line });
    }
  }

  function agentLabel(message) {
    return [...new Set([message.author, "人工客服", message.createdAt].filter(Boolean))].join(" · ");
  }

  function beginBotStream() {
    enterThread();
    const wrap = document.createElement("div");
    wrap.className = "msg bot";
    wrap.id = "streamRow";
    wrap.innerHTML = `<div class="who">校园助手</div><div class="bubble"><span class="stream-body"></span><span class="stream-cursor" aria-hidden="true"></span></div>`;
    el.messages.appendChild(wrap);
    el.messages.scrollTop = el.messages.scrollHeight;
    return wrap;
  }

  function updateBotStream(text) {
    const row = document.getElementById("streamRow");
    if (!row) return;
    const body = row.querySelector(".stream-body");
    if (body) {
      body.dataset.answer = "1";
      body.innerHTML = formatAnswer(text);
    }
    el.messages.scrollTop = el.messages.scrollHeight;
  }

  function finishBotStream(text, opts) {
    if (typeof opts === "boolean") opts = { refuse: opts };
    opts = opts || {};
    const row = document.getElementById("streamRow");
    if (!row) {
      return appendMessage("bot", formatAnswer(text), opts);
    }
    row.id = "";
    if (opts.agent) row.classList.add("agent-msg");
    if (opts.who) {
      const who = row.querySelector(".who");
      if (who) who.textContent = opts.who;
    }
    if (opts.refuse) row.classList.add("refuse");
    if (opts.handoff && !opts.refuse) row.classList.add("handoff");
    const bubble = row.querySelector(".bubble");
    if (bubble) bubble.innerHTML = linkCitationMarks(formatAnswer(text), opts.answer?.citations);
    const cursor = row.querySelector(".stream-cursor");
    if (cursor) cursor.remove();
    if (opts.refuse && !row.querySelector(".msg-actions")) {
      const actions = document.createElement("div");
      actions.className = "msg-actions";
      actions.innerHTML = `<button type="button" class="solid" data-action="ticket">转人工坐席</button>`;
      actions.querySelector("button").addEventListener("click", openTicket);
      row.appendChild(actions);
    }
    mountSuggestions(row, opts.suggestions, opts.clarify);
    if (!opts.clarify && !opts.agent) mountBotTools(row, opts.answer?.serverMessageId);
    attachSources(row, opts.answer);
    el.messages.scrollTop = el.messages.scrollHeight;
    return row;
  }

  function mountHandoffAction(row, ticketId) {
    if (!row || row.querySelector(".msg-actions")) return;
    const actions = document.createElement("div");
    actions.className = "msg-actions";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "solid";
    button.textContent = "补充工单信息";
    button.addEventListener("click", () => {
      openTicket();
      const subj = el.ticketForm.querySelector("input[name=subject]");
      if (subj && !subj.value) subj.value = maskPhone(ticketId ? "跟进工单 " + ticketId : "转人工跟进");
    });
    actions.appendChild(button);
    row.appendChild(actions);
  }

  function mountBotTools(row, messageId) {
    if (!row || row.querySelector(".bot-tools")) return;
    const bar = document.createElement("div");
    bar.className = "bot-tools";
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "mini";
    copy.textContent = "复制";
    copy.addEventListener("click", () => copyAnswer(row, copy));
    bar.appendChild(copy);
    if (messageId) {
      row.dataset.messageId = String(messageId);
      for (const [label, helpful] of [["有帮助", true], ["没解决", false]]) {
        const rating = document.createElement("button");
        rating.type = "button";
        rating.className = "mini";
        rating.textContent = label;
        rating.addEventListener("click", () => recordFeedback(row, helpful));
        bar.appendChild(rating);
      }
    }
    row.appendChild(bar);
  }

  function copyAnswer(row, button) {
    const bubble = row.querySelector(".bubble");
    const text = bubble ? bubble.innerText.trim() : "";
    if (!text) return;
    const done = () => {
      button.textContent = "已复制";
      setStatus("已复制到剪贴板，只在本机");
      window.setTimeout(() => {
        button.textContent = "复制";
      }, 1600);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
    } else {
      fallbackCopy(text, done);
    }
  }

  function fallbackCopy(text, done) {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.select();
    try {
      document.execCommand("copy");
      done();
    } catch {
      setStatus("复制失败，可以改用导出记录");
    }
    area.remove();
  }

  function lastUserText() {
    for (let i = state.messages.length - 1; i >= 0; i -= 1) {
      if (state.messages[i].role === "user") return String(state.messages[i].text || "").slice(0, 80);
    }
    return "";
  }

  async function recordFeedback(row, helpful) {
    const note = row.querySelector(".feedback-note");
    if (note) note.remove();
    const line = document.createElement("p");
    line.className = "feedback-note";
    const messageId = Number(row.dataset.messageId || 0);
    if (!messageId) {
      line.textContent = "这条回答还没有编号，评价没有送出。";
      row.appendChild(line);
      return;
    }
    line.textContent = "正在记下…";
    row.appendChild(line);
    try {
      const res = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message_id: messageId,
          helpful: !!helpful,
          comment: "",
          portal_session: state.sessionId || "",
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        line.textContent = data.error || "评价没有送出。";
        return;
      }
    } catch {
      line.textContent = "评价没有送出，请稍后再试。";
      return;
    }
    if (helpful) {
      line.textContent = "已交给工作人员。";
      setStatus("已交给工作人员：有帮助");
    } else {
      line.textContent = "已记下。可以换一种问法，或转人工。";
      setStatus("已记下：没解决 · 可转人工");
      if (!row.querySelector('[data-action="ticket"]')) {
        const actions = document.createElement("div");
        actions.className = "msg-actions";
        const button = document.createElement("button");
        button.type = "button";
        button.className = "solid";
        button.dataset.action = "ticket";
        button.textContent = "转人工坐席";
        button.addEventListener("click", openTicket);
        actions.appendChild(button);
        row.appendChild(actions);
      }
    }
  }

  function exportConversation() {
    const lines = [
      "校园客服对话",
      "本机导出，未提交给工作人员。",
      "星云大学是虚构样例，不是真实学校。",
      "",
    ];
    if (!state.messages.length) {
      setStatus("当前没有对话可导出");
      return;
    }
    state.messages.forEach((message) => {
      lines.push((message.role === "user" ? "同学" : "校园助手") + "：");
      lines.push(String(message.text || ""));
      lines.push("");
    });
    const blob = new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "校园客服-对话.txt";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
    setStatus("已下载到本机，没有上传");
  }

  const navState = { categories: [], active: "全部" };

  function openNav() {
    if (!el.navModal) return;
    if (!el.navModal.open) el.navModal.showModal();
    if (el.navSearch) {
      el.navSearch.value = "";
      el.navSearch.focus();
    }
    if (!navState.categories.length) {
      if (el.navList) el.navList.textContent = "正在读取知识库标题…";
      fetch("/api/faq-nav")
        .then((res) => res.json())
        .then((data) => {
          navState.categories = Array.isArray(data.categories) ? data.categories : [];
          navState.active = "全部";
          renderNav();
        })
        .catch(() => {
          if (el.navList) el.navList.textContent = "办事导航暂时读不到。可以直接在输入框提问。";
        });
      return;
    }
    renderNav();
  }

  function closeNav() {
    if (el.navModal?.open) el.navModal.close();
  }

  function renderNav() {
    if (!el.navCats || !el.navList) return;
    const names = ["全部"].concat(navState.categories.map((cat) => cat.name));
    el.navCats.innerHTML = "";
    names.forEach((name) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip" + (name === navState.active ? " active" : "");
      btn.textContent = name;
      btn.addEventListener("click", () => {
        navState.active = name;
        renderNav();
      });
      el.navCats.appendChild(btn);
    });
    const q = (el.navSearch && el.navSearch.value ? el.navSearch.value : "").trim().toLowerCase();
    const items = [];
    navState.categories.forEach((cat) => {
      if (navState.active !== "全部" && cat.name !== navState.active) return;
      (cat.items || []).forEach((item) => {
        const hay = (item.title || "") + (item.query || "");
        if (!q || hay.toLowerCase().indexOf(q) >= 0) items.push(item);
      });
    });
    el.navList.innerHTML = "";
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "nav-empty";
      empty.textContent = "没有对上的标题。换个词，或直接提问。";
      el.navList.appendChild(empty);
      return;
    }
    items.slice(0, 80).forEach((item) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "nav-item";
      btn.textContent = item.title || item.query || "";
      btn.addEventListener("click", () => {
        closeNav();
        sendQuery(item.query || item.title);
      });
      el.navList.appendChild(btn);
    });
  }

  function mountSuggestions(row, suggestions, clarify) {
    if (!row || !suggestions || !suggestions.length || row.querySelector(".suggest-chips, .clarify-opts")) return;
    const box = document.createElement("div");
    box.className = clarify ? "clarify-opts" : "suggest-chips";
    box.setAttribute("role", "group");
    box.setAttribute("aria-label", clarify ? "澄清选项" : "可选问题");
    const items = clarify ? suggestions.slice(0, 3) : suggestions;
    items.forEach((item) => {
      const raw = (item && (item.label || item.query)) || "";
      const q = (item && (item.query || item.label)) || "";
      if (!q) return;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip";
      btn.textContent = clarify ? clarifyLabel(raw) : raw;
      btn.addEventListener("click", () => sendQuery(q));
      box.appendChild(btn);
    });
    if (box.childElementCount) row.appendChild(box);
  }

  function scrubLocal(text) {
    const raw = String(text || "");
    const med = /(病历|病例|化验单|出院小结|出院记录|诊断证明|诊断书)/;
    if (med.test(raw) && (raw.length > 36 || /\n/.test(raw) || /\d{6,}/.test(raw))) {
      return "［病历内容已隐去，请勿在对话中发送］";
    }
    let next = raw.replace(/(?<!\d)\d{17}[\dXx](?!\d)/g, "［身份证号已隐去］");
    next = next.replace(/(?<!\d)\d{16,19}(?!\d)/g, "［卡号已隐去］");
    next = maskPhone(next);
    return next === raw ? null : next;
  }

  function groupCitations(citations) {
    const groups = [];
    const index = new Map();
    (citations || []).forEach((raw, order) => {
      if (!raw || typeof raw !== "object") return;
      const key = raw.document_id || raw.document_name || "doc-" + order;
      let group = index.get(key);
      if (!group) {
        group = {
          document_name: raw.document_name || "文档",
          marks: [],
          segments: [],
        };
        index.set(key, group);
        groups.push(group);
      }
      group.marks.push(raw.mark);
      [raw, ...raw.segments].forEach((piece) => {
        if (!piece.content) return;
        if (group.segments.some((item) => item.content === piece.content)) return;
        group.segments.push(piece);
      });
    });
    groups.forEach((group) => {
      group.segments.sort((a, b) => b.score - a.score);
    });
    groups.sort((a, b) => {
      const left = a.segments[0] ? a.segments[0].score : -1;
      const right = b.segments[0] ? b.segments[0].score : -1;
      return right - left;
    });
    return groups;
  }

  function renderCitations(citations, question = "", mark = null) {
    const groups = groupCitations(citations);
    el.sourcePanel.hidden = !groups.length;
    if (!groups.length) {
      el.citeList.replaceChildren();
      return 0;
    }
    el.sourceCount.hidden = false;
    el.sourceCount.textContent = `${groups.length} 份文档`;
    el.sourceQuestion.hidden = !question;
    el.sourceQuestion.textContent = question ? `对应提问 · ${question.slice(0, 80)}` : "";
    el.citeList.innerHTML = groups.map((group) => {
      const preview = (group.segments[0]?.content || "").replace(/\s+/g, " ");
      const marks = group.marks.join(" ");
      const parts = group.segments.map((segment) => `<div class="cite-segment">
        ${segment.title ? `<h3>${escapeHtml(segment.title)}</h3>` : ""}<p>${escapeHtml(segment.content)}</p>
      </div>`).join("");
      return `<details class="cite-card" data-marks="${escapeHtml(marks)}"${group.marks.includes(mark) ? " open" : ""}>
        <summary><strong>${escapeHtml(group.document_name)}</strong>${preview ? `<span class="cite-preview">${escapeHtml(preview.slice(0, 70))}${preview.length > 70 ? "…" : ""}</span>` : ""}</summary>
        <div class="cite-segments">${parts || '<p class="cite-empty">暂无可展示的原文片段。</p>'}</div>
      </details>`;
    }).join("");
    return groups.length;
  }

  function restoreSources() {
    const answer = [...state.messages].reverse().find((row) => row.role === "bot" || row.role === "agent");
    renderCitations(answer?.citations || [], answer?.question);
  }

  function autosize() {
    const ta = el.input;
    ta.style.height = "auto";
    ta.style.height = Math.min(140, ta.scrollHeight) + "px";
  }

  function setBusy(busy) {
    state.busy = busy;
    el.btnSend.disabled = busy || state.ticketSubmitting;
    el.btnNewChat.disabled = busy || state.ticketSubmitting;
    el.btnStop.hidden = !busy;
    if (!busy) {
      state.abort = null;
      state.taskId = "";
    }
  }

  async function stopGenerating() {
    const taskId = state.taskId;
    const abort = state.abort;
    setStatus("正在停止…");
    if (abort) {
      try {
        abort.abort();
      } catch {
        /* ignore */
      }
    }
    if (taskId) {
      try {
        await fetch("/api/chat/stop", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ task_id: taskId, user: state.userId }),
        });
      } catch {
        /* ignore — local abort already cancelled stream */
      }
    }
  }


  function historyPayload() {
    // 最近若干轮，供代理侧查询改写（短指代追问）。重新开始之后不再带上旧话题。
    const start = state.historyCutoff || 0;
    return state.messages.slice(start, -1).filter((m) => m.role === "bot" || m.role === "user").slice(-10).map((m) => ({
      role: m.role === "bot" ? "assistant" : "user",
      text: maskPhone(String(m.text || "")).slice(0, 500),
    }));
  }

  function noteRewrite(rewrite) {
    if (!rewrite || !rewrite.rewritten) return;
    setStatus(
      "已改写追问 · 「" +
        String(rewrite.original || "").slice(0, 16) +
        "」→「" +
        String(rewrite.rewritten || "").slice(0, 28) +
        "」"
    );
  }

  function completeAnswer(data, text, query) {
    if (data.conversation_id) state.conversationId = data.conversation_id;
    const answer = {
      role: "bot",
      text,
      refuse: !!data.refuse,
      handoff: !!data.handoff,
      action: data.agent_action || "",
      suggestions: data.suggestions || [],
      citations: citationSnapshot(data.citations),
      question: query,
      serverMessageId: data.server_message_id || 0,
      ticketId: data.ticket_id || "",
    };
    const row = finishBotStream(text, { ...answer, answer, clarify: answer.action === "clarify" });
    if (answer.handoff && !answer.refuse) mountHandoffAction(row, answer.ticketId);
    state.messages.push(answer);
    if (answer.action === "restart") {
      state.historyCutoff = state.messages.length;
      state.conversationId = "";
    }
    if (data.maintenance) showMaintenance(true);
    if (data.queue && answer.ticketId) {
      const sameTicket = state.ticketId === answer.ticketId;
      noteTicket({
        public_id: answer.ticketId,
        status: data.ticket_status || (sameTicket ? state.ticketStatus : "waiting"),
        assignee_name: sameTicket ? state.agentName : "",
      });
    }
    const count = renderCitations(answer.citations, query);
    if (data.maintenance) setStatus("知识库维护中 · 校园办事问题已转人工");
    else if (answer.action === "clarify") setStatus("请选择一个具体问题");
    else if (answer.handoff && answer.ticketId) setStatus(`${data.queue ? "人工服务" : "演示回执"} · 工单 ${answer.ticketId}`);
    else if (answer.action === "order_lookup") setStatus(data.order_found ? "已查询演示办事单" : "未找到办事单 · 可转人工");
    else if (answer.action === "restart") setStatus("已重新开始");
    else if (answer.action === "safety") setStatus("请勿发送证件号、银行卡号或病历");
    else if (data.intent === "needs_model") setStatus("开放问答暂不可用 · 仍可查询校园办事");
    else if (answer.refuse) setStatus("可以换个问法或转人工");
    else setStatus(count ? `答复完成 · 引用 ${count} 份文档` : "答复完成");
    persistCurrentSession();
  }

  async function sendQuery(raw) {
    const typed = (raw || el.input.value || "").trim();
    if (!typed || state.busy || state.ticketSubmitting) return;
    const scrubbed = scrubLocal(typed);
    const query = maskPhone(scrubbed || typed);

    if (!state.sessionId) state.sessionId = newSessionId();

    setBusy(true);
    el.input.value = "";
    autosize();

    appendMessage("user", escapeHtml(query), { persist: false });
    state.messages.push({ role: "user", text: query });
    persistCurrentSession();

    beginBotStream();
    setStatus("正在查找依据…");

    const controller = new AbortController();
    state.abort = controller;
    let acc = "";
    let finalPayload = null;

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          query,
          user: state.userId,
          conversation_id: state.conversationId || undefined,
          portal_session: state.sessionId,
          stream: true,
          history: historyPayload(),
        }),
        signal: controller.signal,
      });

      const ctype = (res.headers.get("content-type") || "").toLowerCase();

      // 非 SSE 回退：JSON blocking 或错误
      if (!ctype.includes("text/event-stream")) {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          const err = data.error || data.detail || "请求失败";
          throw new Error(String(err));
        }
        completeAnswer(data, data.answer || "（空响应）", query);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n");
        buffer = parts.pop() || "";
        for (const line of parts) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data:")) continue;
          const rawJson = trimmed.slice(5).trim();
          if (!rawJson || rawJson === "[DONE]") continue;
          let ev;
          try {
            ev = JSON.parse(rawJson);
          } catch {
            continue;
          }
          if (ev.type === "start") {
            if (ev.conversation_id) state.conversationId = ev.conversation_id;
            if (ev.task_id) state.taskId = ev.task_id;
            if (ev.rewrite) noteRewrite(ev.rewrite);
            if (ev.agent_action === "human_handoff") setStatus("正在登记人工…");
            if (ev.agent_action === "order_lookup") setStatus("正在查询办事进度…");
          } else if (ev.type === "status") {
            showPhase(ev.phase);
          } else if (ev.type === "delta") {
            acc += ev.text || "";
            updateBotStream(acc);
          } else if (ev.type === "done") {
            finalPayload = ev;
            if (ev.conversation_id) state.conversationId = ev.conversation_id;
          } else if (ev.type === "error") {
            throw new Error(ev.error || "引擎错误");
          }
        }
      }

      if (!finalPayload) throw new Error("答复连接提前结束，请重试");
      completeAnswer(finalPayload, finalPayload.answer || acc || "（空响应）", query);
    } catch (err) {
      const stopped = err?.name === "AbortError";
      const text = stopped
        ? [acc.trim(), "已停止生成"].filter(Boolean).join("\n\n")
        : "答复失败 · " + (err?.message || "请稍后重试");
      finishBotStream(text, { refuse: !stopped });
      state.messages.push({ role: "bot", text, refuse: !stopped });
      setStatus(stopped ? "已停止生成" : "可重试或联系人工");
      persistCurrentSession();
    } finally {
      setBusy(false);
      pollPortal();
      if (el.input === document.activeElement || document.activeElement === document.body) el.input.focus();
    }
  }

  function openTicket() {
    if (state.ticketSubmitting) return;
    el.ticketResult.hidden = true;
    el.ticketResult.textContent = "";
    el.ticketForm.reset();
    el.ticketForm.querySelector('[type="submit"]').hidden = false;
    el.btnCancelTicket.textContent = "取消";
    el.ticketResult.classList.remove("error");
    if (!el.ticketModal.open) el.ticketModal.showModal();
    const first = el.ticketForm.querySelector("input[name=subject]");
    const lastUser = [...state.messages].reverse().find((m) => m.role === "user");
    if (first && lastUser && !first.value) {
      first.value = globalThis.nebulaMask.handoffSubject(lastUser.text || "");
    }
    if (first) first.focus();
  }

  function closeTicket() {
    if (!state.ticketSubmitting && el.ticketModal.open) el.ticketModal.close();
  }

  function ticketBadge(status) {
    return `<span class="badge my-ticket-badge" data-status="${escapeHtml(status)}">${TICKET_LABELS[status] || "状态待确认"}</span>`;
  }

  function showMyTicketsStatus(text, error = false) {
    el.myTicketsStatus.textContent = text;
    el.myTicketsStatus.classList.toggle("error", error);
    el.myTicketsStatus.hidden = !text;
  }

  function renderMyTickets(tickets, append) {
    const rows = tickets.map((ticket) => `
      <li><button type="button" class="my-ticket-row" data-my-ticket="${escapeHtml(ticket.public_id)}">
        <span><strong>${escapeHtml(ticket.subject || "人工服务")}</strong>
          <small>${escapeHtml(ticket.public_id)} · ${escapeHtml(fmtTime(ticket.created_at))}</small></span>
        ${ticketBadge(ticket.status)}
      </button></li>`).join("");
    if (append) el.myTicketsContent.querySelector("ul").insertAdjacentHTML("beforeend", rows);
    else el.myTicketsContent.innerHTML = rows ? `<ul class="my-tickets-list" aria-label="工单列表">${rows}</ul>` : "";
  }

  function renderMyTicket({ ticket, replies }, append) {
    const rows = replies.map((reply) => `
      <li><p class="my-ticket-reply-byline">${escapeHtml(reply.author || "人工客服")} · ${escapeHtml(fmtTime(reply.created_at))}</p>
        <p class="my-ticket-reply-body">${escapeHtml(reply.body)}</p></li>`).join("");
    if (append) {
      el.myTicketsContent.querySelector("ul").insertAdjacentHTML("beforeend", rows);
      return;
    }
    const localSession = ticket.portal_session && loadSessions().some((s) => s.id === ticket.portal_session);
    el.myTicketsContent.innerHTML = `<section class="my-ticket-detail" aria-labelledby="myTicketSubject">
      <div class="my-ticket-summary">
        <div class="my-ticket-heading"><h3 id="myTicketSubject">${escapeHtml(ticket.subject || "人工服务")}</h3>${ticketBadge(ticket.status)}</div>
        <p class="muted">${escapeHtml(ticket.public_id)} · ${escapeHtml(fmtTime(ticket.created_at))}${ticket.assignee_name ? ` · ${escapeHtml(ticket.assignee_name)}` : ""}</p>
      </div>
      <div><h4>人工回复</h4>
        ${rows ? `<ul class="my-ticket-replies">${rows}</ul>` : '<p class="muted">暂未收到人工回复。</p>'}
      </div>
      ${localSession ? `<button type="button" class="btn btn-sm" data-resume-session="${escapeHtml(ticket.portal_session)}">返回原对话</button>` : ""}
    </section>`;
  }

  async function loadMyTickets(before = null) {
    myTickets.request?.abort();
    const request = new AbortController();
    myTickets.request = request;
    const id = myTickets.id;
    const path = id ? `/api/portal/tickets/${encodeURIComponent(id)}` : "/api/portal/tickets";
    const query = before === null ? "" : `?before=${encodeURIComponent(before)}`;
    el.btnMoreMyTickets.disabled = true;
    showMyTicketsStatus("正在读取工单…");
    try {
      const res = await fetch(path + query, { signal: request.signal });
      if (request !== myTickets.request || !el.myTicketsModal.open) return;
      if (res.status === 404 && id) {
        el.myTicketsContent.replaceChildren();
        el.btnMoreMyTickets.hidden = true;
        showMyTicketsStatus("没有找到这张工单。", true);
        return;
      }
      if (!res.ok) throw new Error("工单读取失败");
      const data = await res.json();
      if (request !== myTickets.request || !el.myTicketsModal.open) return;
      if (id) renderMyTicket(data, before !== null);
      else renderMyTickets(data.tickets, before !== null);
      myTickets.before = data.next_before ?? null;
      el.btnMoreMyTickets.hidden = myTickets.before === null;
      el.btnMoreMyTickets.textContent = id ? "更早的回复" : "更早的工单";
      showMyTicketsStatus(!id && before === null && !data.tickets.length ? "暂无工单。提交人工服务后可在这里查看。" : "");
    } catch {
      if (request === myTickets.request && el.myTicketsModal.open) showMyTicketsStatus("读取失败，请刷新重试。", true);
    } finally {
      if (request === myTickets.request) {
        myTickets.request = null;
        el.btnMoreMyTickets.disabled = false;
      }
    }
  }

  function selectMyTicket(id = "") {
    el.myTicketsContent.replaceChildren();
    el.myTicketsModal.scrollTop = 0;
    el.btnBackMyTickets.hidden = !id;
    el.btnMoreMyTickets.hidden = true;
    el.myTicketsHint.hidden = !!id;
    myTickets.id = id;
    myTickets.before = null;
    loadMyTickets();
  }

  el.btnMyTickets.addEventListener("click", () => {
    el.myTicketsModal.showModal();
    selectMyTicket();
  });
  el.btnCloseMyTickets.addEventListener("click", () => el.myTicketsModal.close());
  el.btnRefreshMyTickets.addEventListener("click", () => loadMyTickets());
  el.btnBackMyTickets.addEventListener("click", () => {
    el.btnRefreshMyTickets.focus();
    selectMyTicket();
  });
  el.btnMoreMyTickets.addEventListener("click", () => loadMyTickets(myTickets.before));
  el.myTicketsModal.addEventListener("close", () => {
    if (el.myTicketsModal.open) return;
    myTickets.request?.abort();
    myTickets.request = null;
  });
  el.myTicketsModal.addEventListener("click", (event) => {
    if (event.target === el.myTicketsModal) el.myTicketsModal.close();
    const ticket = event.target.closest("[data-my-ticket]");
    if (ticket) {
      selectMyTicket(ticket.dataset.myTicket);
      el.btnBackMyTickets.focus();
    }
    const resume = event.target.closest("[data-resume-session]");
    if (!resume) return;
    if (restoreSession(resume.dataset.resumeSession)) {
      el.myTicketsModal.close();
      document.getElementById("assistant").focus();
    } else if (state.busy || state.ticketSubmitting) {
      showMyTicketsStatus("请等待当前操作结束，再返回对话。");
    } else {
      resume.remove();
      showMyTicketsStatus("本机历史里已找不到原对话。你仍可在这里查看回复。");
    }
  });

  el.composer.addEventListener("submit", (e) => {
    e.preventDefault();
    sendQuery();
  });

  el.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      sendQuery();
    }
  });
  el.input.addEventListener("input", autosize);

  el.btnStop.addEventListener("click", () => {
    if (state.busy) stopGenerating();
  });

  el.btnNewChat.addEventListener("click", startNewChat);
  if (el.btnExport) el.btnExport.addEventListener("click", exportConversation);
  if (el.btnNav) el.btnNav.addEventListener("click", openNav);
  if (el.btnCloseNav) el.btnCloseNav.addEventListener("click", closeNav);
  if (el.navModal) {
    el.navModal.addEventListener("click", (e) => {
      if (e.target === el.navModal) closeNav();
    });
  }
  if (el.navSearch) el.navSearch.addEventListener("input", renderNav);

  el.btnTicketTop.addEventListener("click", openTicket);
  el.btnCloseTicket.addEventListener("click", closeTicket);
  el.btnCancelTicket.addEventListener("click", closeTicket);
  el.ticketModal.addEventListener("click", (e) => {
    if (e.target === el.ticketModal) closeTicket();
  });
  el.ticketModal.addEventListener("cancel", (e) => {
    if (state.ticketSubmitting) e.preventDefault();
  });

  el.ticketForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (state.ticketSubmitting || state.busy) {
      el.ticketResult.hidden = false;
      el.ticketResult.textContent = state.busy ? "请等待当前答复结束后再提交工单。" : "正在提交工单…";
      return;
    }
    const fd = new FormData(el.ticketForm);
    const subject = maskPhone(String(fd.get("subject") || "").trim()).slice(0, 80);
    const detail = maskPhone(String(fd.get("detail") || "").trim());
    const contact = maskPhone(String(fd.get("contact") || "").trim());
    const subjectInput = el.ticketForm.querySelector("input[name=subject]");
    const detailInput = el.ticketForm.querySelector("textarea[name=detail]");
    const contactInput = el.ticketForm.querySelector("input[name=contact]");
    if (subjectInput) subjectInput.value = subject;
    if (detailInput) detailInput.value = detail;
    if (contactInput) contactInput.value = contact;
    const payload = { subject, detail, contact, portal_session: state.sessionId };
    const submit = el.ticketForm.querySelector('[type="submit"]');
    state.ticketSubmitting = true;
    setBusy(false);
    submit.disabled = true;
    el.ticketResult.classList.remove("error");
    el.ticketResult.textContent = "正在提交工单…";
    el.ticketResult.hidden = false;
    try {
      const res = await fetch("/api/ticket", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.message || data.error || "请稍后重试");
      if (data.queue) {
        noteTicket(data.ticket || { public_id: data.ticket_id, status: "waiting" });
        const line = detail ? `工单补充 · ${detail}` : `工单主题 · ${subject}`;
        appendSystem(line);
        state.messages.push({ role: "system", text: line });
        persistCurrentSession();
      }
      setStatus(`${data.queue ? "已提交" : "演示回执"} · 工单 ${data.ticket_id}`);
      el.ticketResult.textContent = data.message || "工单已提交";
      submit.hidden = true;
      el.btnCancelTicket.textContent = "返回对话";
      el.btnCancelTicket.focus();
    } catch (err) {
      el.ticketResult.classList.add("error");
      el.ticketResult.textContent = "提交失败 · " + (err.message || err);
    } finally {
      submit.disabled = false;
      state.ticketSubmitting = false;
      setBusy(false);
      pollPortal();
    }
  });

  async function pollPortal() {
    if (!state.sessionId || state.pollRequest || state.busy || state.ticketSubmitting || document.hidden) return;
    const request = new AbortController();
    state.pollRequest = request;
    const params = new URLSearchParams({ session: state.sessionId });
    if (state.portalCursor) params.set("after", String(state.portalCursor));
    try {
      const res = await fetch(`/api/portal/state?${params}`, { signal: request.signal });
      if (!res.ok) return;
      const data = await res.json();
      if (request !== state.pollRequest || state.busy || state.ticketSubmitting) return;
      showMaintenance(data.maintenance);
      setTicketProgress(data.ticket);
      let added = false;
      for (const msg of data.messages || []) {
        if (msg.id <= state.portalCursor) continue;
        const row = { role: msg.role, text: msg.body, serverId: msg.id };
        if (msg.role === "agent") {
          row.createdAt = clockOf(msg.created_at);
          row.author = msg.author || "人工客服";
          appendMessage("bot", formatAnswer(row.text), {
            agent: true,
            who: agentLabel(row),
          });
          renderCitations([]);
        } else if (msg.role === "system") appendSystem(row.text);
        else continue;
        state.messages.push(row);
        state.portalCursor = msg.id;
        added = true;
      }
      if (added) persistCurrentSession();
    } catch {
      if (!request.signal.aborted && request === state.pollRequest) setPill("状态暂不可用", "warn");
    } finally {
      if (request === state.pollRequest) state.pollRequest = null;
    }
  }

  el.messages.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-cite]");
    const answer = trigger && rowAnswers.get(trigger.closest(".msg"));
    if (!answer) return;
    const mark = Number(trigger.dataset.cite) || answer.citations[0].mark;
    renderCitations(answer.citations, answer.question, mark);
    const card = el.citeList.querySelector(`[data-marks~="${mark}"]`);
    card?.querySelector("summary")?.focus({ preventScroll: true });
    card?.scrollIntoView({ block: "nearest" });
  });

  document.querySelector("#main").addEventListener("click", (event) => {
    const button = event.target.closest("[data-q]");
    if (button) sendQuery(button.dataset.q);
  });

  // 恢复上次活动会话（若有消息）；否则空态
  const sessions = loadSessions();
  let activeId = "";
  try {
    activeId = localStorage.getItem(LS_ACTIVE) || "";
  } catch {
    activeId = "";
  }
  const active = sessions.find((s) => s.id === activeId && s.messages && s.messages.length);
  if (active) {
    hydrateSession(active);
    renderMessagesFromState();
    restoreSources();
    setStatus("已恢复本机会话 · 可继续追问");
  } else {
    state.sessionId = newSessionId();
    renderEmpty();
    setStatus("可以提问");
  }
  renderSessionList();
  pollPortal();
  setInterval(() => { if (!document.hidden) pollPortal(); }, 3000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) pollPortal(); });
})();
