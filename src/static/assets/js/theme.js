// 主题启动脚本：必须在首帧绘制前跑（index.html 里同步引入在 CSS 之前），防暗色闪白（FOUC）
// CSP script-src 'self'：本文件同源外链，合法；不读 localStorage 之外的任何东西。
// 规则：localStorage "lc_theme" 优先（用户手选）；未选过则跟随系统 prefers-color-scheme。
"use strict";
(function () {
  var theme = null;
  try { theme = localStorage.getItem("lc_theme"); } catch (e) { /* 隐私模式等场景静默 */ }
  if (theme !== "light" && theme !== "dark") {
    try {
      theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    } catch (e) { theme = "light"; }
  }
  if (theme === "dark") document.documentElement.setAttribute("data-theme", "dark");
  else document.documentElement.removeAttribute("data-theme");
})();
