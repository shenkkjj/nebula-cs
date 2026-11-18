"use strict";
(() => {
  const form = document.getElementById("loginForm");
  const error = document.getElementById("loginError");
  const next = new URLSearchParams(location.search).get("next") || "";
  const submit = document.getElementById("roleLabel");
  const tabs = [...document.querySelectorAll("[data-role]")];
  const roleInput = form.querySelector('input[name="role"]');

  function selectRole(role) {
    roleInput.value = role === "admin" ? "admin" : "agent";
    for (const tab of tabs) {
      const on = tab.dataset.role === roleInput.value;
      tab.setAttribute("aria-selected", String(on));
      tab.tabIndex = on ? 0 : -1;
    }
    const active = tabs.find((tab) => tab.dataset.role === roleInput.value);
    form.setAttribute("aria-labelledby", active.id);
    submit.textContent = roleInput.value === "admin" ? "登录管理后台" : "登录坐席工作台";
    error.hidden = true;
  }

  for (const tab of tabs) {
    tab.addEventListener("click", () => selectRole(tab.dataset.role));
    tab.addEventListener("keydown", (event) => {
      const index = tabs.indexOf(tab);
      const move = { ArrowRight: 1, ArrowLeft: -1, Home: "home", End: "end" }[event.key];
      if (move === undefined) return;
      event.preventDefault();
      const target = move === "home" ? tabs[0] : move === "end" ? tabs[tabs.length - 1] : tabs[(index + move + tabs.length) % tabs.length];
      selectRole(target.dataset.role);
      target.focus();
    });
  }
  selectRole(next.startsWith("/admin") ? "admin" : "agent");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submit.disabled) return;
    error.hidden = true;
    const body = {
      username: form.elements.username.value.trim(),
      password: form.elements.password.value,
      role: roleInput.value,
      next,
    };
    const label = submit.textContent;
    submit.disabled = true;
    submit.textContent = "正在登录…";
    for (const tab of tabs) tab.disabled = true;
    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) {
        location.href = data.redirect || (data.role === "admin" ? "/admin" : "/agent");
        return;
      }
      error.textContent = data.error || "登录失败，请检查账号和密码。";
    } catch {
      error.textContent = "无法连接服务，请稍后重试。";
    }
    error.hidden = false;
    submit.textContent = label;
    submit.disabled = false;
    for (const tab of tabs) tab.disabled = false;
  });
})();
