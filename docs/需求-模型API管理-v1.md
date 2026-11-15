# 需求 · 模型 & API 管理 v1（2026-11-15 拍板）

> 本文档是实施依据。改动须先与用户确认。
> 拍板来源：2026-11-15 会话四问（密钥存储 / MinerU 归属 / 权限语义 / 实施范围）。

## 1. 目标

管理后台新增「模型 & API 管理」模块，统一管理外部模型服务：官方 API、渠道套餐（tokenplan / agentplan 类）、MinerU 等第三方服务。管理员配供应商、拉模型、管启停、配权限；用户可自接个人模型。

## 2. 拍板决策（硬约束）

| # | 决策 | 内容 |
|---|---|---|
| R1 | 密钥加密入库 | 废除白皮书 v3 §03「密钥只进 .env 不入库」。后台配置的密钥 AES-256-GCM 加密存 PG，服务端用 `LC_SECRET_KEY`（.env，新增）scrypt 派生密钥；页面只显示脱敏提示（前 4 + 后 4）。个人模型同规则 |
| R2 | MinerU 纳入本模块 | 不另建 service_keys。MinerU 作为 protocol=mineru 的供应商统一管理（鉴权/启停/日志）；其模型不进对话选择器，供论文流水线用 |
| R3 | 可见范围 = 并集 | 用户可用模型 = 通用模型 ∪ 角色被授 ∪ 账号被授 ∪ 个人自接。管理员可见全部 |
| R4 | 一批交付 | 表 + 接口 + 后台页面 + 一键拉取 + 批量启停 + 连通测试 + 权限分配 + 个人接入 + 调用日志，一批做完 |

## 3. 三级结构

```
供应商 provider（谁：DeepSeek / Anthropic / MinerU…）
  └─ 渠道套餐 plan（哪条渠道：官方直连接口 / 某家 tokenplan 档位…）
       └─ 模型 model（哪个模型：deepseek-chat / claude-sonnet-4-5…）
```

- **供应商**管：协议（openai / anthropic / mineru）、接口地址、鉴权方式、启停。
- **套餐**管：渠道类型（official / tokenplan / agentplan / third_party）、套餐级密钥（可覆盖供应商级）、调用限制（RPM / 日额度）、熔断。
- **模型**管：启用、通用标记、价格、上下文参数、来源（手录 / 一键拉取）。
- 密钥可在供应商级或套餐级配置（套餐级优先）；MinerU 这类服务型供应商可无套餐直下挂模型。

## 4. 数据表（migration 0008，PG）

### 4.1 model_providers 供应商

| 列 | 类型 | 说明 |
|---|---|---|
| id | SERIAL PK | |
| name | TEXT NOT NULL | 显示名 |
| code | TEXT NOT NULL UNIQUE | 英文码（deepseek…），模型 ref 前缀 |
| protocol | TEXT NOT NULL CHECK IN ('openai','anthropic','mineru') | |
| base_url | TEXT NOT NULL | 接口地址，可含路径前缀 |
| auth_type | TEXT NOT NULL DEFAULT 'bearer' CHECK IN ('bearer','header','query','none') | 鉴权方式 |
| auth_config | JSONB NOT NULL DEFAULT '{}' | header 名/前缀/query 参数名等 |
| key_cipher | TEXT NOT NULL DEFAULT '' | AES-256-GCM 密文 |
| key_hint | TEXT NOT NULL DEFAULT '' | 脱敏提示 sk-a…z9 |
| enabled | BOOLEAN NOT NULL DEFAULT true | 启停 |
| scope | TEXT NOT NULL DEFAULT 'system' CHECK IN ('system','personal') | system=管理员建 / personal=用户自接 |
| owner_user_id | INTEGER NULL REFERENCES users(id) | personal 时归属 |
| remark | TEXT NOT NULL DEFAULT '' | |
| created_at / updated_at | TIMESTAMPTZ | |

### 4.2 model_plans 渠道套餐

| 列 | 类型 | 说明 |
|---|---|---|
| id | SERIAL PK | |
| provider_id | INTEGER NOT NULL REFERENCES model_providers(id) ON DELETE CASCADE | |
| name | TEXT NOT NULL | 套餐名 |
| plan_type | TEXT NOT NULL DEFAULT 'official' CHECK IN ('official','tokenplan','agentplan','third_party') | |
| base_url | TEXT NOT NULL DEFAULT '' | 非空时覆盖供应商地址 |
| key_cipher / key_hint | TEXT | 套餐级密钥（优先于供应商级） |
| rpm_limit | INTEGER NOT NULL DEFAULT 0 | 每分钟上限，0=不限 |
| daily_limit | INTEGER NOT NULL DEFAULT 0 | 每日调用上限，0=不限 |
| enabled | BOOLEAN NOT NULL DEFAULT true | |
| remark | TEXT NOT NULL DEFAULT '' | |
| created_at / updated_at | TIMESTAMPTZ | |

