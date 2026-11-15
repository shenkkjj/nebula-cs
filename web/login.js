"use strict";
(() => {
  const form = document.getElementById("loginForm");
  const error = document.getElementById("loginError");
  const hint = document.getElementById("demoHint");
  const next = new URLSearchParams(location.search).get("next") || "";

  fetch("/api/health")
    .then((res) => res.json())
    .then((data) => {
      if (!hint || !data || !data.demo_accounts) return;
      hint.hidden = false;
      hint.textContent = "本机演示模式已打开。账号写在课程说明里，不会从接口返回。";
    })
    .catch(() => {});

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.hidden = true;
    const body = {
      username: form.username.value.trim(),
      password: form.password.value,
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
