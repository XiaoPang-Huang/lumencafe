# 流光咖啡馆（LumenCafe）产品需求文档 v1.1

> 版本：v1.1（增补 2026-10-15）· 产品经理：许清楚（software-product-manager-2）
> 基准文档：《架构定稿-v1.md》（2026-10-14 定稿）。本文档严格以架构文档为准，冲突处以架构文档为最高优先级。
> 需求来源：旧版 FastAPI 后端（`old/`）业务能力（文献 crawler/LLM provider 抽象/对话 SSE 等）+ 架构文档新增需求。旧接口全部废弃重写，本文档的接口明细即新接口契约。

## 修订记录

| 版本 | 日期 | 修订内容 |
| --- | --- | --- |
| v1 | 2026-10-14 | 初版：覆盖 10 个应用 + 平台层全量需求 |
| v1.1 | 2026-10-14 | 按用户最新决策重排：① 删除打卡、心情、知识库、量表、呼吸急救、统计、自动化中心全部接口与需求条目；② 应用优先级重排——第一批 = 对话应用 + 记账（新增），第二批 = 文献，其余无限期推迟；③ 新增记账应用完整接口；④ 需求池重排为 P0 = 平台层+对话+记账，P1 = 文献；⑤ 前端改为「卡片工作台 + 应用中心」两层架构 |
| v1.1-rev1 | 2026-10-14 | 微调（版本不变）：① Q4 已拍板——「AI 记一笔」（POST /money/parse）本期实施；② 文献抓取调度改为 **n8n 定时触发**，后端提供内部令牌触发接口（取代进程内定时器） |
| v1.1-rev2 | 2026-10-15 | 微调（版本不变）：对话应用由「树洞 + 旅行规划」两个合并为**单一通用对话应用**（app_id=chat，对标 DeepSeek 对话界面）；用户故事、绑定描述、需求池、前端组件描述同步更新 |
| v1.1-rev3 | 2026-10-15 | 范围收敛清理：删除「已移出（无限期推迟）」清单整节、Q3 作废条目、附录已砍应用映射行；全文清除已砍应用残留，文档仅保留平台层 + 对话 + 记账 + 文献 |
| v1.1-rev4 | 2026-10-15 | 删除「应用级绑定」设计：模型管理回归纯网关——Provider CRUD + 调官方 `GET /models` 拉取模型（按 Agent/Token 套餐分组展示）；对话与记账解析统一走网关默认路由；系统提示词改为内置常量；§2.1 G2、§3.2、§3.3、§4.3、§4.6、US-7、P0-3、附录同步 |
| v1.1-rev5 | 2026-10-18 | 模型选择与网关令牌：① Provider 条目 = 厂商 × 套餐平级（`llm_models.plan` 列移除），fetch-models 返回平铺模型列表，支持自定义模型（custom 标记，409 重名）；② `llm_models.meta` 固定 capabilities（vision/files/context_tokens），驱动对话文件上传显隐；③ `/chat` 增加可选 `model_id`（选择值用表 id；绑定会话级 `chat_conversations.model_id`，缺省走默认路由），新增 `GET /chat/models` 用户侧模型池；④ 新增 `gateway_tokens` 表与 `/admin/gateway-tokens*`（对外 `/gw/v1` 鉴权改查表，首个令牌由 `LUMEN_INTERNAL_TOKEN` 种子）；§4.3、§4.6、US-7、P0-3 同步 |
| v1.1-rev6 | 2026-10-21 | 对话思考双流与润色（按《PRD-增量-对话思考与润色-v1.md》v1.1 与《架构设计-增量 v1》实施）：① §4.6 `POST /chat` 请求体增可选 `thinking_level`（R1 白名单内唯一可开放调用参数；会话级快照 `chat_conversations.thinking_level`，不传 = 厂商默认）；② SSE 事件流增 `data: {reasoning_delta}`（思维双流，R3），既有 `{delta}`/`{error}`/`[DONE]` 不变，`chat_messages` 增列 `reasoning`（可空 TEXT）；③ 新增 `POST /chat/polish`（AI 润色，内置 prompt 常量，≤8s，502/429）；④ `GET /chat/models` 每模型增 `reasoning`（`{enabled, levels:[{value,label}], default_level}`，R5）；⑤ 系统提示词注入决策：内置常量在前、用户已安装 skill 片段在后（增量 §7，不占调用参数白名单） |
| v1.1-rev7 | 2026-10-24 | 工作台定位从「应用陈列卡片」改为「**每日看板**」（信息优先，卡片即跳板）：① 首页按应用划分**信息板块**（板块注册表机制：应用有「每天值得一眼的信息」才上板块，配置型应用——平台管理/我的/专家/MCP——不上板；应用增加 = 板块注册表加卡片）；② 整卡即跳板（点击进对应应用），卡头右侧「应用名 →」；③ 两条纪律——**信息纪律**（每板块只放必要信息）与**排序纪律**（保留拖拽排序 lc_home_order，常用在前；板块过多时的折叠/自选本期不做）；④ 页面结构 = 轻问候行（日期 + 时段问候 + 昵称，取消全局指标带）+ bento 板块卡片区（记账小卡 / 论文大卡·新闻流式·mock 先行 / 对话小卡）；⑤ 新增轻量聚合接口 `GET /money/stats/summary` 与 `GET /chat/conversations/summary`（§4.6/§4.7）；⑥ 论文板块本期 mock 数据演示，`api.js` 留 `API.papers.feed()` 占位封装，真接口第二批进程内定时接入 |

