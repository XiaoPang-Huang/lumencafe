# Octop 组件评估 v1（2026-10-24）

> 调研对象：腾讯云 Octop（自托管多用户多 Agent AI 助手平台）+ 四个拆分组件（harness / memory / browser / gateway）。
> 衔接《生态集成候选-v1.md》§八 的结论：「平台级不碰、四组件当工人单独评估」。本文是逐个的深评。
> 所有事实已对照各仓库 README 原文核实（见文末依据）。

## 〇、结论先放

| 组件 | 结论 |
|---|---|
| Octop 主项目 | ❌ 不碰当底座；设计可抄 |
| octop-harness | ⏸ 暂不引入；触发点到了先走既定 LangGraph 路线 |
| octop-memory | ⏸ 留在候选（与 Mem0 二选一实测）；有新判据 |
| octop-browser | ⏸ 暂不引入；真要浏览器自动化时它是首选 |
| octop-gateway | ⏸ 留在候选；双向 IM 那天直接上它 |

一句话：**现在一个都不用装**。但有 4 个新发现值得记进候选表（见 §三）。

## 一、Octop 是什么

腾讯云开源的「自托管多用户多 Agent AI 助手平台」，MIT 协议。

- 主项目 = 完整产品：Web 控制台、用户/权限、专家库、知识库、定时任务、IM 网关，功能面是本项目的超集。
- 四个组件单独开源、单独上 PyPI，官方明说「只拿你需要的那一块」。
- 成熟度：主项目 1.0.2b6（beta）；组件 1.0.x。2026 年 10 月刚开源，接口还会动。

## 二、逐个评估

### 1. Octop 主项目（平台级）→ 不碰

**优点**：开箱即用的控制面（用户、权限、额度、专家、知识库、IM）；一条命令部署；多用户记忆隔离。

**缺点 / 风险**：自带 Web 控制台和用户体系，和我们的 FastAPI + Postgres 产品主权直接冲突；两套账号两套权限；beta 版 API 不稳；上了它我们产品就没个性了。

**与本项目的适配与冲突**：功能重叠是全量重叠（对话/记账/文献/模型管理它都有对应物）。这与《生态集成候选-v1.md》§八「产品重叠 + 主权重叠」的判断一致，维持原判。

**推荐**：❌ 不作为底座、不部署。但它的设计思路对我们有参考价值，见 §四。

### 2. octop-harness（Agent 运行时库）→ 暂不引入

**它是什么**：把 LangChain 团队的 deepagents 封装成可部署的 Agent 运行时。是库不是服务。图运行时用 LangGraph + SQLite checkpoint。

**优点**：
- 模型路由（ChatModelFactory）：OpenAI / Anthropic / Bedrock + 17 个国产预设，支持 OpenAI 兼容 base_url；
- 多 Agent 注册表 + Teams 互派活；工作区可换（本地 / S3 / COS / Postgres）；
- 安全护栏开箱：工具护栏、文件系统权限、PII 脱敏（内置大陆手机号 / 身份证识别清单）；
- LangGraph 派活栈和我们的首选路线（生态集成候选 §四）同源。

**缺点 / 风险**：
- 会把 deepagents / LangChain 整棵依赖树拉进后端，我们现在的 FastAPI 后端是很干净的轻依赖；
- 它自带模型路由，和我们「模型管理 = 纯网关」的主权决策是第二套路由（虽然它的 base_url 可以指向我们 `/gw/v1`，Key 仍留在网关，但模型注册表会重复一份）；
- 3 个月大，主项目还在 beta，接口变动是常态；
- 依赖树对 Python 3.14 的兼容未验证（我们 Dockerfile 用 `python:3.14-slim`，它标称 3.12+）。

**与本项目的适配与冲突**：我们的对话现在只是 SSE 单轮流（架构设计 §5.2），多步任务 / 工具调用的需求还没立项。冲突点主要是模型路由重叠（可用 base_url 指向网关缓解）和依赖树增重。

