"use strict";
// 候选原型的演示交互：只在本页内生效，不发网络请求，不保存数据。
(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const SAFE_STATE = /^[\w-]+$/;

  const toastBox = $("#toast");
  const live = $("#live");
  let toastTimer;
  function toast(message) {
    if (!toastBox || !message) return;
    $("#toast-msg").textContent = message;
    toastBox.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastBox.hidden = true; }, 4000);
    if (live) { live.textContent = ""; setTimeout(() => { live.textContent = message; }, 60); }
  }
  $("#toast-close")?.addEventListener("click", () => { toastBox.hidden = true; });

  function selectTab(tab, moveFocus = false) {
    const list = tab.closest('[role="tablist"]');
    for (const item of $$('[role="tab"]', list)) {
      const on = item === tab;
      item.setAttribute("aria-selected", String(on));
      item.tabIndex = on ? 0 : -1;
      const panel = document.getElementById(item.getAttribute("aria-controls"));
      if (panel) panel.hidden = !on;
    }
    if (moveFocus) tab.focus();
  }

  function setCurrent(links, isCurrent) {
    for (const a of links) {
      if (isCurrent(a)) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    }
  }

  // 屏幕切换：#屏幕 或 #屏幕:状态（状态 = 标签的 data-state，或 dialog 的 id）
  let firstRoute = true;
  function route() {
    const [name, state] = location.hash.slice(1).split(":");
    const screens = $$("[data-screen]");
    const match = screens.find((s) => s.dataset.screen === name);
    if (!match && !firstRoute) return; // 「跳到主要内容」这类普通锚点不切屏
    const target = match || screens[0];
    if (!target) return;
    for (const s of screens) s.hidden = s !== target;
    setCurrent($$(".proto-bar a[href^='#']"), (a) => a.getAttribute("href") === `#${target.dataset.screen}`);
    const nav = target.dataset.nav || target.dataset.screen;
    setCurrent($$("[data-nav-link]"), (a) => a.dataset.navLink === nav);
    document.title = `${target.dataset.title || nav} · ${document.body.dataset.option || "候选原型"}`;
    if (state && SAFE_STATE.test(state)) {
      const tab = $(`[role="tab"][data-state="${state}"]`, target);
      if (tab) selectTab(tab);
      const dlg = document.getElementById(state);
      if (dlg instanceof HTMLDialogElement && !dlg.open) dlg.showModal();
    }
    if (!firstRoute) {
      const heading = $("h1", target);
      if (heading) { heading.tabIndex = -1; heading.focus({ preventScroll: true }); }
    }
    firstRoute = false;
  }
  window.addEventListener("hashchange", route);

  let lastOpener = null;
  document.addEventListener("click", (event) => {
    const el = event.target;
    const tab = el.closest('[role="tab"]');
    if (tab) { selectTab(tab); return; }
    const opener = el.closest("[data-open]");
    if (opener) {
      const dlg = document.getElementById(opener.dataset.open);
      if (dlg instanceof HTMLDialogElement) { lastOpener = opener; dlg.showModal(); }
      return;
    }
    const closer = el.closest("[data-close]");
    if (closer) { closer.closest("dialog")?.close(); return; }
    const toggle = el.closest(".row-toggle");
    if (toggle) {
      const open = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", String(open));
      const row = document.getElementById(toggle.getAttribute("aria-controls"));
      if (row) row.hidden = !open;
      return;
    }
    const picker = el.closest("[data-trace]");
    if (picker) {
      const scope = picker.closest("[data-screen]") || document;
      for (const p of $$("[data-trace-panel]", scope)) p.hidden = p.id !== picker.dataset.trace;
      for (const m of $$(".msg", scope)) m.classList.toggle("is-selected", m.contains(picker));
      const traceTab = $('[role="tab"][data-state="trace"]', scope);
      if (traceTab) selectTab(traceTab);
      return;
    }
    const switcher = el.closest("[data-toggle-class]");
    if (switcher) {
      const target = document.querySelector(switcher.dataset.target);
      const on = target ? target.classList.toggle(switcher.dataset.toggleClass) : false;
      switcher.setAttribute("aria-pressed", String(on));
      return;
    }
    const demo = el.closest("[data-toast]");
    if (demo && demo.type !== "submit") {
      if (demo.tagName === "A" && demo.getAttribute("href") === "#") event.preventDefault();
      toast(demo.dataset.toast);
    }
  });

  document.addEventListener("keydown", (event) => {
    const tab = event.target.closest?.('[role="tab"]');
    if (tab) {
      const tabs = $$('[role="tab"]', tab.closest('[role="tablist"]'));
      const i = tabs.indexOf(tab);
      const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[event.key];
      if (next !== undefined) { event.preventDefault(); selectTab(tabs[(next + tabs.length) % tabs.length], true); }
      return;
    }
    const box = event.target.closest?.("textarea[data-enter-submit]");
    if (box && event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      box.form?.requestSubmit();
    }
  });

  function appendReply(form) {
    const thread = document.querySelector(form.dataset.append);
    const text = $("textarea", form)?.value.trim();
    if (!thread || !text) return;
    const msg = document.createElement("div");
    msg.className = "msg agent";
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `${form.dataset.author || "我"} · 刚刚`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    msg.append(meta, bubble);
    thread.append(msg);
    thread.scrollTop = thread.scrollHeight;
  }

  document.addEventListener("submit", (event) => {
    const form = event.target;
    event.preventDefault(); // 原型里的表单一律不提交
    if (!form.matches("[data-demo]")) return;
    for (const field of $$("textarea[required], input[required]:not([type=radio]):not([type=checkbox])", form)) {
      field.setCustomValidity(field.value.trim() ? "" : (field.dataset.msg || "这一项不能为空"));
    }
    if (!form.reportValidity()) return;
    if (form.dataset.append) appendReply(form);
    const status = $(".form-status", form);
    const done = form.dataset.demoDone;
    if (status) {
      status.hidden = false;
      status.textContent = form.dataset.demo;
      status.classList.toggle("pending", Boolean(done));
      if (done) setTimeout(() => { status.textContent = done; status.classList.remove("pending"); }, reduceMotion ? 0 : 1500);
    }
    toast(form.dataset.toast || form.dataset.demo);
    if (form.hasAttribute("data-clear")) for (const f of $$("textarea", form)) f.value = "";
    const dlg = form.closest("dialog");
    if (dlg && !("keepOpen" in form.dataset)) dlg.close();
  });
  document.addEventListener("input", (event) => { event.target.setCustomValidity?.(""); });

  for (const dlg of $$("dialog")) {
    dlg.addEventListener("close", () => {
      for (const form of $$("form", dlg)) {
        form.reset();
        const status = $(".form-status", form);
        if (status) status.hidden = true;
      }
      if (lastOpener?.isConnected) lastOpener.focus();
    });
  }

  route();
})();
