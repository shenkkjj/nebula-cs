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

  /** 空态高频意图：少量入口，其余问题仍在顶栏。 */
  const EMPTY_CHIPS = [
    { label: "在读证明", query: "在读证明如何办理？" },
    { label: "助学贷款", query: "国家助学贷款如何申请？" },
    { label: "宿舍报修", query: "宿舍报修怎么提交？" },
    { label: "校园网", query: "校园网如何认证登录？" },
    { label: "查办事进度", query: "查询办事进度 SW20260001" },
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
    btnToggleFaq: document.getElementById("btnToggleFaq"),
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
      historyCutoff: state.historyCutoff || 0,
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
    state.historyCutoff = s.historyCutoff || 0;
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
          suggestions: m.suggestions || [],
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
    state.historyCutoff = 0;
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
        <h3>你好，我是校园助手</h3>
        <p>按校园知识库回答办事问题，并标出依据。也能做计算、换算和校园用语短翻译。说不清的校规不会编，需要工作人员就转人工。</p>
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
    const who = role === "user" ? "同学" : "校园助手";
    wrap.innerHTML = `<div class="who">${who}</div><div class="bubble">${html}</div>`;
    if (opts.refuse) {
      const actions = document.createElement("div");
      actions.className = "msg-actions";
      actions.innerHTML = `<button type="button" class="solid" data-action="ticket">转人工坐席</button>`;
      actions.querySelector("button").addEventListener("click", openTicket);
      wrap.appendChild(actions);
    }
    mountSuggestions(wrap, opts.suggestions);
    if (role === "bot") mountBotTools(wrap);
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
    wrap.innerHTML = `<div class="who">校园助手</div><div class="bubble"><span class="stream-body"></span><span class="stream-cursor" aria-hidden="true"></span></div>`;
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

  function finishBotStream(text, opts) {
    if (typeof opts === "boolean") opts = { refuse: opts };
    opts = opts || {};
    const row = document.getElementById("streamRow");
    if (!row) {
      appendMessage("bot", formatAnswer(text), opts);
      return;
    }
    row.id = "";
    if (opts.refuse) row.classList.add("refuse");
    const bubble = row.querySelector(".bubble");
    if (bubble) bubble.innerHTML = formatAnswer(text);
    const cursor = row.querySelector(".stream-cursor");
    if (cursor) cursor.remove();
    if (opts.refuse && !row.querySelector(".msg-actions")) {
      const actions = document.createElement("div");
      actions.className = "msg-actions";
      actions.innerHTML = `<button type="button" class="solid" data-action="ticket">转人工坐席</button>`;
      actions.querySelector("button").addEventListener("click", openTicket);
      row.appendChild(actions);
    }
    mountSuggestions(row, opts.suggestions);
    mountBotTools(row);
    el.messages.scrollTop = el.messages.scrollHeight;
  }

  function mountBotTools(row) {
    if (!row || row.querySelector(".bot-tools")) return;
    const bar = document.createElement("div");
    bar.className = "bot-tools";
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "mini";
    copy.textContent = "复制";
    copy.addEventListener("click", () => copyAnswer(row, copy));
    const yes = document.createElement("button");
    yes.type = "button";
    yes.className = "mini";
    yes.textContent = "有帮助";
    yes.addEventListener("click", () => recordFeedback(row, true));
    const no = document.createElement("button");
    no.type = "button";
    no.className = "mini";
    no.textContent = "没解决";
    no.addEventListener("click", () => recordFeedback(row, false));
    bar.append(copy, yes, no);
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

  function recordFeedback(row, helpful) {
    const note = row.querySelector(".feedback-note");
    if (note) note.remove();
    const entry = {
      at: Date.now(),
      helpful: !!helpful,
      topic: lastUserText(),
    };
    try {
      const key = "nebula-cs-feedback-v1";
      const prev = JSON.parse(localStorage.getItem(key) || "[]");
      const list = Array.isArray(prev) ? prev : [];
      list.unshift(entry);
      localStorage.setItem(key, JSON.stringify(list.slice(0, 40)));
    } catch {
      /* quota or private mode: still tell the user nothing was sent */
    }
    const line = document.createElement("p");
    line.className = "feedback-note";
    if (helpful) {
      line.textContent = "已记在本机，没有交给工作人员。";
    } else {
      line.textContent = "已记在本机，没有交给工作人员。可以换一种问法，或转人工。";
      if (!row.querySelector(".msg-actions")) {
        const actions = document.createElement("div");
        actions.className = "msg-actions";
        const button = document.createElement("button");
        button.type = "button";
        button.className = "solid";
        button.textContent = "转人工坐席";
        button.addEventListener("click", openTicket);
        actions.appendChild(button);
        row.appendChild(actions);
      }
    }
    row.appendChild(line);
    setStatus(helpful ? "本机记录：有帮助" : "本机记录：没解决 · 可转人工");
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
    el.navModal.hidden = false;
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
    if (el.navModal) el.navModal.hidden = true;
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

  function mountSuggestions(row, suggestions) {
    if (!row || !suggestions || !suggestions.length || row.querySelector(".suggest-chips")) return;
    const box = document.createElement("div");
    box.className = "suggest-chips";
    box.setAttribute("role", "group");
    box.setAttribute("aria-label", "可选问题");
    suggestions.forEach((item) => {
      const label = (item && (item.label || item.query)) || "";
      const q = (item && (item.query || item.label)) || "";
      if (!q) return;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip";
      btn.textContent = label;
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
    return next === raw ? null : next;
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
    // 最近若干轮，供代理侧查询改写（短指代追问）。重新开始之后不再带上旧话题。
    const start = state.historyCutoff || 0;
    return state.messages.slice(start).slice(-10).map((m) => ({
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
    const typed = (raw || el.input.value || "").trim();
    if (!typed || state.busy) return;
    const scrubbed = scrubLocal(typed);
    const query = scrubbed || typed;

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
        const suggestions = data.suggestions || [];
        finishBotStream(answer, { refuse: refuse || handoff, suggestions });
        state.messages.push({
          role: "bot",
          text: answer,
          refuse: refuse || handoff,
          handoff,
          action: data.agent_action,
          suggestions,
        });
        if (data.agent_action === "restart") {
          state.historyCutoff = state.messages.length;
          state.conversationId = "";
        }
        renderCitations(data.citations || []);
        if (handoff) {
          setStatus("已转人工 · 工单 " + (data.ticket_id || "") + "（演示存根）");
        } else if (data.agent_action === "order_lookup") {
          setStatus(data.order_found ? "办事进度已查出 · 演示存根" : "办事单未找到 · 可转人工");
        } else if (data.agent_action === "clarify") {
          setStatus("有几条都相关 · 点一个具体问题");
        } else if (data.agent_action === "restart") {
          setStatus("已重新开始");
        } else if (data.agent_action === "safety") {
          setStatus("已隐去敏感信息 · 请不要发送证件号或病历");
        } else if (data.agent_action === "general_skill") {
          setStatus("已用本地能力回答 · 未引用校规");
        } else {
          setStatus(
            refuse
              ? "这件事我做不了 · 可以换个问法或转人工"
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
      const suggestions = (finalPayload && finalPayload.suggestions) || [];
      if (finalPayload && finalPayload.rewrite) noteRewrite(finalPayload.rewrite);
      finishBotStream(answer, { refuse: refuse || handoff, suggestions });
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
      state.messages.push({
        role: "bot",
        text: answer,
        refuse: refuse || handoff,
        handoff,
        action,
        suggestions,
      });
      if (action === "restart") {
        state.historyCutoff = state.messages.length;
        state.conversationId = "";
      }
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
      } else if (action === "clarify") {
        setStatus("有几条都相关 · 点一个具体问题");
      } else if (action === "restart") {
        setStatus("已重新开始");
      } else if (action === "safety") {
        setStatus("已隐去敏感信息 · 请不要发送证件号或病历");
      } else if (action === "general_skill" || action === "assistant_intro") {
        setStatus(action === "assistant_intro" ? "校园助手已就绪" : "已用本地能力回答 · 未引用校规");
      } else {
        setStatus(
          refuse
            ? "这件事我做不了 · 可以换个问法或转人工"
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
      el.ticketResult.textContent = data.message || (data.ok === false ? "未提交" : "已提交");
      if (data.ok === false) setStatus("工单未提交 · 请去掉证件号或病历");
      else setStatus(data.ticket_id ? "工单 " + data.ticket_id + " 已登记" : "工单已提交");
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
