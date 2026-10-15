/* 流光咖啡馆原型 · 共享演示脚本（仅交互演示，无后端依赖） */
(function () {
  "use strict";

  /* 顶栏菜单：开关侧栏抽屉（手机） */
  document.querySelectorAll("[data-open-sider]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var sider = document.querySelector(".sider");
      var mask = document.querySelector(".drawer-mask");
      if (sider) sider.classList.add("open");
      if (mask) mask.classList.add("open");
    });
  });

  /* 会话抽屉（对话页手机） */
  document.querySelectorAll("[data-open-conv]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var panel = document.querySelector(".conv-panel");
      var mask = document.querySelector(".drawer-mask");
      if (panel) panel.classList.add("open");
      if (mask) mask.classList.add("open");
    });
  });

  /* 点击遮罩关闭所有抽屉 */
  document.querySelectorAll(".drawer-mask").forEach(function (mask) {
    mask.addEventListener("click", function () {
      document.querySelectorAll(".sider.open, .conv-panel.open").forEach(function (el) {
        el.classList.remove("open");
      });
      mask.classList.remove("open");
    });
  });

  /* 弹层开合 */
  document.querySelectorAll("[data-modal-open]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var m = document.querySelector(btn.getAttribute("data-modal-open"));
      if (m) m.classList.add("open");
    });
  });
  document.querySelectorAll("[data-modal-close]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var m = btn.closest(".modal-mask");
      if (m) m.classList.remove("open");
    });
  });
  document.querySelectorAll(".modal-mask").forEach(function (mask) {
    mask.addEventListener("click", function (e) {
      if (e.target === mask) mask.classList.remove("open");
    });
  });

  /* toast 提示 */
  var toastTimer = null;
  function toast(text) {
    var t = document.querySelector(".toast");
    if (!t) {
      t = document.createElement("div");
      t.className = "toast";
      document.body.appendChild(t);
    }
    t.textContent = text;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove("show"); }, 2200);
  }
  document.querySelectorAll("[data-toast]").forEach(function (el) {
    el.addEventListener("click", function () { toast(el.getAttribute("data-toast")); });
  });

  /* 记账类型切换（支出/收入） */
  document.querySelectorAll(".seg button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var seg = btn.closest(".seg");
      seg.querySelectorAll("button").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
    });
  });

  /* 分类点选（记账 + 应用中心） */
  document.querySelectorAll(".cat-pick").forEach(function (wrap) {
    wrap.querySelectorAll(".cp").forEach(function (cp) {
      cp.addEventListener("click", function () {
        wrap.querySelectorAll(".cp").forEach(function (c) { c.classList.remove("active"); });
        cp.classList.add("active");
      });
    });
  });

  /* 对话页：假流式输出演示 —— 打字机播完最后一条 assistant 消息 */
  var streamEl = document.querySelector("[data-stream]");
  if (streamEl) {
    var fullText = streamEl.getAttribute("data-stream");
    var dots = streamEl.querySelector(".thinking");
    var textNode = streamEl.querySelector(".stream-text");
    var idx = 0;
    setTimeout(function typeNext() {
      if (dots) { dots.remove(); dots = null; }
      if (idx < fullText.length) {
        /* 每拍吐出 1~3 字，模拟 token 流 */
        var step = 1 + Math.floor(Math.random() * 3);
        textNode.textContent += fullText.slice(idx, idx + step);
        idx += step;
        setTimeout(typeNext, 60);
      } else {
        streamEl.classList.remove("cursor");
      }
    }, 900);
  }

  /* 对话页：输入框高度自适应 + 回车发送（演示） */
  var input = document.querySelector(".composer textarea");
  if (input) {
    input.addEventListener("input", function () {
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 140) + "px";
    });
  }
})();
