# 生产部署说明（2026-11-14 第 0 批收尾补）

服务器只装 docker engine（+ compose 插件），不装 Node、不装数据库，环境干净（拍板见 `docs/白皮书-v3.md` §15-5）。

## 首次部署

```bash
# 1. 服务器上克隆代码
git clone https://github.com/XiaoPang-Huang/lumencafe.git && cd lumencafe

# 2. 建 deploy/.env（已被 .gitignore 覆盖，不入库），两个变量：
cat > deploy/.env <<'EOF'
POSTGRES_PASSWORD=换成强口令
STORAGE_DRIVER=local
EOF

# 3. 构建并启动三件套（Caddy + 主程序 + PG）
docker compose -f deploy/compose.yml up -d --build

# 4. 看主程序日志：PG migration 自动跑完，打印主人登录链接（一次性，10 分钟有效）
docker compose -f deploy/compose.yml logs app
```

浏览器打开 `https://服务器IP`（自签证书，首次访问浏览器会提示风险，点继续访问），用第 4 步打印的主人链接登录。

## 发版

```bash
git pull
docker compose -f deploy/compose.yml up -d --build app   # 只改代码走镜像缓存，很快
```

migration 随主程序启动自动执行；回退 = `git checkout <旧提交>` 后重复上面两条。

## 备份（白皮书 §15-5 要求，落地前 TODO）

SQLite（appdata 卷）+ PG（pgdata 卷）定时备份到 COS，脚本待写；落地前生产数据有风险，尽快补。

## 待办

- [ ] 首次 build 后回填基础镜像 digest 钉死（Dockerfile 的 node、compose 的 caddy/pg，见白皮书 §14 供应链纪律）
- [ ] 服务器实测本 compose（本地已 `compose config` 校验语法，镜像构建需 docker 能访问 registry）
- [ ] 备份脚本（见上）
