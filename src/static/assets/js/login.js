// 流光咖啡馆 · 登录页 JS（批 1 账号登录）
// 独立公开页：POST /api/auth/login 成功后跳工作台；已登录用户访问直接跳 /
"use strict";

(async function () {
  const form = document.getElementById("loginForm");
  const errBox = document.getElementById("loginError");
  const btn = document.getElementById("loginBtn");
  const inputUser = document.getElementById("loginUser");
  const inputPass = document.getElementById("loginPass");

  const showError = (msg) => {
    errBox.textContent = msg;
    errBox.hidden = false;
  };
  const hideError = () => {
    errBox.hidden = true;
  };

  // 带有效会话访问 /login：直接进工作台（/api/session 匿名 401，不会误跳）
  try {
    const res = await fetch("/api/session", { headers: { Accept: "application/json" } });
    if (res.ok) {
      location.replace("/");
      return;
    }
  } catch {
    // 网络异常时继续展示登录页，由用户提交时再次报错
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    hideError();
    btn.disabled = true;
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          username: inputUser.value.trim(),
          password: inputPass.value,
        }),
      });
      if (res.ok) {
        location.href = "/";
        return;
      }
      let message = "登录失败，请稍后重试";
      try {
        const data = await res.json();
        if (typeof data?.message === "string" && data.message) message = data.message;
        else if (res.status === 401) message = "用户名或密码错误";
        else if (res.status === 429) message = "尝试次数过多，请 5 分钟后再试";
      } catch {
        if (res.status === 401) message = "用户名或密码错误";
        else if (res.status === 429) message = "尝试次数过多，请 5 分钟后再试";
      }
      showError(message);
      btn.disabled = false;
    } catch {
      showError("连不上服务，请确认主程序已启动");
      btn.disabled = false;
    }
  });
})();