| v1.1-rev8 | 2026-10-24 | **移除 n8n**：① 定时任务收回进程内（APScheduler 自研），文献抓取由后端调度器每日触发，`POST /internal/jobs/papers-crawl` 保留为手动/运维触发口（内部令牌鉴权不变）；② 部署形态回到三件套（PostgreSQL / FastAPI / Caddy），compose/覆盖层/.env/部署指南同步清除 n8n；③ 触发点：定时任务增至 5-10 个或需非工程人员改流程时再评估编排平台（见 docs/生态集成候选-v1.md）；④ 文档同步：架构定稿 修订6 / 架构设计 v1.6 / 部署指南 §7 移除 |
---

## 1. 项目信息

| 项 | 值 |
| --- | --- |
| 产品名 | 流光咖啡馆（LumenCafe） |
| 项目代号 | `lumencafe` |
| 产品定位 | 自部署的两人 AI 应用面板；打磨成熟后 MIT 开源 |
| 前端技术栈 | Vite + React + TypeScript + shadcn/ui + Tailwind CSS（一套代码手机/电脑自适应） |
| 后端技术栈 | FastAPI + PostgreSQL（沿用架构文档） |
| 部署形态 | Docker Compose：Caddy + FastAPI + PostgreSQL |
| GitHub 仓库 | `XiaoPang-Huang/lumencafe` |
| 访问方式 | **IP 直连**（2026-10-18 起）：主站 `https://IP:8443` 自签证书。原计划的 `cafe.lumenhub.online` / `api.lumenhub.online` 域名因未备案被腾讯云拦截 80/443 而弃用；域名回归路径（DNS-01 / ICP 备案）见部署指南-v1 §1.1 |

**原始需求复述**：将归档的旧版 FastAPI 后端重写为全新的账号化 AI 应用面板。基础设施（账号/RBAC、模型管理、ChatApp 通用对话件、应用注册表）为所有批次共用；第一批业务应用为对话（单一通用对话应用）与记账（新增），第二批为文献阅读。最终 MIT 开源。

---

## 2. 产品定义

### 2.1 产品目标

| # | 目标 | 衡量标准 |
| --- | --- | --- |
| G1 | 两位使用者拥有统一的个人 AI 应用入口 | 每日看板（信息板块跳板）+ 应用中心数据驱动；第一批应用（对话、记账）上线即可用 |
| G2 | 对话与解析统一走 AI 网关，换模型/换供应商零代码 | 更换对话或记账解析的模型 = 网关层改默认 Provider，对话/解析接口与前端零改动 |
| G3 | 记账可用自然语言快速入账并按月看清收支 | 「AI 记一笔」一句话成账；月度统计覆盖分类汇总 + 近 6 个月趋势 |
| G4 | 开源后其他自部署者可一条 Docker 命令部署并自行扩展 | MIT 发布；README 含部署文档与「如何添加新应用」开发者文档 |

### 2.2 用户画像

| 画像 | 描述 |
| --- | --- |
| 使用者 A / B（当前） | 两位亲密关系使用者，**均为管理员**。使用场景：通用 AI 对话（日常问答、写作辅助、学习解释）、日常记账与月度收支复盘、神经科文献跟踪（AD/PD/ALS/量表）。设备：手机为主、电脑为辅（PWA 体验）。 |
| 自部署者（未来，开源后） | 具备 Docker 部署能力的个人/小团队，拉取仓库后自行配置域名、PostgreSQL、LLM Provider Key。需要注册开关、RBAC、模型管理页开箱可用。 |

### 2.3 用户故事

