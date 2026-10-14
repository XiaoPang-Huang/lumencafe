# 流光咖啡馆（LumenCafe）

自部署的两人 AI 应用面板。FastAPI + PostgreSQL + Caddy，打磨成熟后计划 MIT 开源。

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
docs/       架构定稿 v1、PRD v1、架构设计 v1
old/        旧版后端（本地参考，不入版本库）
```

详细设计见 [docs/架构定稿-v1.md](docs/架构定稿-v1.md)。
