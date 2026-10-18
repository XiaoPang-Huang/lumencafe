# 流光咖啡馆（LumenCafe）

自部署的两人 AI 应用面板。FastAPI + PostgreSQL + Caddy，打磨成熟后计划 MIT 开源。

> **协作硬性规定**：所有界面设计必须先搜索并参考业界成功案例（火山方舟控制台、LobeChat、Supabase、midday 等），禁止凭感觉自行设计。详见 [AGENTS.md](AGENTS.md)。

## 快速开始（本地）

```bash
cp .env.example .env   # 修改其中的密码与密钥
docker compose up -d --build
```

- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

注意：
- **compose 运行必须提供 `.env`**。缺失时 api 容器会因连不上数据库而重启循环（默认 `LUMEN_DATABASE_URL` 面向本机 venv 开发，指向 localhost）。
- `POSTGRES_PASSWORD` 含 `$` `#` 等特殊字符时，`.env` 里的值要用单引号包住，如 `POSTGRES_PASSWORD='a@b#c$d'`。
- Alembic 迁移在 api 容器启动时自动执行（`alembic upgrade head`）。

## 服务器部署

一台 2核4G VPS 即可，Caddy 自动 HTTPS。完整步骤见 [docs/部署指南-v1.md](docs/部署指南-v1.md)，核心三步：

```bash
git clone <仓库地址> lumencafe && cd lumencafe
cp .env.example .env   # 改 JWT_SECRET / POSTGRES_PASSWORD / LUMEN_INTERNAL_TOKEN；Caddyfile 改三处域名
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
```

部署形态：`cafe.域名` 主站（前端 + /api 同域反代）、`api.域名` 外部客户端、`n8n.域名` 工作流控制台（可选）。

## n8n 中文界面（可选）

n8n 镜像版本已锁定，中文界面包版本必须与之一致（当前 n8n `2.43.5`）：

```bash
mkdir -p n8n-zh && curl -sL -o n8n-zh/pkg.tar.gz \
  "https://github.com/bsi-bcp/n8n-i18n-chinese/releases/download/release/2.43.5/n8n-editor-ui%402.43.5.tar.gz" \
  && tar -xzf n8n-zh/pkg.tar.gz -C n8n-zh
docker compose up -d n8n
```

来源：github.com/bsi-bcp/n8n-i18n-chinese（MIT）。升级 n8n 前先确认该仓库是否已跟进对应版本的汉化包，跨版本错配会回退英文甚至白屏。

## 目录结构

```
backend/    FastAPI 后端（第一期：环境地基）
docs/       架构定稿 v1、PRD v1、架构设计 v1、团队协作规范 v1
old/        旧版后端（本地参考，不入版本库）
prototype/  前端交互原型（纯 HTML/CSS/JS，v2 见 prototype/v2/，本地起任意静态服务即可预览）
```

找不到要改的文件？先看 [docs/项目地图-v1.md](docs/项目地图-v1.md)（或浏览器打开 `docs/项目地图.html`，可搜索、点选复制路径）。

详细设计见 [docs/架构定稿-v1.md](docs/架构定稿-v1.md)。