**推荐**：⏸ 暂不引入。触发点分两级——
- 对话要多步任务/工具调用 → 仍按既定路线先用 **LangGraph 库级**自己拼（轻、可控）；
- 需求升级到「多 Agent 互相派活 / 被 IDE 经 ACP 驱动 / 要开箱 PII 脱敏」→ 再评估 harness。

### 3. octop-memory（记忆库）→ 留在候选，与 Mem0 二选一

**它是什么**：Agent 长期记忆库，纯标准库 + SQLite/FTS5 起步（零核心依赖），可选 Postgres。是库（Python API / CLI / JSON-RPC），可进程内嵌。

**优点**：
- 分层蒸馏：原始事件 → 事实卡（AtomCard）→ 实体页，树状组织，召回按 token 预算裁剪；
- **零核心依赖**，进程内嵌符合我们「库级随便复用」的口诀，不加容器；
- 支持 PostgreSQL（独立 schema + namespace 隔离），和我们业务库可共存；
- **附赠 LangGraph checkpointer（SQLite/PG 可选）**——正好接我们 LangGraph 首选路线；
- 记忆可打包迁移（.hmpkg），「记忆是资产」。

**缺点 / 风险**：
- **向量搜索是 mock、默认关闭（README 原文承认 Chroma/Qdrant 集成未验证）**——主打词法检索（FTS5），和我们「pgvector 摘要级」基线是两条路线；
- 自动蒸馏要注入 LLMClient（可指向我们网关，但多一层接线）；
- 3.14 兼容未实测；数据落自己的 schema，和「业务数据进业务表」的直觉有摩擦。

**与本项目的适配与冲突**：《生态集成候选-v1.md》§三 已定「Mem0 首选，octop-memory 小规模实测二选一」。本次核实给出二选一的新判据：

- 检索最终走向量（pgvector 统一检索）→ **Mem0** 更顺（可挂 pgvector）；
- 要零依赖、词法召回、顺带拿 LangGraph checkpoint → **octop-memory** 更顺。

**推荐**：⏸ 维持候选不动。触发点 = 对话需要跨会话个性化记忆（第二批之后）。届时实测比四件事：召回质量、和对话注入点的衔接成本、Python 3.14 兼容、Postgres 下与业务库共存表现。

### 4. octop-browser（浏览器自动化库）→ 暂不引入

**它是什么**：CDP 直连 Chromium 的浏览器自动化（运行时不依赖 Playwright），带 MCP server。

**优点**：元素 ref 定位稳（页面重排不点空）；轻量 DOM 输出省 token；登录态 profile 持久；录一遍回放（record & replay）；约 20 个 action 兼 CLI；自带 MCP server，任何支持 MCP 的 Agent 直接接。

**缺点 / 风险**：要拉 Chromium 二进制（几百 MB）；我们目前没有浏览器场景（arXiv 抓取走 HTTP API 就够，见生态集成候选 §六）。

**与本项目的适配与冲突**：当前无冲突也无需求。它的 MCP server 和我们未来的 MCP 注入点天然咬合，这是它最大的长期价值。

**推荐**：⏸ 暂不引入。触发点 = 出现「需要 JS 渲染 / 登录态」的采集、剪藏需求（届时对照 Karakeep 候选）、或给对话 Agent 开「操作网页」工具。到那天它是首选。

### 5. octop-gateway（IM 桥库）→ 留在候选

**它是什么**：10 个 IM 平台一套消息抽象（飞书 / 钉钉 / QQ / 企微 / 微信 iLink / 元宝 / 小艺 / MQTT / Telegram / Discord）。**是纯 asyncio 的库，跑在你自己的进程里**，不是独立服务。

**优点**：
- 写一个异步处理器，所有平台通用；token 流式输出（DELTA）是一等公民；
- 主动推送（push_text / push_to_all）也内置——单向通知场景它也能干；
- 限流 / 超时 / typing / 附件存储（MediaBackend）全内置；多租户隔离；群会话策略可配；
- 自定义平台继承 BaseChannel 即可复用整条管线；库级嵌入 = 不占机器预算的容器配额。

