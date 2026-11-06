# pi-runner 镜像（步 2：薄层服务）——复用步 1 已验证的基础层，再装服务依赖。
# 基础层 = 官方 Dockerfile.pi（锁 pi-coding-agent@1.5.0 + curl，见 deploy/pi/Dockerfile）。
FROM lumencafe-pi:1.5.0

WORKDIR /app
COPY package.json package-lock.json ./
# 锁版本安装（对齐 backend 的 lockfile 纪律；--ignore-scripts 延续基础层供应链策略）
RUN npm ci --omit=dev --ignore-scripts
COPY server.js ./

ENV PORT=8787 \
    OUTPUT_DIR=/output \
    WORKSPACE_DIR=/workspace
EXPOSE 8787
ENTRYPOINT ["node", "server.js"]