| # | 用户故事 | 对应应用 | 批次 |
| --- | --- | --- | --- |
| US-1 | 作为使用者，我想与一个通用 AI 助手持续多轮对话、按会话管理历史，以便日常问答与思考梳理 | 对话 | 第一批 |
| US-2 | 作为使用者，我想让 AI 辅助写作（润色、扩写、列提纲）与学习（解释概念、出练习题），以便提升产出效率 | 对话 | 第一批 |
| US-3 | 作为使用者，我想快速记一笔账（金额/收支/分类/备注/日期）并管理自定义分类，以便随手记账 | 记账 | 第一批 |
| US-4 | 作为使用者，我想查看本月按分类汇总的支出、收支合计和近 6 个月趋势，以便掌握财务状况 | 记账 | 第一批 |
| US-5 | 作为使用者，我想用自然语言说一句话就自动生成一条账目草稿，确认后入账，以便极简记账 | 记账（AI 记一笔） | 第一批（已决实施） |
| US-6 | 作为使用者，我想每天看到按我订阅关键词抓到的 PubMed 新文献，能收藏、写笔记、一键 AI 解读（含中文摘要），以便跟踪研究领域 | 文献 | 第二批 |
| US-7 | 作为管理员，我想在管理页配置提供商条目（官方 API / 各套餐）、拉取模型、设定默认路由并管理网关令牌，以便对话界面与外部工具（外部工具）共享池化模型 | 平台管理 | 基础设施 |
| US-8 | 作为自部署者，我想通过 `REGISTRATION_OPEN` 控制注册、通过 RBAC 管理成员，以便两人以上共用实例 | 平台管理 | 基础设施 |

---

## 3. 系统总体架构

### 3.1 分层与组件

```
浏览器（手机/电脑/PWA）
   │ HTTPS
Caddy ── 静态托管 React 构建产物 │ 反代 /api │ SSE 不缓冲
   │
FastAPI ──┬─ 平台层：账号/RBAC、应用注册表、模型管理、用户设置
          ├─ 应用 API：记账、文献
          └─ AI 网关：对话 SSE / 解读 / 结构化解析（DeepSeek/Kimi/OpenAI 兼容端点）
   │
PostgreSQL（user_id 行级隔离）
```

> 定时任务说明：本期后端**进程内定时任务自研**（APScheduler，2026-10-24 起；原 n8n 方案移除）。文献抓取每天早上固定时间由后端调度器直接触发（cron 配置在后端）；同时保留带内部令牌的手动触发接口（见 4.8）。每日备份不做，数据兜底策略见 Q7。

### 3.2 模块职责边界

| 模块 | 职责 | 明确不做 |
| --- | --- | --- |
| 平台层-账号/RBAC | 注册、登录、JWT 签发、users/roles/permissions 三件套校验 | 不做 OAuth/第三方登录；忘记密码走管理员重置 |
| 平台层-应用注册表 | 应用元数据（名称/描述/图标/颜色/分类/排序）+ 用户级可见性/工作台固定覆盖，驱动「应用中心」与「每日看板」 | 不含应用业务逻辑 |
| 平台层-模型管理 | Provider CRUD、调官方 `GET /models` 拉取模型清单（按套餐分组）、连通性测试、网关默认路由配置 | 不做应用绑定；不做用量计费 |
| AI 网关 | 按默认路由（默认 Provider/模型）调对应 OpenAI 兼容端点；统一 SSE 流式输出；文献解读/摘要翻译/记账解析复用同一网关 | 不做 per-app 绑定；不实现非 OpenAI 兼容协议 |
| 应用 API-记账 | 账目 CRUD、自定义分类、月度统计、request_id 幂等 | 不做预算/报销/多人账本 |
| 应用 API-文献 | 文献流（归属隔离）、收藏、笔记、AI 解读缓存、中文摘要回填；由进程内定时任务触发的抓取 | 不做全文 PDF 管理；不做后端进程内调度 |
| 前端 ChatApp 组件 | 唯一通用对话 React 组件（对标 DeepSeek 对话界面）：左侧会话列表、消息流、SSE 流式渲染、Markdown 渲染 + 代码块高亮、新建/删除会话 | 各对话应用不得自研聊天 UI |

### 3.3 数据流要点

| 数据流 | 说明 |
| --- | --- |
| 登录流 | 用户名+密码 → bcrypt 校验 → JWT（30 天）→ 前端存储 → 后续请求 Bearer 携带 |
| 对话流 | 前端 ChatApp → `POST /chat {app_id, conversation_id, message}` → 校验权限/限流 → 存用户消息 → 组装内置 system prompt + 历史 → AI 网关按默认路由 SSE 逐 token 返回 → 完整回复落库 → `[DONE]` |
| AI 记一笔流 | 前端输入自然语言 → `POST /money/parse`（Q4 已决，本期实施）→ AI 网关一次性返回结构化草稿 → 用户确认 → 正常走 `POST /money/transactions` 入账（解析与入账分离，解析不落库） |
| 文献流 | 进程内定时任务每日触发 → 按每用户订阅关键词 esearch/efetch → 去重入库 + 规则打标 + 归属记录 → best-effort LLM 中文摘要 → 用户看到按人隔离的文献流 |
| 隔离原则 | 所有业务查询必须带 `user_id` 过滤；文献主表全局共享，归属表（paper_users）决定可见性；文献 AI 解读缓存全局共享（架构已定） |

---

## 4. 接口明细

