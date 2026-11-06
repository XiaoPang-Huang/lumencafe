# Harness 选型分析：OpenCode / Pi / Google ADK 三强对比

> 版本 v1 · 2026-11-06
> 修订（同日）：用户拍板「后续要升级」为硬约束。推荐排序从 OpenCode ＞ Pi ＞ ADK **改为 Pi ＞ OpenCode ＞ ADK**；新增 §2.7「可升级性」专节；§4 结论、§5 落位方案、§6 风险登记同步改写。
> 性质：选型对比与适应性分析（只读调研产出，未做任何测试或开发动作）
> 依据：四路联网核实（官方文档/仓库/LICENSE/PyPI/CVE 记录 + 第三方来源），关键事实均附出处见会话记录
> 适用前提：流光咖啡馆（Python FastAPI + 自研 OpenAI 兼容网关 /chat/completions + PostgreSQL + docker compose + Caddy + 纯 IP）

## 0. 用户的选型约束（分析基准）

1. harness 是「一个功能/能力」的提供者，**不是整个底座**；可围绕它再起其他服务
2. 不用它自带的 Web UI；自己开发前端，**只接入它的能力**
3. 可接受全部重构，TypeScript 在 Docker 起服务暴露接口也可以
4. 模型请求必须能指向**自建的 /chat/completions 网关**（计费、熔断、路由不能丢）
5. 后续要**扩展其他应用**（记账 / 对话 / 论文 / 更多），新增能力成本要低
6. 出发点：论文检索/下载长尾场景，**agent 自己试错**，skill / MCP 做兜底，不自己写流水线
7. 供应链纪律：锁精确版本 + 哈希、禁 latest、无未修高危 CVE、升级要影响面评估
8. 选定后才考虑高性能实现
9. **后续要持续升级**（用户 2026-11-06 明确）：选型必须把「升级代价」当一等维度，不接受「钉死一个版本不再动」的方案

## 1. 三者各自是什么（定位差异）

三者不是同一类东西，先看清各自回答什么问题：

- **OpenCode** = 服务化的完整 harness。回答「怎么拿到一个现成的、能被外部程序调用的 agent 服务」。
- **Pi** = 嵌入式 agent 内核。回答「怎么拿到最干净、最省 token 的 agent 循环」。
- **Google ADK** = agent 开发框架。回答「怎么把 skill / MCP / 多应用扩展管起来」。

## 2. 逐项事实对比

### 2.1 接入形态（能否不开自带 UI 被外部调用）

| 维度 | OpenCode | Pi | Google ADK |
|---|---|---|---|
| 官方程序化入口 | `opencode serve` 无头 HTTP | Node SDK 进程内 / `pi --mode rpc` JSONL | `adk api_server` REST/SSE/WS + `get_fast_api_app()` 嵌 FastAPI |
| 接口规约 | OpenAPI 3.1（`/doc`），官方 SDK 客户端 | 无 HTTP；SDK 类型即契约 | FastAPI 自动文档 |
| 官方容器 | GHCR `ghcr.io/anomalyco/opencode:2.2.5` | 无官方镜像，官方 `Dockerfile.pi` 自建 | 无（库型，跑在自己进程里） |
| 自带认证 | `OPENCODE_SERVER_PASSWORD` Basic | 无（靠部署隔离） | **api_server 默认无认证**，官方明示生产需自加 |

结论：OpenCode 的「服务边界」是现成的；Pi 要自己包约 100 行 HTTP；ADK 对 Python 主体零侵入（直接嵌进现有 FastAPI）。

### 2.2 自建网关兼容（/chat/completions）

三家都能指向自建网关，但姿势不同：

- **OpenCode**：`@ai-sdk/openai-compatible` + `options.baseURL`，75+ providers，文档示例最完整。
- **Pi**：`models.json` 配 `baseUrl` + `api: "openai-completions"`，支持环境变量插值、支持 Ollama/vLLM/lmstudio 等兼容端点。
- **Google ADK**：经 LiteLLM / OpenAI 兼容 provider 接入，官方路径偏 GCP（Vertex），非 Gemini 模型要绕一层。

### 2.3 扩展机制（新增一个应用能力要写什么）

- **OpenCode**：三条路——插件（`.opencode/plugins/` 或 npm 包，导出 hooks）、MCP（local/remote，支持 `POST /mcp` 动态添加）、skills（`.opencode/skills/<id>/SKILL.md`）。全是 TypeScript。
- **Pi**：最轻——单个 TS 文件放 `extensions/`，`registerTool` / `registerCommand` / 事件钩子，`tool_call` 钩子可拦截调用；MCP 走 `mcp.json`（stdio 或 Streamable HTTP，**SSE 明确被拒**），工具曝光分 codemode/deferred/direct/hidden 四档。注意：SDK session 默认**不加载**内建 MCP/codemote，要显式 `createMcpExtension()` + `bindExtensions()`。
- **Google ADK**：最强原生——`SkillToolset` 自动生成 `list_skills`(L1) / `load_skill`(L2) / `load_skill_resource`(L3) / `run_skill_script`，遵循 Agent Skills 开放标准的渐进披露，甚至支持运行时自写 skill（skill factory）；MCP **双向**（`McpToolset` 消费 + `to_mcp_server` 把自身暴露出去）。