### 4.3 models 模型

| 列 | 类型 | 说明 |
|---|---|---|
| id | SERIAL PK | |
| plan_id | INTEGER NULL REFERENCES model_plans(id) ON DELETE CASCADE | mineru 类可空 |
| provider_id | INTEGER NOT NULL REFERENCES model_providers(id) ON DELETE CASCADE | 冗余方便查 |
| model_id | TEXT NOT NULL | 上游模型 id |
| ref | TEXT NOT NULL UNIQUE | 调用标识 `{code}/{model_id}`，conversations.model 存它 |
| display_name | TEXT NOT NULL | 选择器显示名 |
| enabled | BOOLEAN NOT NULL DEFAULT true | |
| is_common | BOOLEAN NOT NULL DEFAULT false | 通用模型（全员可用） |
| context_window / max_output_tokens | INTEGER NULL | |
| input_price / output_price | NUMERIC(12,6) NULL | 每百万 token 单价（元） |
| supports_tools | BOOLEAN NOT NULL DEFAULT false | |
| source | TEXT NOT NULL DEFAULT 'manual' CHECK IN ('manual','fetched') | |
| fetched_at | TIMESTAMPTZ NULL | 一键拉取时间 |
| created_at / updated_at | TIMESTAMPTZ | |

UNIQUE(provider_id, model_id)。

### 4.4 model_grants 模型授权

| 列 | 类型 | 说明 |
|---|---|---|
| id | SERIAL PK | |
| model_id | INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE | |
| grantee_type | TEXT NOT NULL CHECK IN ('role','user') | |
| grantee | TEXT NOT NULL | role: admin/member；user: users.id |
| created_at | TIMESTAMPTZ | |

UNIQUE(model_id, grantee_type, grantee)。通用模型（is_common）无需行。

### 4.5 llm_call_logs 调用日志

| 列 | 类型 | 说明 |
|---|---|---|
| id | BIGSERIAL PK | |
| model_id / plan_id / provider_id | INTEGER | 调用时快照 |
| user_id | INTEGER NOT NULL | 谁调的 |
| app | TEXT NOT NULL DEFAULT 'chat' | chat / money / papers / agent… |
| conversation_id | TEXT NOT NULL DEFAULT '' | 应用内会话（SQLite id） |
| prompt_tokens / completion_tokens | INTEGER NULL | 上游回报才记 |
| cost_fen | INTEGER NOT NULL DEFAULT 0 | 费用=token×单价，算不出记 0 |
| latency_ms | INTEGER NOT NULL DEFAULT 0 | |
| status | TEXT NOT NULL CHECK IN ('ok','failed','stopped') | |
| error_code / error_msg | TEXT NOT NULL DEFAULT '' | 失败原因 |
| created_at | TIMESTAMPTZ | |

索引：(model_id, created_at)、(user_id, created_at)、(created_at)。

## 5. 接口（全部走网关鉴权）

### 5.1 管理端（requireAdmin）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/models/tree | 供应商→套餐→模型 全树 |
| POST | /api/models/providers | 建供应商 |
| PATCH | /api/models/providers/:id | 改（含换密钥：key_cipher 重加密、key_hint 更新） |
| DELETE | /api/models/providers/:id | 删（级联套餐/模型/授权/日志保留 model_id 快照） |
| POST | /api/models/providers/:id/test | 连通性测试 |
| POST | /api/models/plans | 建套餐 |
| PATCH | /api/models/plans/:id | 改 |
| DELETE | /api/models/plans/:id | 删 |
| POST | /api/models/fetch | { provider_id } 一键拉模型（OpenAI: GET {base}/models；Anthropic: GET {base}/v1/models；MinerU: GET 健康端点）。已存在按 ref 更新 display_name/source/fetched_at，不覆盖手改的名称/价格/启停/通用标记 |
| PATCH | /api/models/:id | 改启用/通用/价格/参数 |
| POST | /api/models/batch | { ids, op: 'enable'/'disable' } |
| DELETE | /api/models/:id | 删模型 |
| PUT | /api/models/:id/grants | 整替授权 [{type:'role'|'user', grantee}] |
| GET | /api/models/logs?model_id=&user_id=&limit=50 | 调用日志 |

