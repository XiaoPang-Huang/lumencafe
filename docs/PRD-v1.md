# 流光咖啡馆（LumenCafe）产品需求文档 v1

> 版本：v1 · 2026-10-14 · 产品经理：许清楚（software-product-manager-2）
> 基准文档：《架构定稿-v1.md》（2026-10-14 定稿）。本文档严格以架构文档为准，冲突处以架构文档为最高优先级。
> 需求来源：旧版 FastAPI 后端（`old/`）业务能力（打卡/心情/文献 crawler/LLM provider 抽象）+ 架构文档新增需求。旧接口全部废弃重写，本文档的接口明细即新接口契约。

---

## 1. 项目信息

| 项 | 值 |
| --- | --- |
| 产品名 | 流光咖啡馆（LumenCafe） |
| 项目代号 | `lumencafe` |
| 产品定位 | 自部署的两人 AI 应用面板；打磨成熟后 MIT 开源 |
| 前端技术栈 | Vite + React + TypeScript + shadcn/ui + Tailwind CSS（一套代码手机/电脑自适应） |
| 后端技术栈 | FastAPI + PostgreSQL（沿用架构文档） |
| 部署形态 | Docker Compose：Caddy + FastAPI + PostgreSQL（+ n8n 后装） |
| GitHub 仓库 | `XiaoPang-Huang/lumencafe` |
| 前端域名 | `cafe.lumenhub.online` |
| API 域名 | `api.lumenhub.online` |

**原始需求复述**：将归档的旧版 FastAPI 后端重写为全新的账号化 AI 应用面板。新增账号/RBAC、模型管理、ChatApp 通用对话件、知识库（pgvector）、自动化中心与备份；旧业务能力（打卡、心情、文献抓取/收藏/笔记/AI 解读、LLM provider 抽象）作为新需求来源全部重写保留。最终 MIT 开源。

---

## 2. 产品定义

### 2.1 产品目标

| # | 目标 | 衡量标准 |
| --- | --- | --- |
| G1 | 两位使用者拥有统一的个人 AI 应用入口 | 应用面板数据驱动，10 个应用全部可登录使用 |
| G2 | 对话能力完全配置驱动，零代码新增对话应用 | 新增一个对话应用 = 注册应用 + 配置提示词/模型，不写新接口 |
| G3 | 开源后其他自部署者可一条 Docker 命令部署并自行扩展 | MIT 发布；README 含部署文档与「如何添加新应用」开发者文档 |

### 2.2 用户画像

| 画像 | 描述 |
| --- | --- |
| 使用者 A / B（当前） | 两位亲密关系使用者，**均为管理员**。使用场景：日常打卡与心情记录、树洞式 AI 倾诉、神经科文献跟踪（AD/PD/ALS/量表）、AI 辅助旅行规划、个人知识库问答。设备：手机为主、电脑为辅（PWA 体验）。 |
| 自部署者（未来，开源后） | 具备 Docker 部署能力的个人/小团队，拉取仓库后自行配置域名、PostgreSQL、LLM Provider Key。需要注册开关、RBAC、模型管理页开箱可用。 |

### 2.3 用户故事

| # | 用户故事 | 对应应用 |
| --- | --- | --- |
| US-1 | 作为使用者，我想每天一键打卡并看到连续打卡天数与本周圆点，以便坚持「放下小说挑战」 | 打卡 |
| US-2 | 作为使用者，我想记录每日心情（好/一般/焦虑）并查看近 30 天历史，以便觉察情绪变化 | 心情 |
| US-3 | 作为使用者，我想与一个温柔的 AI 树洞持续多轮对话且历史按会话保存，以便倾诉并获得安抚 | 树洞对话 |
| US-4 | 作为使用者，我想每天看到按我订阅关键词抓到的 PubMed 新文献，能收藏、写笔记、一键 AI 解读（含中文摘要），以便跟踪研究领域 | 文献 |
| US-5 | 作为使用者，我想用对话方式规划旅行（同一对话组件、不同提示词），以便快速得到行程建议 | 旅行规划 |
| US-6 | 作为使用者，我想上传个人文档并向知识库提问且回答带引用，以便检索自己的资料 | 知识库 |
| US-7 | 作为使用者，我想在焦虑时打开纯前端的量表速查页与呼吸急救动画页（无需登录后端交互），以便自助平复 | 量表 / 呼吸急救 |
| US-8 | 作为管理员，我想在管理页配置 LLM Provider、模型清单与每个应用的绑定（模型/系统提示词/参数），以便对话完全配置驱动 | 平台管理 |
| US-9 | 作为管理员，我想每日自动备份数据库并查看备份历史，以便数据安全 | 自动化中心 |
| US-10 | 作为自部署者，我想通过 `REGISTRATION_OPEN` 控制注册、通过 RBAC 管理成员，以便两人以上共用实例 | 平台管理 |

