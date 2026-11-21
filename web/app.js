"use strict";
(() => {
  const byId = (id) => document.getElementById(id);
  const input = byId("queryInput");
  const messages = byId("messages");
  const chatContent = byId("chatContent");
  const navModal = byId("navModal");
  const historyModal = byId("historyModal");
  const sourcePanel = byId("sourcePanel");
  const audienceButtons = [...document.querySelectorAll("[data-audience]")];
  const sessionLists = [byId("sessionList"), byId("mobileSessions")];
  const storageKey = "nebula-qut-sessions-v1";
  const catalogs = new Map();
  const drafts = { student: "", staff: "" };
  const dateTime = new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
  const state = { audience: "student", id: "", conversationId: "", messages: [], request: null, taskId: "" };
  const schoolDirectory = "https://www.qut.edu.cn/zzjg.htm";
  let selectedGroup = "";
  let navRevision = 0;
  let composing = false;

  const id = () => globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  const readStorage = (key) => {
    try { return localStorage.getItem(key); } catch { return null; }
  };
  const writeStorage = (key, value) => {
    try { localStorage.setItem(key, value); } catch { /* Storage may be disabled. */ }
  };
  const userId = readStorage("nebula-qut-visitor") || id();
  writeStorage("nebula-qut-visitor", userId);

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  const icon = (name, cls = "") => `<svg class="icon ${cls}" aria-hidden="true"><use href="/assets/icons.svg#${name}" /></svg>`;
  const status = (text) => { byId("statusText").textContent = text; };

  function scrub(text) {
    const medical = /(病历|病例|化验单|出院小结|出院记录|诊断证明|诊断书)/;
    if (medical.test(text) && (text.length > 36 || /\n|\d{6,}/.test(text))) return "［病历内容已隐去］";
    return nebulaMask.maskPhone(text
      .replace(/(?<!\d)\d{17}[\dXx](?!\d)/g, "［身份证号已隐去］")
      .replace(/(?<!\d)\d{16,19}(?!\d)/g, "［卡号已隐去］"));
  }

  function officialUrl(value) {
    try {
      const url = new URL(value);
      const school = url.hostname === "qut.edu.cn" || url.hostname.endsWith(".qut.edu.cn");
      return url.protocol === "https:" && school && !url.username && !url.password && !url.port ? url.href : "";
    } catch { return ""; }
  }

  function snapshot(citations) {
    if (!Array.isArray(citations)) return [];
    return citations.slice(0, 8).flatMap((item, index) => {
      if (!item || typeof item !== "object") return [];
      const excerpts = [item.content, ...(Array.isArray(item.segments) ? item.segments.map((row) => row?.content) : [])];
      return [{
        mark: Number(item.mark) || index + 1,
        title: String(item.document_name || item.title || "资料").slice(0, 180),
        url: officialUrl(item.source_url),
        text: [...new Set(excerpts.filter((text) => typeof text === "string" && text))].slice(0, 3).join("\n\n").slice(0, 1000),
      }];
    });
  }

  function formatAnswer(text, citations = []) {
    return escapeHtml(text).replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\[(\d+)\]/g, (raw, mark) => citations.some((item) => item.mark === Number(mark))
        ? `<button type="button" class="cite-mark" data-source="${mark}" aria-label="查看出处 ${mark}">${raw}</button>` : raw);
  }

  function readSessions() {
    try {
      const list = JSON.parse(readStorage(storageKey) || "[]");
      return Array.isArray(list) ? list.filter((item) => typeof item?.id === "string" && Array.isArray(item.messages) && ["student", "staff"].includes(item.audience)).slice(0, 20) : [];
    } catch { return []; }
  }

  function renderHistory() {
    const rows = readSessions().filter((item) => item.audience === state.audience);
    const html = rows.map((item) => {
      const stamp = new Date(item.updatedAt);
      const time = Number.isFinite(stamp.getTime()) ? dateTime.format(stamp) : "";
      return `<button type="button" class="session-item" data-session="${escapeHtml(item.id)}"${item.id === state.id ? ' aria-current="true"' : ""}${state.request ? " disabled" : ""}>
        <strong>${escapeHtml(nebulaMask.sessionTitle(item.title))}</strong><time>${escapeHtml(time)}</time></button>`;
    }).join("") || '<p class="session-empty">暂无对话</p>';
    for (const list of sessionLists) list.innerHTML = html;
  }

  function persist() {
    if (!state.id || !state.messages.length) return;
    const recent = state.messages.slice(-40).map((message, index, items) => {
      if (index >= items.length - 12 || !message.citations?.length) return message;
      return { ...message, citations: [] };
    });
    const row = nebulaMask.maskStoredSession({
      id: state.id, audience: state.audience, conversationId: state.conversationId,
      updatedAt: Date.now(), messages: recent,
    });
    const rows = readSessions().filter((item) => item.id !== state.id);
    writeStorage(storageKey, JSON.stringify([row, ...rows].slice(0, 20)));
    writeStorage(`${storageKey}-${state.audience}`, state.id);
    renderHistory();
  }

  function activate(session, draft = "") {
    state.id = session?.id || "";
    state.conversationId = String(session?.conversationId || "");
    state.messages = (session?.messages || []).filter((row) => row && typeof row.text === "string" && ["bot", "user"].includes(row.role));
    writeStorage(`${storageKey}-${state.audience}`, state.id);
    input.value = draft;
    messages.replaceChildren(...state.messages.map((row) => renderMessage(row)));
    syncThread();
    updateComposer();
    renderHistory();
    scrollEnd();
  }

  function activeSession() {
    const active = readStorage(`${storageKey}-${state.audience}`);
    return readSessions().find((row) => row.audience === state.audience && row.id === active);
  }

  function selectAudience(audience) {
    if (state.request || audience === state.audience) return;
    drafts[state.audience] = input.value;
    state.audience = audience;
    for (const button of audienceButtons) button.setAttribute("aria-pressed", String(button.dataset.audience === audience));
    activate(activeSession(), drafts[audience]);
    loadShortcuts();
  }

  function syncThread() {
    const empty = !state.messages.length;
    byId("emptyState").hidden = !empty;
    messages.hidden = empty;
    byId("btnExport").hidden = empty;
  }

  function updateComposer() {
    const pending = !!state.request;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 132)}px`;
    byId("btnSend").disabled = pending || !input.value.trim();
    byId("btnStop").hidden = !pending;
    for (const button of document.querySelectorAll("[data-audience], [data-command=new], [data-session], button[data-query]")) button.disabled = pending;
  }

  function iconButton(name, label, attrs) {
    return `<button type="button" class="mini" aria-label="${label}" title="${label}" ${attrs}>${icon(name)}</button>`;
  }

  function renderMessage(message, streaming = false) {
    const row = document.createElement("article");
    row.className = `msg ${message.role}${streaming ? " streaming" : ""}${message.error ? " error" : ""}`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    if (message.role === "bot") {
      row.innerHTML = '<p class="who">校园助手</p>';
      bubble.innerHTML = formatAnswer(message.text, message.citations);
    } else {
      bubble.textContent = message.text;
    }
    row.appendChild(bubble);
    if (streaming || message.role !== "bot") return row;
    const tools = document.createElement("div");
    tools.className = "bot-tools";
    if (message.error) {
      tools.innerHTML = `<button type="button" class="chip" data-query="${escapeHtml(message.question)}">重试</button>`;
    } else {
      tools.innerHTML = `${message.citations?.length ? '<button type="button" class="mini" data-source="0">查看出处</button>' : ""}${iconButton("copy", "复制答复", "data-copy")}`;
      if (message.serverId) {
        tools.insertAdjacentHTML("beforeend", iconButton("thumbs-up", "有帮助", `data-vote="yes" aria-pressed="${message.vote === true}"`) + iconButton("thumbs-down", "没解决", `data-vote="no" aria-pressed="${message.vote === false}"`));
      }
      if (message.refuse && !message.maintenance) tools.insertAdjacentHTML("beforeend", `<a class="official-fallback" href="${schoolDirectory}" target="_blank" rel="noopener noreferrer">学校部门目录</a>`);
    }
    row.appendChild(tools);
    if (message.suggestions?.length) {
      const suggestions = document.createElement("div");
      suggestions.className = "suggestions";
      for (const item of message.suggestions.slice(0, 4)) {
        if (!item?.query && !item?.label) continue;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "chip";
        button.dataset.query = item.query || item.label;
        button.textContent = item.label || item.query;
        suggestions.appendChild(button);
      }
      row.appendChild(suggestions);
    }
    if (message.vote !== undefined) row.dataset.rated = "true";
    row.addEventListener("click", (event) => {
      const button = event.target.closest("button");
      if (!button) return;
      if ("source" in button.dataset) showSources(message.citations, Number(button.dataset.source));
      if ("copy" in button.dataset) copyAnswer(message.text, button);
      if ("vote" in button.dataset) recordVote(row, message, button.dataset.vote === "yes");
    });
    return row;
  }

  function showSources(citations, mark) {
    const list = mark ? citations.filter((item) => item.mark === mark) : citations;
    byId("citeList").innerHTML = list.map((item) => {
      const url = officialUrl(item.url);
      return `<article class="cite-card"><h3>${escapeHtml(item.title)}</h3>${item.text ? `<p>${escapeHtml(item.text)}</p>` : ""}${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">打开学校原文${icon("arrow-up-right")}</a>` : ""}</article>`;
    }).join("");
    if (list.length && !sourcePanel.open) sourcePanel.showModal();
  }

  async function copyAnswer(text, button) {
    try {
      if (navigator.clipboard) await navigator.clipboard.writeText(text);
      else {
        const temp = document.createElement("textarea");
        temp.value = text;
        temp.style.position = "fixed";
        temp.style.opacity = "0";
        document.body.appendChild(temp);
        temp.select();
        const copied = document.execCommand("copy");
        temp.remove();
        button.focus();
        if (!copied) throw new Error("copy");
      }
      status("已复制");
      button.innerHTML = icon("check");
      setTimeout(() => { button.innerHTML = icon("copy"); }, 1400);
    } catch { status("复制失败"); }
  }

  async function recordVote(row, message, helpful) {
    const sessionId = state.id;
    const buttons = [...row.querySelectorAll("[data-vote]")];
    if (!message.serverId || buttons.some((button) => button.disabled)) return;
    const notes = row.querySelector(".rating-status") || document.createElement("span");
    notes.className = "rating-status";
    notes.setAttribute("role", "status");
    row.querySelector(".bot-tools").appendChild(notes);
    notes.textContent = "";
    for (const button of buttons) button.disabled = true;
    try {
      const res = await fetch("/api/feedback", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: message.serverId, helpful, portal_session: sessionId }),
      });
      if (!res.ok) throw new Error("feedback");
      message.vote = helpful;
      for (const button of buttons) button.setAttribute("aria-pressed", String((button.dataset.vote === "yes") === helpful));
      notes.textContent = "已评价";
      if (sessionId === state.id) persist();
    } catch { notes.textContent = "评价未送达"; }
    finally { for (const button of buttons) button.disabled = false; }
  }

  function scrollEnd(force = true) {
    if (force) chatContent.scrollTop = chatContent.scrollHeight;
  }

  function nearEnd() { return chatContent.scrollHeight - chatContent.scrollTop - chatContent.clientHeight < 90; }

  function showMaintenance() {
    byId("noticeBar").textContent = "知识库维护中";
    byId("noticeBar").hidden = false;
  }

  async function readReply(res, row) {
    if (!res.ok || !res.headers.get("content-type")?.includes("text/event-stream")) {
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error("request");
      return payload;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    const bubble = row.querySelector(".bubble");
    let buffer = "";
    let text = "";
    let final = null;
    const eventLine = (line) => {
      const data = line.trim();
      if (!data.startsWith("data:")) return;
      let event;
      try { event = JSON.parse(data.slice(5)); } catch { return; }
      if (event.type === "start") {
        state.taskId = event.task_id || "";
        state.conversationId = event.conversation_id || state.conversationId;
      } else if (event.type === "status" && event.phase === "generating" && !text) {
        bubble.textContent = "正在作答…";
      } else if (event.type === "delta") {
        const pinned = nearEnd();
        text += event.text || "";
        bubble.innerHTML = formatAnswer(text);
        scrollEnd(pinned);
      } else if (event.type === "done") {
        final = event;
      } else if (event.type === "error") {
        throw new Error("stream");
      }
    };
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) eventLine(line);
      }
      eventLine(buffer + decoder.decode());
    } finally {
      reader.releaseLock();
    }
    if (!final) throw new Error("incomplete stream");
    return { ...final, answer: final.answer || text };
  }

  async function sendQuery(raw) {
    const typed = String(raw ?? input.value).trim();
    if (!typed || state.request) return;
    const query = scrub(typed.slice(0, 2000));
    const history = state.messages.filter((row) => !row.error && !row.stopped).slice(-10).map((row) => ({
      role: row.role === "bot" ? "assistant" : "user", text: row.text.slice(0, 500),
    }));
    const request = new AbortController();
    state.request = request;
    if (!state.id) state.id = id();
    input.value = "";
    drafts[state.audience] = "";
    const user = { role: "user", text: query };
    state.messages.push(user);
    const pending = renderMessage({ role: "bot", text: "正在查找依据…" }, true);
    messages.append(renderMessage(user), pending);
    syncThread();
    updateComposer();
    persist();
    scrollEnd();
    status("正在查找依据");
    let answer;
    try {
      const res = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" }, signal: request.signal,
        body: JSON.stringify({ query, stream: true, user: userId, audience: state.audience, conversation_id: state.conversationId || undefined, portal_session: state.id, history }),
      });
      const result = await readReply(res, pending);
      state.conversationId = result.conversation_id || state.conversationId;
      answer = { role: "bot", question: query, text: result.answer || "没有收到答复。", refuse: !!result.refuse,
        maintenance: !!result.maintenance, serverId: Number(result.server_message_id) || 0,
        citations: snapshot(result.citations), suggestions: Array.isArray(result.suggestions) ? result.suggestions : [] };
      if (answer.maintenance) showMaintenance();
      else byId("noticeBar").hidden = true;
      status("答复完成");
    } catch {
      const stopped = request.signal.aborted;
      answer = { role: "bot", question: query, text: stopped ? "已停止" : "暂时无法答复，请重试。", error: !stopped, stopped };
      status(answer.text);
    } finally {
      const pinned = nearEnd();
      state.request = null;
      state.taskId = "";
      state.messages.push(answer);
      pending.replaceWith(renderMessage(answer));
      updateComposer();
      persist();
      scrollEnd(pinned);
    }
  }

  function loadCatalog(audience) {
    if (!catalogs.has(audience)) {
      const request = fetch(`/api/faq-nav?audience=${encodeURIComponent(audience)}`).then((res) => {
        if (!res.ok) throw new Error("catalog");
        return res.json();
      }).catch((error) => { catalogs.delete(audience); throw error; });
      catalogs.set(audience, request);
    }
    return catalogs.get(audience);
  }

  async function loadShortcuts() {
    const audience = state.audience;
    const target = byId("quickQuestions");
    target.replaceChildren();
    try {
      const data = await loadCatalog(audience);
      if (audience !== state.audience) return;
      const shortcuts = data.shortcuts || (data.categories || []).slice(0, 4).map((group) => ({ group: group.name, label: group.items?.[0]?.title, query: group.items?.[0]?.query }));
      const icons = { "证件与证明": "file", "校园生活": "tools", "网络与系统": "wifi", "人事事务": "user" };
      target.innerHTML = shortcuts.slice(0, 4).filter((item) => item?.query).map((item) => `<button type="button" class="quick-action" data-query="${escapeHtml(item.query)}"${state.request ? " disabled" : ""}>${icon(icons[item.group] || "book")}<span>${escapeHtml(item.label || item.query)}</span>${icon("chevron", "outgoing")}</button>`).join("");
    } catch { /* The composer is still usable without the catalog. */ }
  }

  async function renderNav(refresh = false) {
    const revision = ++navRevision;
    const view = byId("navList");
    const cats = byId("navCats");
    if (refresh) {
      cats.replaceChildren();
      view.innerHTML = '<p class="nav-status" role="status">加载中…</p>';
    }
    try {
      const data = await loadCatalog(state.audience);
      if (!navModal.open || revision !== navRevision) return;
      const groups = data.categories || [];
      const names = ["", ...groups.map((group) => group.name)];
      if (cats.childElementCount !== names.length) {
        cats.innerHTML = names.map((name) => `<button type="button" class="chip" data-group="${escapeHtml(name)}">${escapeHtml(name || "全部")}</button>`).join("");
      }
      for (const button of cats.children) button.setAttribute("aria-pressed", String(button.dataset.group === selectedGroup));
      const search = byId("navSearch").value.toLowerCase().trim();
      view.innerHTML = groups.filter((group) => !selectedGroup || group.name === selectedGroup).map((group) => {
        const matching = (group.items || []).filter((item) => [item.title, item.query, ...(item.keywords || [])].some((value) => String(value || "").toLowerCase().includes(search)));
        if (!matching.length) return "";
        return `<section class="nav-group"><h3>${escapeHtml(group.name)}</h3>${matching.slice(0, 80).map((item) => `<button type="button" class="nav-item" data-query="${escapeHtml(item.query || item.title)}"${state.request ? " disabled" : ""}>${escapeHtml(item.title || item.query)}${icon("chevron")}</button>`).join("")}</section>`;
      }).join("") || '<p class="nav-status">没有匹配的指南</p>';
    } catch {
      if (navModal.open && revision === navRevision) view.innerHTML = '<button type="button" class="btn btn-sm" data-command="retry-nav">重试</button>';
    }
  }

  byId("composer").addEventListener("submit", (event) => { event.preventDefault(); sendQuery(); });
  input.addEventListener("input", updateComposer);
  input.addEventListener("compositionstart", () => { composing = true; });
  input.addEventListener("compositionend", () => { composing = false; });
  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing || event.keyCode === 229 || composing) return;
    event.preventDefault();
    sendQuery();
  });

  byId("btnStop").addEventListener("click", () => {
    const task = state.taskId;
    state.request?.abort();
    if (task) fetch("/api/chat/stop", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ task_id: task, user: userId }) }).catch(() => {});
    input.focus();
  });
  byId("btnHistory").addEventListener("click", () => historyModal.showModal());
  byId("btnNav").addEventListener("click", () => {
    selectedGroup = "";
    byId("navSearch").value = "";
    navModal.showModal();
    renderNav(true);
  });
  byId("navSearch").addEventListener("input", () => renderNav());
  byId("btnExport").addEventListener("click", () => {
    if (!state.messages.length) return;
    const content = state.messages.map((row) => `${row.role === "user" ? "提问" : "校园助手"}：${row.text}`).join("\n\n");
    const url = URL.createObjectURL(new Blob([content], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.download = "校园办事对话.txt";
    link.href = url;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 500);
    status("已导出对话");
  });
  for (const dialog of [navModal, sourcePanel, historyModal]) {
    dialog.querySelector("[data-close]").addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  }
  document.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button || button.disabled) return;
    const data = button.dataset;
    if (data.audience) selectAudience(data.audience);
    else if (data.command === "new" && !state.request) {
      historyModal.close();
      activate(null);
      input.focus();
    } else if (data.session && !state.request) {
      const session = readSessions().find((row) => row.id === data.session && row.audience === state.audience);
      if (!session) return;
      historyModal.close();
      activate(session);
      input.focus();
    } else if (data.query && !state.request) {
      if (navModal.open) navModal.close();
      sendQuery(data.query);
    } else if ("group" in data) {
      selectedGroup = data.group;
      renderNav();
    } else if (data.command === "retry-nav") {
      renderNav(true);
    }
  });

  activate(activeSession());
  loadShortcuts();
})();