### 2.4 论文长尾试错能力（bash / 浏览器 / 换源 / 解析重试）

这是选型的核心痛点：

- **OpenCode**：强。bash、webfetch、websearch 内置，MCP 可接 Playwright/浏览器；逐工具权限可控。
- **Pi**：强。4 个工具（read/write/edit/bash）+ MCP；极简意味着模型自由度高。
- **Google ADK**：**弱**。默认没有 shell / 文件系统工具，agent 拿不到自由执行能力；内置 code execution 偏 GCP 沙箱形态。做「下载失败换源再试」需要自建工具链。

### 2.5 安全与沙箱

- **OpenCode**：`permission` 规则（allow/ask/deny 按工具、通配符、auto 模式）是**审批策略层**，不是 OS 隔离；官方文档查不到网络出口白名单。`CVE-2026-22812`（High 8.8，<1.0.216 自动启动无认证 HTTP server 可执行任意 shell，已修）——**必须钉 ≥1.0.216**。
- **Pi**：README 明示**没有内建权限系统**，以启动者权限运行，隔离交给容器/微 VM（官方 containerization 文档给了 Docker/SBX/OpenShell/Gondolin 四种）。CVE 四个（54328 High 7.3 等，均修于 0.78/0.79），v1.5.0 又修了一批（glob DoS、非 http(s) OAuth 回调等）。
- **Google ADK**：`McpToolset` 官方最佳实践强制 `tool_filter` + 显式超时；GCP 侧有 Semantic Governance Policy 拦 skill 生命周期调用。但 api_server 默认无认证是硬缺口。

**共同结论**：三者没有一个是「开箱安全」，隔离沙箱 + 网络出口限制 + 结果校验是绕不开的自建项（与早前架构结论一致）。

### 2.6 版本 / 治理 / 供应链

| 维度 | OpenCode | Pi | Google ADK |
|---|---|---|---|
| License | MIT | MIT（作者承诺永久 MIT） | Apache-2.0 |
| 当前版本 | V1 1.19.5（文档全）/ V2 2.2.5（破坏性变更） | v1.5.0 正式（2026-11-02） | v2.11.0（2026-10-02） |
| 稳定性声明 | V2 server API 官方明列 breaking；V2 serve 文档页 404 | v1.x 正式版，但 v1.5.0 自身带 breaking（校验迁 pi-schema） | 约每两周一发版；2.0 有 breaking |
| 治理变动 | 仓库 sst → anomalyco | **已被 Earendil 收购**（2026-04），商标归公司，未来有 Fair Source/商业层 | Google 维护，治理最稳 |
| 依赖体量 | — | npm 包 + Node≥22.19.0 | 48 包 / 104MB |

### 2.7 可升级性（用户拍板的一等维度）

**升级痛苦 = 依赖的接口面 × 破坏性变更次数。** 发版频繁 ≠ 升级痛苦，关键看每次升级要动多少自己的代码。

| 维度 | OpenCode | Pi | Google ADK |
|---|---|---|---|
| 你依赖的接口面 | 宽：HTTP 契约 + 插件 API + 一堆配置键 | **窄：SDK 几个函数 + `models.json` 一行** | 中：嵌进 FastAPI 的框架 API |
| 已发生的 breaking | V1→V2 官方明列重写（server API / 插件 API / 配置键全换） | v1.5.0 一次（工具参数校验迁 `pi-schema`） | 2.0 一次 |
| 升级路径 | 钉 V1 = 放弃升级；升 V2 = 重写集成 | 锁 minor → 看 release notes → 升一级 → 跑验收链路 | 约每两周一发版，评估是常态 |
| 模块可拆 | 否（整体 CLI） | **是**（`pi-agent-core` / `pi-ai` / `pi-mcp` 单独升） | 部分 |
| License 稳定性 | MIT | **MIT，作者承诺永久（"MIT, forever"）** | Apache-2.0 |

结论：**要后续升级，选接口面最窄的 Pi**。OpenCode 的 V1/V2 分裂意味着「升级即重写」，与硬约束 9 直接冲突。

## 3. 适应性分析（对项目逐维度打分）

