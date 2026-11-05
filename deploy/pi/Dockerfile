# pi-runner 基础镜像（步 1：最小验证）
# 以 Pi 官方容器化文档的 Dockerfile.pi 为基础（packages/coding-agent/docs/containerization.md，
# 仓库 earendil-works/pi-mono），按项目供应链纪律改动两点：
#   1. pi-coding-agent 锁精确版本 @1.5.0（官方示例未锁，违反禁 latest 纪律）；
#   2. 追加 curl（官方镜像不含任何下载工具，步 1 验收「抓网页存 markdown」需要）。
FROM node:24-bookworm-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends bash ca-certificates git ripgrep curl \
  && rm -rf /var/lib/apt/lists/*
RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent@1.5.0

WORKDIR /workspace
ENTRYPOINT ["pi"]