---

## 3. 系统总体架构

### 3.1 分层与组件

```
浏览器（手机/电脑/PWA）
   │ HTTPS
Caddy ── 静态托管 React 构建产物 │ 反代 /api │ SSE 不缓冲
   │
FastAPI ──┬─ 平台层：账号/RBAC、应用注册表、模型管理、用户设置
          ├─ 应用 API：打卡 心情 文献 知识库…
          ├─ AI 网关：对话 SSE / 解读（DeepSeek/Kimi/OpenAI 兼容端点）
          └─ 定时任务：文献抓取、每日备份
   │
PostgreSQL（user_id 行级隔离；pgvector = 知识库）
   │
n8n（后装；仅自动化编排，与对话无关，不直连数据库）
```

### 3.2 模块职责边界

| 模块 | 职责 | 明确不做 |
| --- | --- | --- |
| 平台层-账号/RBAC | 注册、登录、JWT 签发、users/roles/permissions 三件套校验 | 不做 OAuth/第三方登录；忘记密码走管理员重置 |
| 平台层-应用注册表 | 应用元数据（名称/描述/图标/颜色/分类/排序）+ 用户级可见性覆盖，驱动首页面板 | 不含应用业务逻辑 |
| 平台层-模型管理 | Provider CRUD、模型清单、应用级绑定（provider+模型+系统提示词+参数覆盖）、连通性测试 | 不做用量计费/限流计费 |
| AI 网关 | 按 app_id 查配置 → 调对应 OpenAI 兼容端点；统一 SSE 流式输出；文献解读/摘要翻译复用同一网关 | 不实现非 OpenAI 兼容协议 |
| 应用 API | 各业务模块 REST 接口（打卡/心情/文献/知识库） | 不做应用间数据共享（文献解读缓存除外，架构明确全局共享） |
| 定时任务 | 进程内调度器：文献抓取（按 push_time）、每日 pg_dump 备份（按 backup_time） | 胶水型自动化交给 n8n |
| 前端 ChatApp 组件 | 唯一通用对话 React 组件：消息列表、输入框、SSE 渲染、会话管理 | 各对话应用不得自研聊天 UI |

### 3.3 数据流要点

| 数据流 | 说明 |
| --- | --- |
| 登录流 | 用户名+密码 → bcrypt 校验 → JWT（30 天）→ 前端存储 → 后续请求 Bearer 携带 |
| 对话流 | 前端 ChatApp → `POST /chat {app_id, conversation_id, message}` → 后端校验权限/限流 → 存用户消息 → 组装 system prompt + 历史 → AI 网关 SSE 逐 token 返回 → 完整回复落库 → `[DONE]` |
| 文献流 | 定时任务按每用户订阅关键词 esearch/efetch → 去重入库 + 规则打标 + 归属记录 → best-effort LLM 中文摘要 → 用户看到按人隔离的文献流 |
| 备份流 | 定时任务按 backup_time 触发 pg_dump → 压缩 → 本地保留 7 份（可选同步 COS） |
| 隔离原则 | 所有业务查询必须带 `user_id` 过滤；文献主表全局共享，归属表（paper_users）决定可见性；文献 AI 解读缓存全局共享（架构已定） |

---

## 4. 接口明细

