// 对话页 vendor 打包：markdown-it + highlight.js 打成一个 IIFE（src/static/assets/vendor/）
// 跑法：node tools/build-vendor.mjs；lockfile 里的 esbuild 负责打包，不产生新依赖
import * as esbuild from "esbuild";
import fs from "node:fs";

fs.mkdirSync("src/static/assets/vendor", { recursive: true });

const entry = `
import MarkdownIt from "markdown-it";
import hljs from "highlight.js/lib/common";
export { MarkdownIt, hljs };
`;
fs.writeFileSync("qa_tmp/vendor-entry.mjs", entry);

await esbuild.build({
  entryPoints: ["qa_tmp/vendor-entry.mjs"],
  bundle: true,
  format: "iife",
  globalName: "LCVendor",
  minify: true,
  outfile: "src/static/assets/vendor/chat-vendor.js",
  logLevel: "info",
});

fs.rmSync("qa_tmp/vendor-entry.mjs");
console.log("OK: src/static/assets/vendor/chat-vendor.js");