> 约定：
> - 除登录/注册外所有接口需 JWT 鉴权；`admin:*` 权限接口仅 admin 角色可用；业务接口按权限点（如 `app:money`）鉴权。
> - 响应统一为 JSON（SSE 除外）；错误统一 `{detail: string}` + 标准 HTTP 状态码（400/401/403/404/409/429/502/503）。
> - 时间格式 ISO 8601；日期格式 `YYYY-MM-DD`。
> - API Key 在响应中一律脱敏（仅返回 `has_key` 布尔与后 4 位掩码）。
> - 幂等约定：请求带 `request_id` 的写接口按 request_id 去重（见记账）；收藏切换为幂等 toggle；文献入库 ON CONFLICT DO NOTHING。

### 4.1 认证模块 `/auth`（基础设施，所有批次共用）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/auth/register` | 注册（仅 `REGISTRATION_OPEN=true` 时开放，默认关）；请求 `{username, password}`；成功返回用户信息 + JWT | 公开（开关控制） |
| POST | `/auth/login` | 登录；请求 `{username, password}`；成功返回 `{token, user:{id, username, nickname, roles}}` | 公开 |
| GET | `/auth/me` | 当前用户信息 + 角色 + 权限点列表 | 登录 |
| POST | `/auth/change-password` | 修改本人密码；请求 `{old_password, new_password}` | 登录 |

说明：JWT 30 天过期，无 refresh token；登出为前端丢弃 token；忘记密码 = 管理员后台重置。

### 4.2 平台管理-RBAC `/admin/users`（基础设施，权限点 `admin:users`）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/admin/users` | 用户列表（含角色绑定） | admin:users |
| POST | `/admin/users` | 创建用户（用户名+初始密码+角色） | admin:users |
| GET | `/admin/users/{uid}` | 用户详情（角色、权限点、创建时间） | admin:users |
| PUT | `/admin/users/{uid}` | 更新用户（昵称、启用/停用） | admin:users |
| PUT | `/admin/users/{uid}/roles` | 重设用户角色；请求 `{role_ids:[…]}` | admin:users |
| POST | `/admin/users/{uid}/reset-password` | 管理员重置该用户密码，返回一次性新密码 | admin:users |
| DELETE | `/admin/users/{uid}` | 删除用户（默认软删除，见 Q6） | admin:users |
| GET | `/admin/roles` | 角色列表（含权限点） | admin:users |
| POST | `/admin/roles` | 新建角色（v1 预置 admin/member，表结构可扩展） | admin:users |
| PUT | `/admin/roles/{rid}` | 更新角色名称 | admin:users |
| PUT | `/admin/roles/{rid}/permissions` | 重设角色权限点；请求 `{permissions:[…]}` | admin:users |
| DELETE | `/admin/roles/{rid}` | 删除角色（预置角色不可删） | admin:users |
| GET | `/admin/permissions` | 全量权限点清单。v1.1 权限点：`app:chat`、`app:money`、`app:papers`、`admin:users`、`admin:models` | admin:users |

### 4.3 平台管理-模型管理 `/admin/models`（基础设施，权限点 `admin:models`）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/admin/models/providers` | Provider 列表；返回 id/name/vendor/base_url/enabled/has_key/api_key 掩码 | admin:models |
| POST | `/admin/models/providers` | 新建 Provider；请求 `{name, vendor, base_url, api_key, enabled}`，vendor ∈ deepseek/kimi/openai/自定义/mock | admin:models |
| GET | `/admin/models/providers/{pid}` | Provider 详情（含已拉取的模型清单） | admin:models |
| PUT | `/admin/models/providers/{pid}` | 更新 Provider；api_key 留空表示不修改 | admin:models |
| DELETE | `/admin/models/providers/{pid}` | 删除 Provider（其下仍有模型被默认路由引用时返回 409） | admin:models |
| POST | `/admin/models/providers/{pid}/test` | 最小请求测试连通性，返回 `{ok, latency_ms, model?/error?}` | admin:models |
| POST | `/admin/models/providers/{pid}/fetch-models` | 调用官方 `GET {base_url}/models` 拉取该 Key 可用模型（平铺列表，套餐身份并入 Provider 条目名）入库并返回 `[{name, meta}]` | admin:models |
| POST | `/admin/models/providers/{pid}/models` | 手动添加自定义模型 `{name, meta?}`；同 Provider 下重名 409 | admin:models |
| GET | `/admin/models/default-route` | 当前网关默认路由（默认 Provider + 默认模型），便于排障 | admin:models |
| PUT | `/admin/models/default-route` | 设置默认路由 `{provider_id, model}`；未设置时取首个启用 Provider 的第一个模型 | admin:models |

