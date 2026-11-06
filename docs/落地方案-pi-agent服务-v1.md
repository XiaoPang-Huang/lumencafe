# Pi Agent 服务落地方案

> 版本 v1 · 2026-11-06
> 依据：`docs/选型分析-harness三强对比-v1.md`（Pi 定案）+ Pi 官方一手文档核实（SDK / RPC / containerization / models / extensions / mcp）
> 阶段：步 1–5 已按本文交付（2026-11-07 验收记录见 `开发计划-pi-runner-v1.md`「执行记录」）。

## 1. 形态总览

新增一个服务 **`pi-runner`**：独立 Node 服务，Pi SDK 进程内嵌入，自写约 100 行 HTTP 薄层。跑在**隔离沙箱容器**里。主体 Python 一行不改语言，通过 HTTP 调用它。

```
浏览器/前端 ──→ Python 主体（FastAPI，不变）
                     │  ① HTTP 调 pi-runner
                     ▼
              pi-runner（Node 薄层 + Pi SDK，沙箱容器）
                     │  ② models.json baseUrl 指向网关
                     ▼
              自建网关 /chat/completions ──→ 模型
                     ▲
              结果只写 /output/<run_id>/，主体校验后入库
```

两条通道不变：模型请求走网关（计费熔断路由留主体）；结果走文件目录（沙箱不碰数据库）。

**一处修正**：早前说「沙箱里没有任何密钥」不严谨。Pi 调网关需要一把 key——方案是主体在 `gateway_tokens` 里发一把**专用最小权限 token**（只许 `/chat/completions`，记 `llm_call_logs` 可单独核算 pi-runner 的成本）。这把 token 泄漏了也干不了别的，风险等价于「沙箱无密钥」的原始意图。

## 2. 分步实施（每步可停，符合项目分步指令节奏）

### 步 1 · 最小验证（先证明链路通，不写服务）

目标：容器里跑通 Pi，配 `models.json` 指向自建网关，一次性任务成功。

- 用官方 `Dockerfile.pi`（`node:24-bookworm-slim` + bash/ca-certificates/git/ripgrep + `npm i -g --ignore-scripts @earendil-works/pi-coding-agent`）起容器
- 挂入两份配置（见 §3）：`models.json`（网关地址 + `api: "openai-completions"` + 专用 token）和任务说明
- 验收：一条命令让 Pi 完成「把某 URL 的页面抓下来存成 markdown」，文件出现在挂出的 `/output` 目录

这一步不通过，后面全不做。

### 步 2 · pi-runner 薄层服务

- 技术栈：Node ≥ 22.19.0，Fastify（轻、SSE 支持好），锁 `package-lock`
- 端点（主体只面对这三个）：
  - `POST /api/runs`：body `{ run_id, task }`，`run_id` 由主体生成传入（幂等，薄层无状态）
  - `GET /api/runs/:id/events`：SSE，转发 `session.subscribe()` 的事件流
  - `POST /api/runs/:id/abort`：调 `session.abort()`
- 结果落盘 `/output/<run_id>/`：`result.md` + `events.jsonl`，主体轮询/读取后入库

**一个必须处理的坑**：Pi SDK session **默认不加载**内建 MCP / codemode / tool-search。薄层装配时要显式把 `createMcpExtension()`、`createCodemodeExtension()` 加进 `DefaultResourceLoader.extensionFactories`，并调 `session.bindExtensions()`。漏了这步，MCP 工具对模型不可见，且**不报错**。

### 步 3 · 沙箱收紧

- compose 服务定义：挂 `no-new-privileges`、只读根文件系统、`/output` 单独可写卷
- 资源限额：`mem_limit 1g`、`cpus 1.0`（比早前估的 512m 宽裕，Pi 加浏览器 MCP 后内存会涨，实测后再降）
- 网络：默认档先做到「容器访问不到 PostgreSQL 端口、只能到网关」；收紧档再加出口域名白名单（egress 代理或网关侧只放行 pi-runner 网段）
- `pi-agent-home` 用命名卷，**不挂宿主目录**（官方明示挂宿主会暴露凭据与配置）

### 步 4 · 接 MCP 生态（论文兜底）

按 §3 的 `mcp.json` 逐个接，每个 server 单独锁版本 + 查 CVE：
- `paper-search-mcp`（22 学术源 + OA-First 换源兜底链，key 全可选）
- Playwright MCP（浏览器，反爬场景）
- 官方 Fetch（网页转 Markdown）

接的顺序就是兜底链的顺序：先 paper-search-mcp（覆盖大多数 OA 论文），Playwright 留给反爬和登录墙。MinerU 解析已有自研流水线，不重复接。

### 步 5 · 主体接入

- Python 侧：一个 `pi_client.py` 模块封装三个调用 + 轮询 `/output` 目录
- 长任务挂 Hatchet（已有），pi-runner 只做执行，编排留主体
- 前端展示 SSE 事件流（工具调用、进度），不用 Pi 的 TUI

### 扩展应用的三种姿势（MCP / Skill / Extension）