> 约定：
> - 除登录/注册外所有接口需 JWT 鉴权；`admin:*` 权限接口仅 admin 角色可用。
> - 响应统一为 JSON（SSE 除外）；错误统一 `{detail: string}` + 标准 HTTP 状态码（401/403/404/429/502/503）。
> - 时间格式 ISO 8601；日期格式 `YYYY-MM-DD`。
> - API Key 在响应中一律脱敏（仅返回 `has_key` 布尔与后 4 位掩码）。
> - 幂等约定：打卡/心情/任务完成用 upsert（重复提交覆盖或忽略）；收藏切换为幂等 toggle；文献入库 ON CONFLICT DO NOTHING。

### 4.1 认证模块 `/auth`

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/auth/register` | 注册（仅 `REGISTRATION_OPEN=true` 时开放）；请求 `{username, password}`；成功返回用户信息 + JWT。**默认关闭**。 | 公开（开关控制） |
| POST | `/auth/login` | 登录；请求 `{username, password}`；成功返回 `{token, user:{id, username, nickname, roles}}` | 公开 |
| GET | `/auth/me` | 当前用户信息 + 角色 + 权限点列表 | 登录 |
| POST | `/auth/change-password` | 修改本人密码；请求 `{old_password, new_password}` | 登录 |

说明：JWT 30 天过期，无 refresh token；登出为前端丢弃 token，无需服务端接口；忘记密码 = 管理员在后台重置（见 4.2）。

### 4.2 平台管理-RBAC `/admin/users`（权限点 `admin:users`）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/admin/users` | 用户列表（含角色绑定） | admin:users |
| POST | `/admin/users` | 创建用户（用户名+初始密码+角色） | admin:users |
| GET | `/admin/users/{uid}` | 用户详情（角色、权限点、创建时间） | admin:users |
| PUT | `/admin/users/{uid}` | 更新用户（昵称、启用/停用） | admin:users |
| PUT | `/admin/users/{uid}/roles` | 重设用户角色；请求 `{role_ids:[…]}` | admin:users |
| POST | `/admin/users/{uid}/reset-password` | 管理员重置该用户密码，返回一次性新密码 | admin:users |
| DELETE | `/admin/users/{uid}` | 删除用户（软删除或硬删除由架构师定，需求=数据不再可见） | admin:users |
| GET | `/admin/roles` | 角色列表（含权限点） | admin:users |
| POST | `/admin/roles` | 新建角色（表结构按可扩展设计，v1 预置 admin/member） | admin:users |
| PUT | `/admin/roles/{rid}` | 更新角色名称 | admin:users |
| PUT | `/admin/roles/{rid}/permissions` | 重设角色权限点；请求 `{permissions:["app:chat",…]}` | admin:users |
| DELETE | `/admin/roles/{rid}` | 删除角色（预置角色不可删） | admin:users |
| GET | `/admin/permissions` | 全量权限点清单（供角色编辑页渲染） | admin:users |

### 4.3 平台管理-模型管理 `/admin/models`（权限点 `admin:models`）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/admin/models/providers` | Provider 列表；返回 id/name/vendor/base_url/enabled/has_key/api_key 掩码 | admin:models |
| POST | `/admin/models/providers` | 新建 Provider；请求 `{name, vendor, base_url, api_key, enabled}`，vendor ∈ deepseek/kimi/openai/自定义/mock | admin:models |
| GET | `/admin/models/providers/{pid}` | Provider 详情（含模型清单） | admin:models |
| PUT | `/admin/models/providers/{pid}` | 更新 Provider；api_key 留空表示不修改 | admin:models |
| DELETE | `/admin/models/providers/{pid}` | 删除 Provider（被应用绑定引用时返回 409 + 引用列表） | admin:models |
| POST | `/admin/models/providers/{pid}/test` | 最小请求测试连通性，返回 `{ok, latency_ms, model?/error?}` | admin:models |
| PUT | `/admin/models/providers/{pid}/models` | 重设该 Provider 模型清单；请求 `[{name, temperature, max_tokens, top_p}]` | admin:models |
| GET | `/admin/models/bindings` | 应用级绑定列表：每对话应用 → `{provider_id, model, system_prompt, param_overrides}` | admin:models |
| PUT | `/admin/models/bindings/{app_id}` | 设置某对话应用的绑定（upsert）；参数覆盖可空 = 用模型默认值 | admin:models |
| GET | `/admin/models/self-test` | 不发起网络请求，解析各 app_id 当前实际命中的 provider/模型，便于排障 | admin:models |