| 维度 | OpenCode | Pi | Google ADK |
|---|---|---|---|
| 服务边界 / 自研前端 | ★★★（现成） | ★★（自包薄层） | ★★★（嵌 FastAPI 零侵入） |
| 论文长尾试错 | ★★★ | ★★★ | ★（需自建工具链） |
| skill / MCP 兜底 | ★★（有，非渐进披露原生） | ★★（lazy skills） | ★★★（SkillToolset 原生 L1/L2/L3 + 双向） |
| 自建网关兼容 | ★★★ | ★★★ | ★★（偏 GCP） |
| 扩展其他应用 | ★★★（三机制） | ★★★（单文件最轻） | ★★★（tool/skill/MCP） |
| 供应链纪律契合 | ★★（钉版本 + 跟 V2） | ★★★（单 npm 包 + 锁版本即可） | ★★★（Apache-2.0 + 大厂） |
| **可升级性（硬约束）** | ★（V1/V2 分裂，升级即重写） | ★★★（接口面最窄，模块可拆） | ★★（节奏快，2.0 已 breaking） |
| 沙箱/权限现成度 | ★★（审批层） | ★（无内建，靠容器） | ★★（tool_filter，server 无认证） |

## 4. 结论与推荐

**推荐排序：Pi ＞ OpenCode ＞ Google ADK**（承担「论文试错」功能 + 后续持续升级，双约束下的结论）。

1. **Pi（主选，用户已倾向）**：决定性理由是**可升级性**——接口面最窄（SDK 几个函数 + 一行 `models.json`），模块可拆（`pi-agent-core` / `pi-ai` / `pi-mcp` 单独升级），v1.5.0 是正式版，MIT 作者承诺永久。发版快但每次升级要改的代码少；配合锁版本 + 验收链路，升级是日常小事而不是重写。叠加既有优势：token 最省（4 工具极简，短任务实测比 Codex 省约 5 倍）、扩展最轻（单个 TS 文件）、lazy skills 对应「skill 兜底」诉求。
2. **OpenCode（第一备选）**：服务边界现成、试错能力完整，曾经是主选。降为备选的唯一原因：V1/V2 分裂使「后续升级」等于「重写集成」，违背硬约束 9。若未来 OpenCode 收敛到单一稳定 API，可重新评估。
3. **Google ADK（第三）**：skill/MCP 运行时最专业，但默认无自由执行能力，撑不起论文下载试错；且嵌入框架的升级评估是常态负担。定位不变：未来在 Python 主体里管 skill 生态的候选。

**一个反直觉的观察**：三强各回答一个问题（内核 / 服务化 / skill 治理）。若未来真走到「Pi 做执行 + 主体里嵌 ADK 管 skill」的组合，并不冲突——但那是后话，现在单选 Pi。

## 5. 选定后必须做的事（Pi 落位方案）

**形态**：Pi 嵌进一个独立 Node 服务（Pi 官方 `Dockerfile.pi` 为基础镜像），自写约 100 行 HTTP 薄层（Fastify/Hono/Express 均可），把 `session.prompt()` / `session.subscribe()` / `abort()` 暴露成端点，给 Python 主体调用。主体 Python 一行不改语言。

**两条通道（与早前架构结论一致）**：
1. `models.json` 配 `baseUrl` 指向自建 `/chat/completions` 网关——计费、熔断、路由全留在主体侧，沙箱里没有任何密钥
2. 试错结果只写指定目录，主体校验后才入库——沙箱不碰数据库

**必做项**：
1. 隔离沙箱容器：无密钥、限定出口域名（论文源 + 网关）、资源限额、`pi-agent-home` 不挂宿主
2. 锁版本：`package-lock` 钉精确版本 + 容器镜像钉 tag，禁 latest；当前基线 `pi-coding-agent@1.5.0`、Node ≥ 22.19.0
3. SDK session 默认不加载内建 MCP/codemode，要显式 `createMcpExtension()` + `bindExtensions()`——薄层里做掉
4. MCP 供应链：每个 server 单独锁版本 + 查 CVE（生态 55.8% 无认证、62.4% 契约变更不升版本号）

**升级节奏**（对应硬约束 9）：锁版本 → 看 release notes → 升一个 minor → 跑验收链路（「下载某篇指定论文到目录」一条）→ 全绿才推。验收链路通过前不升。

## 6. 风险登记

**Pi（主选）**：
- v1.5.0 自带 breaking：工具参数校验迁到 `@earendil-works/pi-schema`，自定义工具写法要跟着改（只在写了自定义工具时发生，release notes 写明改法）
- Earendil 收购后的路线：作者承诺 MIT 核心层永久，但未来有 Fair Source 增值层与商业层，需持续观察
- 发版频繁（v1.0 于 2026-10-01，一个多月到 1.5.0）：必须建立「锁版本 → 评估 → 验收」的固定节奏，不然会被拖着走
- 无内建权限系统：容器隔离是必做项，不是可选优化

**OpenCode（备选）**：V2 迁移即重写集成；官方 Docker 部署文档 404，compose 要自己写；若选它必须接受「钉 V1 = 放弃升级」或「升 V2 = 重写」二选一。

**Google ADK（第三）**：若 2.x 再出 breaking，嵌进主体的升级成本；GCP 默认导向带来的配置噪音；api_server 默认无认证。
