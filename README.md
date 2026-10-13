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

## 目录结构

```
backend/    FastAPI 后端（第一期：环境地基）
docs/       架构定稿 v1、PRD v1、架构设计 v1
old/        旧版后端（本地参考，不入版本库）
```

详细设计见 [docs/架构定稿-v1.md](docs/架构定稿-v1.md)。