说明：Key 存库（自部署威胁模型低），环境变量作首次种子默认值；运行时热生效；对话接口完全配置驱动。

### 4.4 应用注册表 `/apps`

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/apps` | 应用面板数据：应用列表（id/name/desc/color/icon/category/sort/hidden）+ 分类列表；hidden 为当前用户覆盖结果 | 登录 |
| POST | `/apps/categories` | 新建分类 | 登录 |
| PUT | `/apps/categories/{cid}` | 重命名分类 | 登录 |
| DELETE | `/apps/categories/{cid}` | 删除分类（旗下应用回落未分类） | 登录 |
| PUT | `/apps/{app_id}/config` | 用户级覆盖：`{hidden?, category_id?}`（显式 null 清除覆盖） | 登录 |

说明：应用注册表数据驱动前端面板（沿用老设计）；新增应用 = 注册一条记录 + 按模式实现页面/接口。

### 4.5 用户设置 `/me`

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/me` | 本人信息 + 全部个人设置（键值） | 登录 |
| PUT | `/me/settings` | upsert 个人设置；请求 `{key, value}`。已知 key：`subscribe_keywords`（文献订阅关键词）、`daily_task_pref`（每日小事偏好 papers/tidy/mix） | 登录 |

### 4.6 打卡 `/focus`（权限点 `app:focus`）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/focus/today` | 今日状态聚合：`{streak, week[7], checked_today, task:{category,content}, task_done, mood_today}` | app:focus |
| POST | `/focus/checkin` | 今日打卡（幂等，重复返回已打卡） | app:focus |
| POST | `/focus/task/done` | 今日小事完成标记 `{done:bool}`（upsert） | app:focus |
| GET | `/focus/todos` | 待办列表 | app:focus |
| POST | `/focus/todos` | 新建待办 `{title}` | app:focus |
| PUT | `/focus/todos/{tid}` | 更新待办（改名/打勾） | app:focus |
| DELETE | `/focus/todos/{tid}` | 删除待办 | app:focus |

说明：连续天数规则沿用旧逻辑——今天没打卡则从昨天起算，断签当天不打断历史记录；今日小事按 `daily_task_pref` + 日期轮换从任务池选取（任务池为服务端常量，沿用旧版文献类/整理类各 4 条）。

### 4.7 心情 `/mood`（权限点 `app:mood`）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/mood` | 记录今日心情 `{mood: good|ok|anxious}`（每人每天一条，重复覆盖） | app:mood |
| GET | `/mood/history` | 近 30 天历史 `{history:[{date, mood}]}` | app:mood |

### 4.8 文献 `/papers`（权限点 `app:papers`）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/papers/daily` | 每日推送：仅本人订阅抓到的文献（归属隔离），created_at 倒序；query：`tag`（AD/PD/ALS/scale 之一，JSONB 包含筛选）、`limit`（默认 50，≤200） | app:papers |
| GET | `/papers/favorites` | 我的收藏列表（收藏时间倒序） | app:papers |
| GET | `/papers/{pid}` | 单篇详情：题录 + 收藏状态 + 本人笔记 + 全局 AI 解读缓存（无则 null） | app:papers |
| POST | `/papers/{pid}/save` | 幂等切换收藏，返回 `{saved:bool}` | app:papers |
| POST | `/papers/{pid}/note` | 笔记 upsert `{content}`（每人每篇一条，覆盖） | app:papers |
| POST | `/papers/{pid}/explain` | AI 解读：命中缓存直返；未命中调 AI 网关生成并写全局缓存（成功才入库）。未配置模型 503 友好文案；生成失败 502 | app:papers |

字段要点（沿用旧版）：`pmid, title, abstract, abstract_zh（LLM 中译）, journal, authors[], pub_date, tags[], keywords[]`。