网关令牌（对外 `/gw/v1` 接入管理，权限点 `admin:models`）：

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/admin/gateway-tokens` | 令牌列表（掩码、模型范围、状态） | admin:models |
| POST | `/admin/gateway-tokens` | 创建令牌 `{name, model_scope?}`；完整令牌仅创建时返回一次 | admin:models |
| DELETE | `/admin/gateway-tokens/{tid}` | 吊销令牌，调用方立即失效 | admin:models |

说明：Key 存库（自部署威胁模型低），环境变量作首次种子默认值；运行时热生效；对话与记账解析统一走默认路由，更换模型/供应商只动网关层，业务接口零改动。

### 4.4 应用注册表 `/apps`（基础设施）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/apps` | 应用数据：应用列表（id/name/desc/color/icon/category/sort）+ 分类列表 + 每用户覆盖（hidden、工作台固定 pinned/sort） | 登录 |
| POST | `/apps/categories` | 新建分类 | 登录 |
| PUT | `/apps/categories/{cid}` | 重命名分类 | 登录 |
| DELETE | `/apps/categories/{cid}` | 删除分类（旗下应用回落未分类） | 登录 |
| PUT | `/apps/{app_id}/config` | 用户级覆盖：`{hidden?, pinned?, sort?, category_id?}`（显式 null 清除覆盖） | 登录 |

说明：应用注册表数据驱动前端两层导航（每日看板信息板块 + 应用中心全量，见 §7）。

### 4.5 用户设置 `/me`（基础设施）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/me` | 本人信息 + 全部个人设置（键值） | 登录 |
| PUT | `/me/settings` | upsert 个人设置；请求 `{key, value}`。已知 key：`subscribe_keywords`（文献订阅关键词，第二批启用） | 登录 |

### 4.6 通用对话 `ChatApp`（第一批，权限点 `app:chat` 或按 app_id 鉴权）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/chat` | **SSE**。请求 `{app_id, conversation_id?, message, model_id?, thinking_level?}`。事件流：`data: {reasoning_delta}`（思维双流，增量 rev6）→ `data: {delta}` 正文逐段 → `data: {error}`（流中断）→ `data: [DONE]`。`model_id` 缺省走默认路由；`thinking_level` 为可选思考档位（按目标模型 `meta.reasoning.levels` 白名单校验，会话级快照，不传 = 厂商默认）；system prompt 为内置常量（已启用 skill 片段按序注入其后，见增量文档 §7）；`conversation_id` 缺省用最近会话，无则新建 | 该 app 权限点 |
| POST | `/chat/polish` | AI 润色 `{text}`（1–4000 字）→ `{polished}`；复用默认路由非流式调用，system prompt 内置常量，≤8s、失败 502、限流 429（增量 rev6，P1-2） | 该 app 权限点 |
| GET | `/chat/models` | 对话模型池：启用 Provider 的启用模型 `[{id, name, provider, capabilities, reasoning, is_default}]`，按 Provider 条目分组；供模型选择器使用。`reasoning = {enabled, levels:[{value,label}], default_level}`（无该键 = 不支持思考，R5） | 登录用户 |
| GET | `/chat/conversations?app_id=` | 会话列表（updated_at 倒序，含标题） | 该 app 权限点 |
| GET | `/chat/conversations/summary?app_id=` | 看板聚合：`{yesterday_count, latest:{id, title, updated_at}}`（昨日有更新的会话数 + 最近一条；日期边界按服务器本地时区） | 该 app 权限点 |
| POST | `/chat/conversations` | 新建会话 `{app_id, title?}` | 该 app 权限点 |
| DELETE | `/chat/conversations/{cid}` | 删除会话（级联删消息） | 该 app 权限点 |
| GET | `/chat/history?app_id=&conversation_id=` | 历史消息（≤200 条，升序）+ 会话标题 | 该 app 权限点 |
| DELETE | `/chat/history?conversation_id=` | 清空会话消息（会话保留） | 该 app 权限点 |

规则与错误场景要点：

| 场景 | 行为 |
| --- | --- |
| 模型未配置 | 503 + 友好文案，引导去管理页配置（对 member 提示联系管理员） |
| 超出每日轮数上限 | 429 + 文案（上限机制见 Q1，默认不限） |
| 会话不存在/不属于本人 | 404 |
| 流中途失败 | 客户端收到 `{error}` 事件，已产生文字不落库，历史不出现半截回复 |
| 流正常结束 | 完整助手消息落库后发送 `[DONE]` |
| 上下文窗口 | 发给模型的历史取最近 20 轮（40 条），超出截断（见 Q2） |
| 会话标题 | 首条用户消息自动生成标题（截取 16 字） |
| 并发对话 | 同一用户并发请求各自独立，互不污染上下文 |

说明：对话为单一通用应用（slug `app_id=chat`），对标 DeepSeek 对话界面；系统提示词为后端内置常量（通用助手）。模型选择器按 Provider 条目分组展示模型池，选择值 `model_id` 绑定会话（`chat_conversations.model_id`，可空 = 默认路由）。文件上传按钮由模型 capabilities.files 驱动显隐（上传接口 `POST /files` 留待后续批次）。

### 4.7 记账 `/money`（第一批，新增，权限点 `app:money`）

