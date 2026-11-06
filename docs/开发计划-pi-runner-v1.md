# pi-runner 开发计划

> 版本 v1 · 2026-11-06
> 依据：`docs/选型分析-harness三强对比-v1.md`（选型定案）+ `docs/落地方案-pi-agent服务-v1.md`（落地方案）
> 节奏：本会话出「计划 + 单步指令」→ 用户另开新会话执行一步 → 反馈后给下一步指令（沿用 2026-10-25 定的分步指令制）。每步开工 = 把对应步的章节当指令给开发会话。

## 0. 总览

| 步 | 名称 | 产出 | 验收 | 依赖 |
|---|---|---|---|---|
| 1 | 最小验证 | pi 容器 + `models.json` 指向网关 | 一条命令抓网页成功落盘 | 网关发专用 token |
| 2 | pi-runner 薄层 | Node 服务三端点（runs / events / abort） | curl 走通 smoke 任务 | 步 1 |
| 3 | 沙箱收紧 | compose 服务定义（只读/限额/内网） | 容器内够不到 DB、根只读生效 | 步 2 |
| 4 | MCP 接入 | `mcp.json` 接 paper-search-mcp → Playwright | 验收链路升级为「下载 OA 论文」 | 步 2（可与步 3 并行） |
| 5 | 主体接入 | `pi_client.py` + Hatchet 包装 + API 端点 | 主体发任务→事件→入库闭环 | 步 3、4 |
| 6+ | 应用扩展（随需求） | 记账/对话工具 MCP server、SKILL.md 沉淀 | 逐应用验收 | 步 5 |

步 1–5 是落地线，每步体量都不大（两人项目可承受）。步 6 起按需求驱动，不提前做。

## 2026-11-07 执行记录

步 1–5 已交付并验收：

- 步 1：Pi 容器经 `LUMEN_PI_TOKEN` 走 `/gw/v1` 抓取 example.com，成功写出中文 markdown 摘要。
- 步 2：`pi-runner/` 三端点走通；POST 建 run、SSE 收事件、POST abort 均验证。
- 步 3：沙箱验证通过——容器内 `/app` 只读、`db:5432` 不可达、`api:8000` 可达。
- 步 4：验收链路升级为「下载 OA 论文」；`paper-search-mcp@0.1.4` 成功下载 arXiv 1706.03762 PDF；`@playwright/mcp@0.0.84` 成功访问 example.com（镜像内补 chromium-1252→1254 兼容软链 + XDG/PLAYWRIGHT_BROWSERS_PATH 修正）。
- 步 5：主体闭环通过——临时用户 POST `/agent/runs` → Hatchet `pi-run` → pi-runner SSE（3127 events / 34 tool events）→ `result.md + 1706.03762.pdf` 入对象存储；`llm_call_logs` 按网关 token 名 `pi-runner（专用）` 记录 deepseek-flash token。

工程实现要点：`pi_runs` 表（Alembic 0015）落状态/产物键；`services/pi_client.py + pi_runner.py`；`routers/agent.py` 提供创建/查询/SSE 代理/abort；前端 `modal-agent` 中央弹窗展示事件流。Hatchet 事件输入模型必须固定注解（SDK 不识别变量注解，曾导致 EmptyModel AttributeError）。

## 步 1 · 最小验证

干什么：证明「Pi 容器 + 自建网关」这条链路通，不写服务。

- 前置：网关中为 pi-runner 造专用最小权限 token（只许 `/chat/completions`，成本可单独核算）
- 写 `deploy/pi/Dockerfile`（以官方 `Dockerfile.pi` 为基础）+ `models.json`（`baseUrl` 指向网关、`api: "openai-completions"`、apiKey 用 `$LUMEN_PI_TOKEN` 环境变量插值）
- 验收：容器里一条命令（print/JSON 模式）完成「抓取某 URL 存成 markdown」，文件出现在挂出的 `/output`

**不过此步，后面全停。**

## 步 2 · pi-runner 薄层

干什么：把步 1 的一次性命令包成常驻服务。

- 新建 `pi-runner/`：`package.json`（锁版本，`pi-coding-agent@1.5.0`、Node ≥ 22.19.0、Fastify）+ `server.js` + Dockerfile
- 三端点：`POST /api/runs`（body 含主体生成的 `run_id`，幂等）、`GET /api/runs/:id/events`（SSE 转发 `session.subscribe`）、`POST /api/runs/:id/abort`
- **必做装配**：`DefaultResourceLoader.extensionFactories` 注入 `createMcpExtension()` / `createCodemodeExtension()`，然后 `session.bindExtensions()`——漏了 MCP 工具对模型不可见且不报错
- 结果写 `/output/<run_id>/`（result.md + events.jsonl）
- 验收：curl 三端点 + smoke 任务全程走 HTTP 成功

## 步 3 · 沙箱收紧

干什么：让步 2 的服务具备生产边界。

- compose 服务：`read_only: true`、`no-new-privileges:true`、命名卷 `pi-agent-home`（不挂宿主）、`pi-output` 卷、`internal` 网络（通网关和主体、不通 PostgreSQL）、`mem_limit 1g`、`cpus 1.0`
- 验收：容器内访问 DB 端口失败；根文件系统只读；网关可达

## 步 4 · MCP 接入

干什么：接上论文兜底的现成轮子，每个 server 锁版本 + 查 CVE。

- 先 `paper-search-mcp`（22 学术源 + OA-First 换源兜底链，key 全可选，绑 127.0.0.1）
- 再 Playwright MCP（反爬/登录墙），容器内 headless
- **验收链路升级**：从「抓网页」换成「下载某篇指定 OA 论文到 /output」，此后它就是每次升级的门槛
- 注意：Pi 的 MCP 不收 SSE；论文工具 `exposure` 用 `deferred` 不占常驻上下文

## 步 5 · 主体接入

干什么：Python 主体正式获得「派任务给 agent」的能力。

- `backend/app/services/pi_client.py`：封装三端点调用 + 轮询 `/output`
- Hatchet 包装长任务（编排留主体，pi-runner 只执行）
- 最小 API 端点 + 前端事件流展示（设计参照既定业界案例，遵守 AGENTS.md 设计强制规则）
- 验收：主体发「下载论文」任务 → SSE 事件完整 → result.md 入库 → 成本记在 pi-runner 名下

## 步 6+ · 应用扩展（随需求，不提前做）

- 记账/对话工具：Python 侧写 MCP server 复用现有 service，`mcp.json` 加一行（见落地方案「扩展应用的三种姿势」）
- 方法沉淀：SKILL.md 放 `skills/` 体系，Pi 侧按目录加载
- 拦截/审计：TS extension 一个文件，`tool_call` 钩子

## 升级纪律（全程适用）

锁版本 → 看 Pi release notes → 升一个 minor → 跑验收链路（步 4 起为「下载 OA 论文」）→ 全绿才推。pi-runner 的 Node 依赖同样走 lockfile（对齐 backend 的 requirements 锁定机制）。

## 与主线计划的关系

本计划是独立新线，不影响既有主线（供应链基建 → 三小件 → 网关路由 → 备份 → 监控 → Hatchet）。pi-runner 的 Hatchet 包装（步 5）复用主线已交付的 Hatchet 基建。
