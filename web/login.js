"use strict";
(() => {
  const form = document.getElementById("loginForm");
  const error = document.getElementById("loginError");
  const submit = form.querySelector('button[type="submit"]');

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submit.disabled) return;
    error.hidden = true;
    submit.disabled = true;
    submit.textContent = "登录中…";
    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: form.elements.username.value.trim(),
          password: form.elements.password.value,
          role: "admin",
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) {
        location.assign("/admin");
        return;
      }
      error.textContent = data.error || "登录失败，请检查账号和密码。";
    } catch {
      error.textContent = "无法连接服务，请稍后重试。";
    }
    error.hidden = false;
    submit.textContent = "登录";
    submit.disabled = false;
  });
})();