**账目字段契约**（架构师据此设计表，此处不定表结构）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | int | 账目 ID |
| request_id | string(64) | 客户端生成的幂等键；同一用户下唯一。重复提交返回首次创建的记录（不重复入账） |
| amount | int | 金额，**以「分」为单位**的最小货币整数（避免浮点误差；展示层换算元） |
| type | enum | `expense` 支出 / `income` 收入 |
| category_id | int | 分类 ID（须属于当前用户；见下方分类约束） |
| note | string(256) | 备注，可空 |
| date | date | 账目日期（可补记过去日期，不晚于今天） |
| created_at / updated_at | datetime | 服务端生成 |

**分类字段契约**：`{id, name, kind: expense|income|both, icon?, sort, built_in}`。分类按用户隔离，仅本人可见可用；预置常用分类（餐饮/交通/购物/居住/收入等，built_in=true，可改名可隐藏不可删除——预置项可否删除见 Q5）。

**接口明细**：

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/money/categories` | 分类列表（按 sort 升序，含 built_in 标记） | app:money |
| POST | `/money/categories` | 新建分类 `{name, kind, icon?, sort?}`；重名（同 kind）返回 409 | app:money |
| PUT | `/money/categories/{cid}` | 更新分类（改名/图标/kind/sort）；built_in 分类不可改 kind、不可删除 | app:money |
| DELETE | `/money/categories/{cid}` | 删除自定义分类；该分类下存在账目时返回 409 + 账目数（提示先迁移或删除账目）；built_in 返回 403 | app:money |
| GET | `/money/transactions` | 账目列表；query：`from`、`to`（日期区间，必填其一，默认本月）、`category_id`、`type`、`page`（默认 1）、`page_size`（默认 20，≤100）；返回 `{items[], total, page, page_size}`，倒序 | app:money |
| POST | `/money/transactions` | 记一笔 `{request_id, amount, type, category_id, note?, date}`；request_id 重复 → 返回已有记录 + `idempotent: true`；校验失败返回 400（金额>0、分类归属、日期不晚于今天） | app:money |
| GET | `/money/transactions/{tid}` | 单条详情；非本人 404 | app:money |
| PUT | `/money/transactions/{tid}` | 编辑 `{amount?, type?, category_id?, note?, date?}`；部分更新；非本人 404 | app:money |
| DELETE | `/money/transactions/{tid}` | 删除；非本人 404 | app:money |
| GET | `/money/stats/monthly?month=YYYY-MM` | 月度统计：`{month, expense_total, income_total, balance, by_category:[{category_id, name, total, count}]}`（支出按分类汇总降序） | app:money |
| GET | `/money/stats/trend?months=6` | 趋势：`{months:[{month, expense_total, income_total}]}`，最近 N 个月（默认 6，≤12），无数据月份补零 | app:money |
| GET | `/money/stats/summary` | 看板聚合：`{yesterday_expense, week_expense, month_income, month_expense}`（金额单位「分」对齐既有接口；昨日/本周/本月日期边界按服务器本地时区，周 = 周一起） | app:money |
| POST | `/money/parse` | **AI 记一笔（Q4 已决：本期实施）**：请求 `{text}`；AI 网关一次性（非 SSE）返回 `{amount, type, category_suggestion, note, date, confidence?}`；仅生成草稿不落库，确认后走 POST /money/transactions；模型未配置 503 | app:money |

记账规则要点：金额为正整数（分）；type 与 category.kind 必须兼容（expense 账目挂 expense/both 分类）；所有查询/写入按 user_id 隔离；统计口径 = 按 `date` 字段归属月份。

### 4.8 文献 `/papers`（第二批，权限点 `app:papers`）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/papers/daily` | 每日推送：仅本人订阅抓到的文献（归属隔离），created_at 倒序；query：`tag`（AD/PD/ALS/scale 之一，JSONB 包含筛选）、`limit`（默认 50，≤200） | app:papers |
| GET | `/papers/favorites` | 我的收藏列表（收藏时间倒序） | app:papers |
| GET | `/papers/{pid}` | 单篇详情：题录 + 收藏状态 + 本人笔记 + 全局 AI 解读缓存（无则 null） | app:papers |
| POST | `/papers/{pid}/save` | 幂等切换收藏，返回 `{saved:bool}` | app:papers |
| POST | `/papers/{pid}/note` | 笔记 upsert `{content}`（每人每篇一条，覆盖） | app:papers |
| POST | `/papers/{pid}/explain` | AI 解读：命中缓存直返；未命中调 AI 网关生成并写全局缓存（成功才入库）。未配置模型 503 友好文案；生成失败 502 | app:papers |

字段要点（沿用旧版）：`pmid, title, abstract, abstract_zh（LLM 中译）, journal, authors[], pub_date, tags[], keywords[]`。