### 5.2 个人模型（登录即可，scope 隔离）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/models/mine | 我的供应商/套餐/模型 |
| POST | /api/models/mine/providers | 自接供应商 |
| PATCH | /api/models/mine/providers/:id | 改/换密钥/启停 |
| DELETE | /api/models/mine/providers/:id | 删 |
| POST | /api/models/mine/providers/:id/test | 连通测试 |
| POST | /api/models/mine/fetch | 拉模型（同 5.1 规则） |

后端强制 owner_user_id=当前用户，越权 404（不暴露存在性）。

### 5.3 前台（改写）

`GET /api/chat/models` 改为按 R3 并集过滤：通用 ∪ 当前用户角色 ∪ 当前用户 ∪ 个人自接；只返回 enabled 且供应商/套餐链全启用的模型。`default_model` = 第一个通用模型，无则第一个可见模型。faux 假模型保留：库中无任何可用模型时兜底（开发环境）。

## 6. llm.mjs 网关改造

- 启动 `initModels()`：读库构建 pi-ai provider（`createProvider`），openai 协议用 `openAICompletionsApi()`、anthropic 用 `anthropicMessagesApi()`；auth.resolve 从库解密取 key；base_url 取套餐覆盖值。
- 管理员改配置后 `reloadModels()` 重建注册表（内存操作，毫秒级）。
- 调用链：resolveModel → 套餐级限流（RPM 滑动窗口 + 日额度，超限抛「渠道繁忙，请稍后再试」）→ 熔断检查（同套餐连续失败 5 次熔断 60s，半开试探）→ pi-ai 流式 → 记 llm_call_logs（token 上游回报则计费 cost_fen = prompt/1M×input_price + completion/1M×output_price）。
- MinerU provider 注册但不进对话解析；论文流水线改从本模块读 key（替代 .env 直读，.env 值保留为兜底）。

## 7. 后台页面

#/admin 加「模型 & API」区块（抄 one-api 信息密度）：
- 供应商卡列表：名/协议徽标/地址/密钥提示/启停开关/测试/编辑/删除；「+ 供应商」。
- 套餐行（供应商下可展开）：类型徽标/限额/启停/编辑/删除。
- 模型表：勾选框/名称/ref/协议/价格/来源/通用开关/启用开关/授权数；顶部「一键获取模型」（按选中供应商）、批量启用/停用。
- 授权弹窗：角色复选（管理员/成员）+ 账号多选（users 下拉多选）。
- 调用日志卡：最近 50 条（模型/用户/状态/token/费用/延迟/错误）。

#/me 通用设置弹窗加「我的模型」区块：自接供应商列表 + 添加（名/协议/地址/密钥）+ 测试 + 拉模型；我的模型启停。

## 8. 连通性测试

按协议发最小请求：openai → GET {base}/models（bearer）；anthropic → GET {base}/v1/models（x-api-key + anthropic-version: 2023-06-01）；mineru → GET {base}/ 或健康检查。返回 { ok, latency_ms, models_count?/http_status, error? }；不通过时把错误透传给页面。密钥不落日志。

## 9. 异常处理

- 拉模型失败：返回上游 status+message，日志记 provider 级，不中断其他供应商。
- 调用失败：写 llm_call_logs(failed) + 熔断计数；页面三态（白皮书 §08）不变。
- 密钥缺失/解密失败：调用时报「渠道未配置密钥」，日志记 error_code='no_key'。
- 限流/熔断：明确文案，不当作模型故障。

## 10. 影响面

- 新表 5 张（0008）；新接口文件 src/api/models.mjs；llm.mjs 重写注册与路由；chat.mjs 模型列表改库读。
- admin.js 加模型区块；app.js「我的」加个人模型；chat.js 无需改（选择器数据源接口不变）。
- MinerU key 读取点改造（papers pipeline 走本模块，.env 兜底）。
- .env.example 加 LC_SECRET_KEY；白皮书 §03「密钥只进 .env」作废（R1）。
- 集成测试新增 models 用例；faux 兜底保证无 key 环境全链路可跑。

## 11. 风险

- pi-ai createProvider 动态注册的稳定性 → 首批只接 openai/anthropic 两协议，faux 兜底。
- 密钥安全 → AES-GCM + scrypt 派生；LC_SECRET_KEY 泄漏等于全部密钥泄漏（.env 保护好，推送红线已覆盖）。
- 性能 → 模型注册表内存常驻；限流熔断均内存态；日志写表异步不阻塞响应。