### 4.9 通用对话 `ChatApp`（权限点 `app:chat` 或按 app_id 鉴权）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/chat` | **SSE**。请求 `{app_id, conversation_id?, message}`。事件流：`data: {delta}` 逐段 → `data: {error}`（流中断）→ `data: [DONE]`。app_id 决定 system prompt/模型/参数（后端查绑定）；`conversation_id` 缺省用最近会话，无则新建 | 该 app 权限点 |
| GET | `/chat/conversations?app_id=` | 会话列表（updated_at 倒序，含标题） | 该 app 权限点 |
| POST | `/chat/conversations` | 新建会话 `{app_id, title?}` | 该 app 权限点 |
| DELETE | `/chat/conversations/{cid}` | 删除会话（级联删消息） | 该 app 权限点 |
| GET | `/chat/history?app_id=&conversation_id=` | 历史消息（≤200 条，升序）+ 会话标题 | 该 app 权限点 |
| DELETE | `/chat/history?conversation_id=` | 清空会话消息（会话保留） | 该 app 权限点 |

规则要点：
- 消息历史按 **user + app** 隔离；发给模型的上下文取最近 **20 轮**（40 条）。
- 会话首条用户消息自动生成标题（截取 16 字）。
- 限流见 §9 待确认问题 Q1（沿用旧版每日轮数上限机制）。
- 流中途失败：客户端收到 error 事件，已产生文字不落库。
- 树洞（slug `chat`）与旅行规划（slug `travel`）均为本接口的 app_id 实例，无独立后端接口。

### 4.10 知识库 `/kb`（权限点 `app:kb`，P2）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/kb/documents` | 上传文档（multipart 文件或 `{title, content}`）；服务端切块 → embedding 入 pgvector | app:kb |
| GET | `/kb/documents` | 文档列表（标题、分块数、创建时间） | app:kb |
| DELETE | `/kb/documents/{did}` | 删除文档（级联删向量） | app:kb |
| POST | `/kb/search` | 检索接口：`{query, top_k?}` → `{chunks:[{doc_title, content, score}]}` | app:kb |

问答走 4.9 的 `/chat`（app_id=`kb`），后端在对话前先做检索、把命中块注入上下文，提示词要求回答附引用（文档标题 + 块序号）。

### 4.11 自动化中心（权限点 `admin:automation` 或登录可见只读）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/automation/config` | 任务配置：文献抓取 `push_time`、备份 `backup_time`、n8n webhook 地址（如有） | admin:automation（读写）/ 登录只读 |
| PUT | `/automation/config` | 更新上述配置 | admin:automation |
| POST | `/automation/crawl/run` | 手动触发一轮文献抓取，返回 `{added: n}` | admin:automation |
| GET | `/automation/crawl/logs` | 最近抓取日志（时间、新增数、失败原因） | 登录 |
| POST | `/automation/backup/run` | 立即执行备份，返回 `{file, size_bytes}` | admin:automation |
| GET | `/automation/backups` | 备份历史列表（文件名、大小、时间，保留 7 份） | admin:automation |
| POST | `/automation/n8n/webhook/{token}` | 供 n8n 回调的受控 webhook（生活提醒等），token 鉴权 | token |

说明：FastAPI 任务管数据密集任务（抓取/备份，事务+幂等）；n8n 管胶水型编排，仅通过 HTTP 调本 API 拿数据，**不直连数据库**（架构硬性约束）。