抓取触发（批次 2）：由 **后端进程内 APScheduler** 每日固定时间触发（cron 配置在后端，建议早间）；后端暴露内部触发接口 `POST /internal/jobs/papers-crawl`，仅校验**内部令牌**（环境变量 `LUMEN_INTERNAL_TOKEN`，占位名以架构设计为准，不经过用户 JWT 体系），校验通过后执行一轮抓取并返回 `{added: n}`；不对普通用户开放、不在前端出现。触发后的抓取逻辑与限速不变：遵守 NCBI 限速（≤3 req/s，efetch 分批 ≤100/批、批间 sleep）；中文摘要翻译每篇间隔 ≥1s、单轮 ≤20 篇；订阅关键词取用户设置 `subscribe_keywords`（未配置回落环境变量默认）。

---

## 5. 需求池

### P0（Must have · 第一批）

| # | 需求 |
| --- | --- |
| P0-1 | 【基础设施·所有批次共用】账号体系：注册（`REGISTRATION_OPEN` 默认关）/登录/改密，bcrypt，JWT 30 天 |
| P0-2 | 【基础设施】RBAC 三件套 + `require_permission` 依赖注入；预置 admin/member；权限点含 `app:money` |
| P0-3 | 【基础设施】模型管理：Provider（厂商×套餐条目）CRUD + 官方 API 拉取模型（平铺）+ 自定义模型 + 连通性测试 + 默认路由 + 网关令牌 |
| P0-4 | 【基础设施】应用注册表 + 分类 + 用户级覆盖（hidden/pinned/sort） |
| P0-5 | 【基础设施】用户设置 `/me/settings` |
| P0-6 | 【基础设施】React 壳：登录页、卡片工作台 + 应用中心、ChatApp 通用对话组件 |
| P0-7 | ChatApp 后端：`POST /chat` SSE + 会话管理（user+app 隔离、20 轮上下文、自动标题、错误场景） |
| P0-8 | 对话应用（通用 AI 对话，app_id=chat）：ChatApp 界面 + 内置通用助手提示词（网关默认路由） |
| P0-9 | 记账：账目 CRUD + 自定义分类 + request_id 幂等 |
| P0-10 | 记账：月度统计（分类汇总/收支合计）+ 近 6 个月趋势 |
| P0-11 | 记账：「AI 记一笔」自然语言解析（Q4 已决：本期实施） |

### P1（Should have · 第二批）

| # | 需求 |
| --- | --- |
| P1-1 | 文献：每日推送（归属隔离 + 标签筛选）/ 收藏 / 笔记 / AI 解读全局缓存 / 中文摘要翻译回填 |
| P1-2 | 文献：进程内 APScheduler 定时抓取 + 内部令牌手动触发接口（POST /internal/jobs/papers-crawl）+ 订阅关键词用户设置 |

---

## 6. 非功能需求

### 6.1 性能（2核4G 硬约束）

| # | 需求 |
| --- | --- |
| N1 | 全部服务（FastAPI/PostgreSQL/Caddy）可在 2核4G 单机上稳定运行；容器 restart: unless-stopped |
| N2 | 常规 REST 接口 P95 ≤ 300ms（不含 LLM 调用）；SSE 首 token 延迟 ≤ 5s |
| N3 | 文献抓取遵守 NCBI 限速（≤3 req/s，efetch 分批 ≤100/批、批间 sleep）；中文摘要翻译每篇间隔 ≥1s，单轮 ≤20 篇 |
| N4 | 不引入独立监控应用；Actions 日志 + 服务日志足够 |
| N5 | 「AI 记一笔」解析耗时 ≤ 8s（非流式一次性返回），前端需有加载态与超时文案 |

### 6.2 数据

| # | 需求 |
| --- | --- |
| N6 | 所有业务数据 PostgreSQL，**user_id 行级隔离**：每条业务查询必须按 user_id 过滤（文献主表共享、归属表隔离；解读缓存全局共享为例外） |
| N7 | 金额一律以「分」整数存储与传输，展示层换算，杜绝浮点误差 |
| N8 | 账目写接口以 request_id 幂等去重，网络重试/双击不产生重复账 |

### 6.3 安全清单

| # | 需求 |
| --- | --- |
| N9 | 密码 bcrypt；JWT secret 长随机（已有） |
| N10 | 所有管理页接口仅 admin（`require_permission` 强制，前端隐藏不算数） |
| N11 | API Key 响应脱敏（掩码 + has_key）；仓库确认无密钥入库 |
| N12 | 备份文件权限收紧（如部署侧保留手动 pg_dump 兜底，见 Q7） |
| N13 | Caddy 反代 `/api` 且 SSE 路径不缓冲；全站 HTTPS |
| N14 | 登录/注册/对话/parse 接口做基础限流（防暴力破解与刷接口） |

---

## 7. 前端需求

### 7.1 整体信息架构：两层（参照 iOS 主屏 + App 资源库）

