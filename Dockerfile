# 流光咖啡馆 · 主程序镜像（2026-11-14 第 0 批收尾补）
# 基础镜像钉精确版本（升级走影响面评估流程，见 docs/白皮书-v3.md §14）
FROM node:24.22.3-bookworm-slim

WORKDIR /app

# 先拷依赖清单，充分利用镜像层缓存；npm ci 严格按 lockfile 装，可复现
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

# 再拷运行所需代码（插件、迁移、前端静态文件都在 src/static）
COPY src ./src
COPY plugins ./plugins
COPY migrations ./migrations

ENV NODE_ENV=production \
    PORT=8480
EXPOSE 8480

# 启动即自动跑未执行的 PG migration（fail fast：连不上 PG 直接退出）
CMD ["node", "src/server.mjs"]