三者是独立入口，底层都经 ResourceLoader 汇进同一条工具管道，模型只看到一份工具列表：

- **MCP = 配置驱动**：`mcp.json` 一行一个 server（stdio 或 Streamable HTTP），零代码。SDK 装配时的 `createMcpExtension()` + `bindExtensions()` 是**开关动作**（写在薄层里一次），不是插件开发——之后加任何 MCP server 只改配置。
- **Skill = 资源文件**：SKILL.md 按目录放置，ResourceLoader 自动发现、按需加载，零代码。
- **Extension = 单个 TS 文件**：**只有**自定义逻辑才写——注册自有工具、用 `tool_call` 钩子拦截调用做审计/权限。

扩展成本的实际形态：

| 想干什么 | 怎么做 | 写代码吗 |
|---|---|---|
| 接外部工具（paper-search-mcp、Playwright） | `mcp.json` 加一行 | 否 |
| 沉淀方法（遇反爬先试 A 再试 B） | 放一个 SKILL.md | 否 |
| 暴露主体能力（查账、查文献库） | Python 侧写 MCP server，复用现有 service | 是（Python，在主体侧） |
| 拦截调用、记审计、统一权限 | 写一个 TS extension | 是（TS，少而固定） |

附带好处：MCP 是开放协议，给 Pi 写的 MCP server 将来换任何 harness 都能直接用——扩展成果不被 Pi 锁死。

## 3. 关键配置样例（格式以官方文档为准）

**models.json**（挂 `/root/.pi/agent/models.json`）：

```json
{
  "providers": {
    "lumen-gateway": {
      "baseUrl": "http://caddy/gw/v1",
      "api": "openai-completions",
      "apiKey": "$LUMEN_PI_TOKEN",
      "models": [{ "id": "deepseek-chat" }]
    }
  }
}
```

**mcp.json**（挂 `/root/.pi/agent/mcp.json`）：

```json
{
  "mcpServers": {
    "papers": { "command": "uvx", "args": ["--from", "paper-search-mcp@<锁版本>", "paper-search-mcp"] },
    "browser": { "command": "npx", "args": ["@playwright/mcp@<锁版本>"] }
  }
}
```

注意：Pi 的 MCP 只收 stdio 和 Streamable HTTP，**SSE 明确被拒**；工具曝光分 `codemode`（默认）/`deferred`/`direct`/`hidden` 四档，论文工具建议 `deferred`，避免占常驻上下文。

**compose 片段**（骨架）：

```yaml
pi-runner:
  build: ./pi-runner
  networks: [internal]        # 只通网关和主体，不通 DB
  environment:
    - LUMEN_PI_TOKEN=${LUMEN_PI_TOKEN}   # 专用最小权限网关 token
  volumes:
    - pi-output:/output
    - pi-agent-home:/root/.pi/agent
  read_only: true
  security_opt: [no-new-privileges:true]
  mem_limit: 1g
  cpus: 1.0
  restart: unless-stopped
```

## 4. 怎么启服务（启动顺序）

```
# 1. 构建
docker compose build pi-runner

# 2. 起服务
docker compose up -d pi-runner

# 3. 健康检查
curl --noproxy "*" http://127.0.0.1:<端口>/healthz
# 期望 {"ok": true}

# 4. 主体侧发一条真实任务验证
curl --noproxy "*" -X POST http://127.0.0.1:<端口>/api/runs \
  -H "Content-Type: application/json" \
  -d '{"run_id": "smoke-001", "task": "抓取 https://arxiv.org/abs/xxxx 的标题和摘要，写入 /output/smoke-001/result.md"}'

# 5. 看事件流
curl --noproxy "*" http://127.0.0.1:<端口>/api/runs/smoke-001/events

# 6. 主体轮询到 result.md 出现，校验后入库
```

（`<端口>` 由 compose 映射决定，pi-runner 监听容器内 8787，映射到宿主 loopback。）

## 5. 验收链路（每次升级的门槛）

`POST /api/runs` 跑「下载某篇指定 OA 论文到 /output」→ SSE 事件完整 → `result.md` 落盘且内容正确 → 全程只访问了允许域名 → 成本记进 `llm_call_logs` 的 pi-runner 条目。全绿才允许推任何升级。

## 6. 风险与对策

| 风险 | 对策 |
|---|---|
| SDK 不加载内建 MCP（静默失败） | 薄层装配显式 `extensionFactories` + `bindExtensions()`，验收链路里专门验证 MCP 工具可见 |
| 无内建权限系统 | 容器隔离是必做项（步 3），不是靠 Pi 自己 |
| v1.5.0 breaking（校验迁 pi-schema） | 自定义工具按新写法写；升级走 §5 验收 |
| Earendil 路线变化 | 核心 MIT 承诺在手，观望 Fair Source 层是否动核心 |
| MCP 生态供应链（55.8% 无认证等） | 每个 server 锁版本 + 查 CVE；`paper-search-mcp` 绑 `127.0.0.1` |
| Playwright 浏览器内存 | `mem_limit` 先 1g 实测再调；容器内 headless |
