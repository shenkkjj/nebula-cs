"use strict";
(() => {
  const form = document.getElementById("loginForm");
  const error = document.getElementById("loginError");
  const next = new URLSearchParams(location.search).get("next") || "";
  const hint = document.getElementById("roleHint");
  const label = document.getElementById("roleLabel");
  const tabs = [...document.querySelectorAll("[data-role]")];
  const roleInput = form.querySelector('input[name="role"]');

  function selectRole(role) {
    roleInput.value = role === "admin" ? "admin" : "agent";
    for (const tab of tabs) {
      const on = tab.dataset.role === roleInput.value;
      tab.setAttribute("aria-selected", String(on));
      tab.tabIndex = on ? 0 : -1;
    }
    if (roleInput.value === "admin") {
      if (label) label.textContent = "管理员登录";
      if (hint) hint.textContent = "管理员进入后台，维护知识库、审计和评测。";
    } else {
      if (label) label.textContent = "坐席登录";
      if (hint) hint.textContent = "坐席进入值班台，处理待接入的工单。";
    }
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
    error.hidden = true;
    const body = {
      username: form.username.value.trim(),
      password: form.password.value,
      role: roleInput.value,
      next,
    };
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      error.hidden = false;
      error.textContent = data.error || "登录失败";
      return;
    }
    location.href = data.redirect || (data.role === "admin" ? "/admin" : "/agent");
  });
})();