### 4.12 统计 `/stats`

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/stats/footprint` | 个人足迹：连续打卡、累计打卡、收藏数、小事完成数、心情记录数 | 登录 |
| GET | `/stats/storage` | 各应用记录数 + 表占用大小（拆库后接口不变，按库统计） | 登录 |

### 4.13 前端静态应用（无后端接口）

| 应用 | 说明 |
| --- | --- |
| 量表速查 | 纯前端静态内容页（量表条目内置为前端常量/JSON），无后端 |
| 呼吸急救 | 纯前端 CSS transform 动画引导呼吸，无后端 |

---

## 5. 需求池

优先级映射严格遵循架构文档 §12 批次（P0=批次1 地基；P1=批次2-4；P2=批次5 开源打磨）。

### P0（Must have · 批次1 地基）

| # | 需求 |
| --- | --- |
| P0-1 | 账号体系：注册（`REGISTRATION_OPEN` 默认关）/登录/改密，bcrypt，JWT 30 天 |
| P0-2 | RBAC 三件套：users/roles/permissions + 关联表 + `require_permission` 依赖注入；预置 admin/member；管理页用户/角色管理 |
| P0-3 | 模型管理：Provider CRUD + 模型清单 + 应用级绑定 + 连通性测试 + self-test（admin 专属） |
| P0-4 | React 壳：登录页、应用面板（注册表数据驱动）、ChatApp 通用对话组件 |
| P0-5 | 应用注册表 + 分类 + 用户级可见性覆盖 |
| P0-6 | ChatApp 后端：`POST /chat` SSE + 会话管理（按 user+app 隔离、20 轮上下文、自动生成标题） |

### P1（Should have · 批次2 复用页面）

| # | 需求 |
| --- | --- |
| P1-1 | 打卡：today 聚合 / 幂等打卡 / 今日小事 / 待办 CRUD |
| P1-2 | 心情：记录（每日覆盖）/ 近 30 天历史 |
| P1-3 | 文献：每日推送（归属隔离+标签筛选）/ 收藏 / 笔记 / AI 解读全局缓存 / 中文摘要翻译回填 |

### P1（Should have · 批次3 对话实例化）

| # | 需求 |
| --- | --- |
| P1-4 | 树洞对话：ChatApp 实例（温柔提示词走模型绑定配置） |
| P1-5 | 旅行规划：ChatApp 实例（仅提示词与开场白不同） |

### P1（Should have · 批次4 新能力）

| # | 需求 |
| --- | --- |
| P1-6 | 量表速查（纯前端静态页） |
| P1-7 | 呼吸急救（纯前端动画页） |
| P1-8 | 自动化中心-备份任务：每日 pg_dump → 压缩 → 本地保留 7 份，`backup_time` 可配，手动触发 + 历史 |
| P1-9 | 知识库：文档上传/切块/embedding（pgvector）/检索，`/chat` app_id=kb 带引用问答 |
| P1-10 | 自动化中心-文献抓取任务：进程内调度（`push_time`）+ 手动触发 + 日志；n8n 后装（Basic Auth，仅 HTTP 调 API） |
| P1-11 | 统计：footprint + storage |

### P2（Nice to have · 批次5 开源打磨）

| # | 需求 |
| --- | --- |
| P2-1 | Alembic 迁移（替代 create_all，开源前必须） |
| P2-2 | README：截图 + Docker 一条命令部署 |
| P2-3 | MIT License + 仓库转 Public |
| P2-4 | 「如何添加新应用」开发者文档（应用注册机制天然支持） |
| P2-5 | COS 同步备份（可选，默认不做） |

---

## 6. 非功能需求

### 6.1 性能（2核4G 硬约束）

| # | 需求 |
| --- | --- |
| N1 | 全部服务（FastAPI/PostgreSQL/Caddy，n8n 后装）可在 2核4G 单机上稳定运行；容器 restart: unless-stopped |
| N2 | 常规 REST 接口 P95 ≤ 300ms（不含 LLM 调用）；SSE 首 token 延迟 ≤ 5s |
| N3 | 文献抓取遵守 NCBI 限速（≤3 req/s，efetch 分批 ≤100/批、批间 sleep）；中文摘要翻译每篇间隔 ≥1s，单轮 ≤20 篇 |
| N4 | 不引入独立监控应用；Actions 日志 + 服务日志足够（架构已定） |

### 6.2 数据

| # | 需求 |
| --- | --- |
| N5 | 所有业务数据 PostgreSQL，**user_id 行级隔离**：每条业务查询必须按 user_id 过滤（文献主表共享、归属表隔离；解读缓存全局共享为例外） |
| N6 | 备份：每日 pg_dump → 压缩 → 本地保留 7 份（轮换删除），时间由 `backup_time` 设置项控制；可选同步 COS |
| N7 | 文件（知识库文档、头像等）先存服务器本地目录，COS 列为可选 |
| N8 | 开源前必须补 Alembic 迁移 |

### 6.3 安全清单（架构 §9 强制执行）

| # | 需求 |
| --- | --- |
| N9 | 密码 bcrypt；JWT secret 长随机（已有） |
| N10 | 所有管理页接口仅 admin（`require_permission` 强制，前端隐藏不算数） |
| N11 | API Key 响应脱敏（掩码 + has_key）；仓库确认无密钥入库 |
| N12 | n8n（将来）加 Basic Auth；n8n 不直连数据库 |
| N13 | 备份文件权限收紧（仅服务用户可读）；webhook token 鉴权 |
| N14 | Caddy 反代 `/api` 且 SSE 路径不缓冲；全站 HTTPS |
| N15 | 登录/注册/对话接口做基础限流（防暴力破解与刷接口） |

---

## 7. UI 设计草案（要点级）

| 页面 | 要点 |
| --- | --- |
| 登录/注册 | 居中卡片；注册入口仅 `REGISTRATION_OPEN=true` 时显示 |
| 应用面板（首页） | 注册表数据驱动网格卡片（color/icon/desc），按分类分组；长按/设置进入隐藏与自定义分类（沿用老交互）；右上角个人入口（设置/足迹/管理页） |
| ChatApp 组件 | 会话侧栏（列表/新建/删除）+ 消息流 + 底部输入；SSE 打字机渲染；错误事件 toast；各对话应用仅 app_id 与开场白不同 |
| 打卡页 | 大卡片区：本周 7 圆点、连续天数、打卡按钮、今日小事卡、待办清单 |
| 心情页 | 三选一表情（好/一般/焦虑）+ 30 天圆点/日历热力 |
| 文献页 | 标签筛选 chips + 文献卡片流；详情抽屉：摘要中英对照、收藏、笔记编辑、AI 解读（缓存命中秒开） |
| 管理页 | 仅 admin 可见入口：用户/角色、Provider 与模型清单、应用绑定表单（system prompt 多行编辑 + 参数覆盖）、备份与任务配置 |
| 量表/呼吸 | 纯前端，移动优先大字号 |

---

## 8. 待确认问题清单

| # | 问题 | 默认决策（可先行） |
| --- | --- | --- |
| Q1 | 对话每日轮数上限是否保留？旧版有 `chat_daily_limit` | **默认保留机制**：上限做成应用绑定里的可配项，默认 0 = 不限（自部署两人场景通常无需限制） |
| Q2 | 上下文保留轮数（旧版 20 轮） | 默认沿用 20 轮，做成全局常量 |
| Q3 | 知识库 embedding 走哪个 Provider | 默认：复用 OpenAI 兼容 `/embeddings` 端点，绑定配置挂在 kb 应用绑定上；Provider 表单增加 `embedding` 能力标记 |
| Q4 | 旅行规划是否需要保存「生成的行程」为独立实体 | 默认不建表，行程即对话历史（与架构「仅提示词不同」一致） |
| Q5 | 量表速查的内容来源与更新方式 | 默认前端内置静态 JSON，发布即更新 |
| Q6 | 删除用户用软删除还是硬删除 | 默认软删除（保留数据可恢复，符合备份策略） |
| Q7 | 树洞等对话消息是否有保留期限/一键清空全部 | 默认：保留会话级清空（已有），不做全局自动清理 |
| Q8 | COS 同步备份是否本期做 | 默认不做（P2 可选） |

---

## 9. 附录：新旧映射

| 旧能力（old/） | 新去向 |
| --- | --- |
| 微信登录 + whitelist_users | 废弃 → 账号密码登录 + users/RBAC |
| 文献 crawler（pubmed esearch/efetch/打标/翻译回填） | 保留逻辑，迁入进程内定时任务 + `/automation` 接口 |
| LLM provider 抽象 + 用途路由 | 演进为 Provider + 模型清单 + **应用级绑定**（替代旧 routing） |
| 树洞 chat（SSE/会话/限流/标题生成） | 泛化为 ChatApp `/chat`（app_id 驱动） |
| space 设置 / 邀请码 / 危险操作双人确认 | space 设置 → 用户设置；邀请码废弃（注册开关替代）；双人确认本期不做（两人均为 admin，待确认） |
| 统计 footprint / storage | 接口不变，纳入 `/stats` |
| `miniprogram/`、`app_原型/` | 归档/参考，不迁移 |
