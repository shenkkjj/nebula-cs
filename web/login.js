"use strict";
(() => {
  const form = document.getElementById("loginForm");
  const error = document.getElementById("loginError");
  const next = new URLSearchParams(location.search).get("next") || "";

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
