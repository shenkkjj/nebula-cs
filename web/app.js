(() => {
  "use strict";

  const FAQ = [
    "在读证明如何办理？",
    "成绩在哪里查询？",
    "选课时间是什么时候？",
    "如何退课？",
    "国家助学贷款如何申请？",
    "图书馆开放时间是什么？",
    "如何借书和续借？",
    "宿舍报修怎么提交？",
    "宿舍水电费如何查询和缴纳？",
    "宿舍门禁时间是什么？",
    "校园网如何认证登录？",
    "VPN 如何使用？",
    "校园卡如何充值和挂失？",
    "校医院如何预约挂号？",
    "心理咨询如何预约？",
    "教室借用怎么申请？",
    "寒暑假校园作息怎么安排？",
    "办事进度如何查询？",
    "办事进度状态分别是什么意思？",
    "什么情况下应转人工？",
  ];

  /** 空态主题 chips：一键发送，问句与知识库标题对齐 */
  const EMPTY_CHIPS = [
    { label: "在读证明", query: "在读证明如何办理？" },
    { label: "查成绩", query: "成绩在哪里查询？" },
    { label: "退课", query: "如何退课？" },
    { label: "助学贷款", query: "国家助学贷款如何申请？" },
    { label: "图书馆", query: "图书馆开放时间是什么？" },
    { label: "宿舍报修", query: "宿舍报修怎么提交？" },
    { label: "水电门禁", query: "宿舍门禁时间是什么？" },
    { label: "校园网", query: "校园网如何认证登录？" },
    { label: "校园卡", query: "校园卡如何充值和挂失？" },
    { label: "心理预约", query: "心理咨询如何预约？" },
    { label: "教室借用", query: "教室借用怎么申请？" },
    { label: "假期作息", query: "寒暑假校园作息怎么安排？" },
    { label: "查办事", query: "查询办事进度 SW20260001" },
    { label: "转人工", query: "转人工" },
  ];

  const LS_KEY = "nebula-cs-sessions-v1";
  const LS_ACTIVE = "nebula-cs-active-session";

  const el = {
    messages: document.getElementById("messages"),
    citeList: document.getElementById("citeList"),
    faqChips: document.getElementById("faqChips"),
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
    btnTicketTop: document.getElementById("btnTicketTop"),
    btnCloseTicket: document.getElementById("btnCloseTicket"),
    btnCancelTicket: document.getElementById("btnCancelTicket"),
    btnToggleFaq: document.getElementById("btnToggleFaq"),
  };

  const state = {
    conversationId: "",
    userId: loadUserId(),
    busy: false,
    abort: null,
    taskId: "",
    sessionId: "",
    messages: [], // {role, text, refuse?}
  };

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

  function setStatus(text) {
    if (el.statusText) el.statusText.textContent = text;
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

  function loadSessions() {
    try {
      const raw = localStorage.getItem(LS_KEY);
      const list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
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
    const title =
      (state.messages.find((m) => m.role === "user") || {}).text || "新对话";
    const entry = {
      id: state.sessionId,
      conversationId: state.conversationId || "",
      title: String(title).slice(0, 40),
      updatedAt: Date.now(),
      messages: state.messages.slice(-40),
    };
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
          <div class="t">${escapeHtml(s.title || "未命名")}</div>
          <div class="d">${escapeHtml(fmtTime(s.updatedAt))} · ${s.messages ? s.messages.length : 0} 条</div>
        </button>`;
      })
      .join("");
    el.sessionList.querySelectorAll(".session-item").forEach((btn) => {
      btn.addEventListener("click", () => restoreSession(btn.getAttribute("data-sid")));
    });
  }

  function restoreSession(sid) {
    if (state.busy) return;
    const list = loadSessions();
    const s = list.find((x) => x.id === sid);
    if (!s) return;
    state.sessionId = s.id;
    state.conversationId = s.conversationId || "";
    state.messages = Array.isArray(s.messages) ? s.messages.slice() : [];
    try {
      localStorage.setItem(LS_ACTIVE, sid);
    } catch {
      /* ignore */
    }
    renderMessagesFromState();
    renderCitations([]);
    renderSessionList();
    setStatus("已切换会话 · 可继续追问");
  }

  function renderMessagesFromState() {
    el.messages.innerHTML = "";
    if (!state.messages.length) {
      renderEmpty();
      return;
    }
    state.messages.forEach((m) => {
      if (m.role === "user") {
        appendMessage("user", escapeHtml(m.text), { persist: false });
      } else {
        appendMessage("bot", formatAnswer(m.text), {
          refuse: !!m.refuse,
          persist: false,
        });
      }
    });
  }

  function newSessionId() {
    return "s-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 7);
  }

  function startNewChat(opts = {}) {
    if (state.busy && state.abort) {
      stopGenerating();
    }
    state.conversationId = "";
    state.taskId = "";
    state.messages = [];
    state.sessionId = newSessionId();
    try {
      localStorage.setItem(LS_ACTIVE, state.sessionId);
    } catch {
      /* ignore */
    }
    el.faqChips.querySelectorAll(".chip").forEach((x) => x.classList.remove("active"));
    renderEmpty();
    renderCitations([]);
    renderSessionList();
    setStatus(opts.status || "新对话已开始");
    el.input.focus();
  }

  function renderEmpty() {
    const chips = EMPTY_CHIPS.map(
      (c) =>
        `<button type="button" class="chip" data-q="${escapeHtml(c.query)}">${escapeHtml(
          c.label
        )}</button>`
    ).join("");
    el.messages.innerHTML = `
      <div class="empty-state">
        <div class="mark" aria-hidden="true">云</div>
        <h3>你好，我是星云校园客服助手</h3>
        <p>基于校园私有知识库回答教务学籍、奖助贷、图书馆、宿舍后勤、校园网与校园卡、医务心理、教室借用和假期作息，并标注出处。支持多轮追问、办事进度演示查询与一键转人工。库外问题会拒答。</p>
        <div class="empty-chips" role="group" aria-label="快捷提问">${chips}</div>
      </div>`;
    el.messages.querySelectorAll(".empty-chips .chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        const q = btn.getAttribute("data-q") || btn.textContent;
        sendQuery(q);
      });
    });
    if (!el.citeList.querySelector(".cite-card")) {
      el.citeList.innerHTML = `
        <div class="cite-empty">
          <p>提问后，这里会展示可展开的出处卡片（文档名、相关度与原文片段）。</p>
        </div>`;
    }
  }

  function appendMessage(role, html, opts = {}) {
    const empty = el.messages.querySelector(".empty-state");
    if (empty) empty.remove();

    const wrap = document.createElement("div");
    wrap.className = "msg " + role + (opts.refuse ? " refuse" : "");
    const who = role === "user" ? "同学" : "星云助手";
    wrap.innerHTML = `<div class="who">${who}</div><div class="bubble">${html}</div>`;
    if (opts.refuse) {
      const actions = document.createElement("div");
      actions.className = "msg-actions";
      actions.innerHTML = `<button type="button" class="solid" data-action="ticket">转人工坐席</button>`;
      actions.querySelector("button").addEventListener("click", openTicket);
      wrap.appendChild(actions);
    }
    el.messages.appendChild(wrap);
    el.messages.scrollTop = el.messages.scrollHeight;
    return wrap;
  }

  function beginBotStream() {
    const empty = el.messages.querySelector(".empty-state");
    if (empty) empty.remove();
    const wrap = document.createElement("div");
    wrap.className = "msg bot";
    wrap.id = "streamRow";
    wrap.innerHTML = `<div class="who">星云助手</div><div class="bubble"><span class="stream-body"></span><span class="stream-cursor" aria-hidden="true"></span></div>`;
    el.messages.appendChild(wrap);
    el.messages.scrollTop = el.messages.scrollHeight;
    return wrap;
  }

  function updateBotStream(text) {
    const row = document.getElementById("streamRow");
    if (!row) return;
    const body = row.querySelector(".stream-body");
    if (body) body.innerHTML = formatAnswer(text);
    el.messages.scrollTop = el.messages.scrollHeight;
  }

  function finishBotStream(text, refuse) {
    const row = document.getElementById("streamRow");
    if (!row) {
      appendMessage("bot", formatAnswer(text), { refuse });
      return;
    }
    row.id = "";
    if (refuse) row.classList.add("refuse");
    const bubble = row.querySelector(".bubble");
    if (bubble) bubble.innerHTML = formatAnswer(text);
    const cursor = row.querySelector(".stream-cursor");
    if (cursor) cursor.remove();
    if (refuse && !row.querySelector(".msg-actions")) {
      const actions = document.createElement("div");
      actions.className = "msg-actions";
      actions.innerHTML = `<button type="button" class="solid" data-action="ticket">转人工坐席</button>`;
      actions.querySelector("button").addEventListener("click", openTicket);
      row.appendChild(actions);
    }
    el.messages.scrollTop = el.messages.scrollHeight;
  }

  function renderCitations(citations) {
    if (!citations || !citations.length) {
      el.citeList.innerHTML = `
        <div class="cite-empty">
          <p>本轮未返回检索片段。若回答提示转人工，请使用右上角「转人工」。</p>
        </div>`;
      return;
    }
    el.citeList.innerHTML = citations
      .map((c, i) => {
        const score =
          typeof c.score === "number" ? (c.score * 100).toFixed(1) + "%" : "—";
        const snip = c.content || "";
        const preview = snip.replace(/\s+/g, " ").slice(0, 64);
        return `<article class="cite-card" data-idx="${i}" tabindex="0" role="button" aria-expanded="false">
          <div class="doc"><span>${escapeHtml(c.document_name || "文档")}</span><span class="score">${score}</span></div>
          <div class="meta"><span>${escapeHtml(c.dataset_name || "知识库")} · #${i + 1}</span><span class="chev">▶ 展开</span></div>
          ${preview ? `<div class="snip-preview">${escapeHtml(preview)}${snip.length > 64 ? "…" : ""}</div>` : ""}
          <div class="snip">${escapeHtml(snip) || "（无原文片段）"}</div>
        </article>`;
      })
      .join("");
    el.citeList.querySelectorAll(".cite-card").forEach((card) => {
      const toggle = () => {
        const open = card.classList.toggle("open");
        card.setAttribute("aria-expanded", open ? "true" : "false");
        const chev = card.querySelector(".chev");
        if (chev) chev.textContent = open ? "▼ 收起" : "▶ 展开";
      };
      card.addEventListener("click", toggle);
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggle();
        }
      });
    });
  }

  function buildChips() {
    el.faqChips.innerHTML = "";
    FAQ.forEach((q) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip";
      btn.textContent = q;
      btn.addEventListener("click", () => {
        el.faqChips.querySelectorAll(".chip").forEach((x) => x.classList.remove("active"));
        btn.classList.add("active");
        el.input.value = q;
        autosize();
        sendQuery(q);
      });
      el.faqChips.appendChild(btn);
    });
  }

  function autosize() {
    const ta = el.input;
    ta.style.height = "auto";
    ta.style.height = Math.min(140, ta.scrollHeight) + "px";
  }

  function setBusy(busy) {
    state.busy = busy;
    el.btnSend.disabled = busy;
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
    // 最近若干轮，供代理侧查询改写（短指代追问）
    return state.messages.slice(-10).map((m) => ({
      role: m.role === "bot" ? "assistant" : "user",
      text: String(m.text || "").slice(0, 500),
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

  async function sendQuery(raw) {
    const query = (raw || el.input.value || "").trim();
    if (!query || state.busy) return;

    if (!state.sessionId) state.sessionId = newSessionId();

    setBusy(true);
    el.input.value = "";
    autosize();

    appendMessage("user", escapeHtml(query), { persist: false });
    state.messages.push({ role: "user", text: query });
    persistCurrentSession();

    beginBotStream();
    setStatus("检索知识库并流式生成…");

    const controller = new AbortController();
    state.abort = controller;
    let acc = "";
    let finalPayload = null;
    let stopped = false;

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          query,
          user: state.userId,
          conversation_id: state.conversationId || undefined,
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
          finishBotStream(String(err), true);
          state.messages.push({ role: "bot", text: String(err), refuse: true });
          renderCitations([]);
          setStatus("调用失败");
          persistCurrentSession();
          return;
        }
        if (data.conversation_id) state.conversationId = data.conversation_id;
        const answer = data.answer || "（空响应）";
        const refuse = !!data.refuse;
        const handoff = !!data.handoff;
        if (data.rewrite) noteRewrite(data.rewrite);
        finishBotStream(answer, refuse || handoff);
        state.messages.push({ role: "bot", text: answer, refuse: refuse || handoff, handoff });
        renderCitations(data.citations || []);
        if (handoff) {
          setStatus("已转人工 · 工单 " + (data.ticket_id || "") + "（演示存根）");
        } else if (data.agent_action === "order_lookup") {
          setStatus(data.order_found ? "办事进度已查出 · 演示存根" : "办事单未找到 · 可转人工");
        } else {
          setStatus(
            refuse
              ? "知识库未覆盖或建议转人工 · 可提交演示工单"
              : `回答完成 · ${(data.citations || []).length} 条引用（非流式）` +
                (data.rewrite ? " · 已改写" : "")
          );
        }
        persistCurrentSession();
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
            if (ev.agent_action === "human_handoff") setStatus("正在转接人工（演示）…");
            if (ev.agent_action === "order_lookup") setStatus("正在查询办事进度…");
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

      const answer = (finalPayload && finalPayload.answer) || acc || "（空响应）";
      const refuse = finalPayload ? !!finalPayload.refuse : false;
      const citations = (finalPayload && finalPayload.citations) || [];
      const handoff = !!(finalPayload && finalPayload.handoff);
      const action = (finalPayload && finalPayload.agent_action) || "";
      if (finalPayload && finalPayload.rewrite) noteRewrite(finalPayload.rewrite);
      finishBotStream(answer, refuse || handoff);
      // 转人工也给出一键工单按钮
      if (handoff) {
        const row = el.messages.lastElementChild;
        if (row && !row.querySelector(".msg-actions")) {
          const actions = document.createElement("div");
          actions.className = "msg-actions";
          const tid = (finalPayload && finalPayload.ticket_id) || "";
          actions.innerHTML = `<button type="button" class="solid" data-action="ticket">补充工单信息</button>`;
          actions.querySelector("button").addEventListener("click", () => {
            openTicket();
            const subj = el.ticketForm.querySelector("input[name=subject]");
            if (subj && !subj.value) subj.value = tid ? "跟进工单 " + tid : "转人工跟进";
          });
          row.appendChild(actions);
        }
      }
      state.messages.push({ role: "bot", text: answer, refuse: refuse || handoff, handoff, action });
      renderCitations(citations);
      if (handoff) {
        setStatus(
          "已转人工 · 工单 " + ((finalPayload && finalPayload.ticket_id) || "") + "（演示存根）"
        );
      } else if (action === "order_lookup") {
        setStatus(
          (finalPayload && finalPayload.order_found)
            ? "办事进度已查出 · 演示存根"
            : "办事单未找到 · 可转人工"
        );
      } else {
        setStatus(
          refuse
            ? "知识库未覆盖或建议转人工 · 可提交演示工单"
            : `回答完成 · ${citations.length} 条引用 · 流式` +
              (finalPayload && finalPayload.rewrite ? " · 已改写" : "")
        );
      }
      persistCurrentSession();
    } catch (err) {
      if (err && err.name === "AbortError") {
        stopped = true;
        const partial = acc.trim() || "（已停止生成）";
        finishBotStream(partial + (acc.trim() ? "\n\n— 已停止生成 —" : ""), false);
        state.messages.push({ role: "bot", text: partial + "\n\n— 已停止生成 —", refuse: false });
        setStatus("已停止生成");
        persistCurrentSession();
      } else {
        const msg = "网络异常：" + (err && err.message ? err.message : err);
        finishBotStream(msg, true);
        state.messages.push({ role: "bot", text: msg, refuse: true });
        setStatus("网络异常");
        persistCurrentSession();
      }
    } finally {
      setBusy(false);
      if (!stopped) el.input.focus();
      else el.input.focus();
    }
  }

  function openTicket() {
    el.ticketResult.hidden = true;
    el.ticketResult.textContent = "";
    el.ticketForm.reset();
    el.ticketModal.hidden = false;
    const first = el.ticketForm.querySelector("input[name=subject]");
    const lastUser = [...state.messages].reverse().find((m) => m.role === "user");
    if (first && lastUser && !first.value) {
      first.value = ("跟进：" + String(lastUser.text || "")).slice(0, 80);
    }
    if (first) first.focus();
  }

  function closeTicket() {
    el.ticketModal.hidden = true;
  }

  el.composer.addEventListener("submit", (e) => {
    e.preventDefault();
    sendQuery();
  });

  el.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendQuery();
    }
  });
  el.input.addEventListener("input", autosize);

  el.btnStop.addEventListener("click", () => {
    if (state.busy) stopGenerating();
  });

  el.btnNewChat.addEventListener("click", () => startNewChat({ status: "新对话已开始" }));

  el.btnTicketTop.addEventListener("click", openTicket);
  el.btnCloseTicket.addEventListener("click", closeTicket);
  el.btnCancelTicket.addEventListener("click", closeTicket);
  el.ticketModal.addEventListener("click", (e) => {
    if (e.target === el.ticketModal) closeTicket();
  });

  el.ticketForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(el.ticketForm);
    const payload = {
      subject: String(fd.get("subject") || "").trim(),
      detail: String(fd.get("detail") || "").trim(),
      contact: String(fd.get("contact") || "").trim(),
    };
    try {
      const res = await fetch("/api/ticket", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      el.ticketResult.hidden = false;
      el.ticketResult.textContent = data.message || "已提交";
      setStatus(data.ticket_id ? "工单 " + data.ticket_id + " 已登记" : "工单已提交");
    } catch (err) {
      el.ticketResult.hidden = false;
      el.ticketResult.textContent = "提交失败：" + (err.message || err);
    }
  });

  if (el.btnToggleFaq) {
    el.btnToggleFaq.addEventListener("click", () => {
      if (el.faqChips) el.faqChips.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  buildChips();

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
    state.sessionId = active.id;
    state.conversationId = active.conversationId || "";
    state.messages = active.messages.slice();
    renderMessagesFromState();
    renderCitations([]);
    setStatus("已恢复本机会话 · 可继续追问");
  } else {
    state.sessionId = newSessionId();
    renderEmpty();
    setStatus("就绪 · 智能客服助手 · 改写 / 转人工 / 办事进度已启用");
  }
  renderSessionList();
  el.input.focus();
})();