**缺点 / 风险**：长连接（WebSocket / 长轮询）跑在宿主进程里，和 FastAPI 同进程要自己管好生命周期（或单开一个小进程）；平台凭据申请是它省不掉的活；同样 3.12+ 标称、3.14 未实测。

**与本项目的适配与冲突**：《生态集成候选-v1.md》§五 已列它为「双向 IM 时的候选」。本次核实的新信息是：它其实是**库**不是服务，比原表里「服务」的定级更轻，机器预算友好。无主权重叠（它只管消息通道，Agent 逻辑仍是我们的）。

**推荐**：⏸ 维持候选。触发点 = 需要双向 IM（在 IM 里发指令给助手）。届时直接上它，省掉逐平台写 webhook。若只是单向推送（论文更新提醒），ntfy 仍然最轻；但若迟早要双向，可以跳过 ntfy 直接攒到 gateway。

## 三、相对既有候选表的 4 个新发现

1. **octop-memory 附赠 LangGraph checkpointer（SQLite/PG）**——和我们 LangGraph 首选路线咬合，是它相对 Mem0 的加分项。
2. **octop-memory 向量搜索确认是 mock / 默认关闭**（README 原文）——「和 Mem0 二选一」的判据由此明确：走向量选 Mem0，走词法选它。
3. **octop-gateway 是进程内库而非独立服务**——按三层复用模型它更靠近「库级」，机器预算比原估计友好。
4. **harness 的模型路由支持 OpenAI 兼容 base_url**——将来若用它，模型 Key 仍可全部留在我们网关，「路由重叠」的冲突是可控的。

## 四、可借鉴的设计（不装代码，抄思路）

- **专家沙箱**：Agent 运行环境默认不信任、读写限定工作区 → Skill 中心执行第三方技能时的安全边界照此画。
- **权限 + 额度**：页面/功能级 ACL + Token 额度限制 → 我们 gateway_tokens 表可以加额度字段，网关计量收费的底子。
- **知识库 llm-wiki 思路**（Karpathy）：把原始资料持续编译成互相链接的 Markdown Wiki → papers 文献库从「摘要列表」走向「知识沉淀」的远期形态。
- **PII 脱敏清单**：大陆手机号（13-19 段）+ 18 位身份证校验规则可以直接抄进我们对话日志脱敏。
- **记忆即资产**（.hmpkg 可迁移）：设计记忆表时预留导出/导入，换模型换机器不清零。

## 五、下一步

1. **请拍板**本文各条结论；拍板后按《生态集成候选-v1.md》的维护约定，把「决策日期 + 结论」补进对应行。
2. 记忆二选一实测**不急**，等对话跨会话记忆需求立项再动。
3. 若想提前热身，10 分钟可做：在 3.14 的 venv 里 `pip install octop-memory` 跑 Quick start，验证 3.14 兼容 + 词法召回手感。
4. 涉及界面的部分（Skill 中心安全边界、额度管理）动工前按 AGENTS.md §一先查参考案例。

## 依据（均已逐条核实）

- 主项目：github.com/TencentCloud/Octop ｜ 官网 octop.cloud
- octop-harness：github.com/TencentCloud/octop-harness（README：库定位、ChatModelFactory、SecurityPolicy、ACP）
- octop-memory：github.com/TencentCloud/octop-memory（README：零依赖、FTS5、向量 mock 声明、Postgres、LangGraph checkpointer）
- octop-browser：github.com/TencentCloud/octop-browser
- octop-gateway：github.com/TencentCloud/octop-gateway（README：10 平台、BaseChannel、push、群会话策略）
- 本项目内部：`docs/生态集成候选-v1.md`（三层复用模型 + 各触发点）、`docs/架构定稿-v1.md`（模型管理 = 纯网关）、`backend/Dockerfile`（python:3.14-slim）

---

*维护约定：拍板后回写 `生态集成候选-v1.md`；触发点出现时重开本文档更新结论。*