| 层 | 说明 |
| --- | --- |
| 首页·每日看板（原卡片工作台） | **信息优先，卡片即跳板**：按应用划分信息板块（记账 / 论文 / 对话），每板块只放「每天值得一眼的信息」，整卡点击进对应应用；上板判断 = 应用有每日值得关注的信息（配置型应用不上板），应用增加 = 板块注册表加卡片；保留拖拽排序（lc_home_order，常用在前；折叠/自选待板块过多时再做） |
| 应用中心 | 全量应用列表，按分类分组、可搜索；与首页共用应用注册表数据 |

手机端：底部导航（工作台 / 应用中心 / 我的）；电脑端：左侧栏 + 内容区，同一套路由。一套代码自适应。

### 7.2 页面要点

| 页面 | 要点 |
| --- | --- |
| 登录/注册 | 居中卡片；注册入口仅 `REGISTRATION_OPEN=true` 时显示 |
| 每日看板（首页） | 轻问候行（x月x日 星期x + 时段问候 + 昵称，不放全局指标带）+ bento 板块卡片区：记账板块（昨日消费/本周消费/本月收支 + 迷你趋势条 → #/money）、论文板块（大卡新闻流式「今日推送」，标题+期刊+时间，空态引导订阅关键词；本期 mock 演示）、对话板块（昨日对话数 + 最近会话摘要 + 「继续聊」→ #/chat）；整卡即跳板，卡头右侧「应用名 →」；桌面 bento 多列（论文 span-8 + 对话 span-4，记账 span-12 横条），手机 ≤900px 单列堆叠；保留 grip 拖拽排序（lc_home_order）；各板块骨架加载 + 按应用一句空态引导 |
| 应用中心 | 分组列表 + 搜索框 + 应用详情操作（固定到首页/隐藏/移分类） |
| ChatApp 组件 | 对标 DeepSeek 对话界面：左侧会话列表（新建/删除/切换）、消息流、底部输入；SSE 打字机渲染；Markdown 渲染 + 代码块高亮 + 复制按钮；error 事件 toast |
| 记账首页 | 本月收支合计条 + 「记一笔」主按钮 + 最近账目列表 + 分类管理入口 |
| 记一笔表单 | 金额键盘（手机唤起数字键盘）、收支切换、分类 chips、备注、日期（默认今天） |
| AI 记一笔 | 输入一句话 → 解析预览卡片（可改字段）→ 确认入账 |
| 月度统计 | 分类汇总条形/列表 + 近 6 个月趋势图（简单柱状即可，不引图表库重型依赖——默认决策，见 Q8） |
| 文献页（第二批） | 标签筛选 chips + 文献卡片流；详情抽屉：摘要中英对照、收藏、笔记编辑、AI 解读（缓存命中秒开） |
| 管理页 | 仅 admin 可见入口：用户/角色、Provider（厂商×套餐条目）与模型清单（官方拉取 + 自定义模型）、网关默认路由、网关令牌 |
| 我的 | 个人设置、修改密码、应用版本与账号信息 |

---

## 8. 待确认问题清单

| # | 问题 | 默认决策（可先行） |
| --- | --- | --- |
| Q1 | 对话每日轮数上限是否保留（旧版有 `chat_daily_limit`） | 默认保留机制：上限做成可配项（后续批次落设置），默认 0 = 不限 |
| Q2 | 上下文保留轮数（旧版 20 轮） | 默认沿用 20 轮，做成全局常量 |
| Q4 | ~~「AI 记一笔」是否本期实施~~ **已决（2026-10-14）：本期实施** | 已定：实施 `POST /money/parse`。解析/入账分离、解析不落库、可改后确认 |
| Q5 | 记账预置分类可否删除/隐藏 | 默认 built_in 分类可改名、可隐藏、不可删除 |
| Q6 | 删除用户用软删除还是硬删除 | 默认软删除（保留数据可恢复） |
| Q7 | 数据兜底：本期不做自动备份任务，数据库备份如何保障 | 默认：由部署侧手动 pg_dump / 云厂商快照兜底；开源打磨批次再议 |
| Q8 | 月度趋势图是否引入图表库 | 默认用轻量 CSS/SVG 自绘柱状图，不引重型图表库 |

---

## 9. 附录：新旧映射（v1.1 适用）

| 旧能力（old/） | 新去向 |
| --- | --- |
| 微信登录 + whitelist_users | 废弃 → 账号密码登录 + users/RBAC |
| LLM provider 抽象 + 用途路由 | 演进为 Provider + 模型清单（网关默认路由，无应用绑定） |
| 旧版 chat 模块（SSE/会话/限流/标题生成） | 泛化为 ChatApp `/chat`（app_id=chat 通用对话应用），第一批 |
| 文献 crawler（esearch/efetch/打标/翻译回填） | 保留逻辑，由进程内定时任务触发，第二批 |
| space 设置 / 邀请码 / 危险操作双人确认 | space 设置 → 用户设置；邀请码废弃（注册开关替代）；双人确认不做 |
| `miniprogram/`、`app_原型/` | 归档/参考，不迁移 |
