# pi-runner 镜像（步 3 沙箱 + 步 4 MCP 生态）——build context = 仓库根。
# 基础层 = 步 1 已验证的官方 Dockerfile.pi 衍生层（锁 pi-coding-agent@1.5.0 + curl）。
FROM lumencafe-pi:1.5.0

# apt 走清华镜像（国内构建加速；服务器/CI 可用构建参数覆盖回官方源）
ARG APT_MIRROR=mirrors.tuna.tsinghua.edu.cn
RUN sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

# paper-search-mcp 是 Python MCP server：装 python3 + uv（锁版本）。
# bookworm 系 externally-managed 环境须 --break-system-packages。
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 python3-pip \
  && rm -rf /var/lib/apt/lists/* \
  && pip3 install --break-system-packages --no-cache-dir --index-url=${PIP_INDEX_URL} uv==0.13.7

# Playwright MCP（锁版本）+ 容器内 headless chromium 及其系统依赖。
# 浏览器二进制走 npmmirror 镜像（国内加速）；沙箱里 chrome 沙箱不可用，
# 运行时由 mcp.json 带 --no-sandbox（read_only + no-new-privileges 下必须）。
RUN npm install -g --ignore-scripts @playwright/mcp@0.0.84 \
  && PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright npx playwright install --with-deps chromium
# 版本兼容：@playwright/mcp@0.0.84 自带的 playwright-core 期望 chromium-1252，
# 而 npx playwright install 按当前解析版下载 1254。镜像层预置同名软链，
# 避免运行时在只读根文件系统里临时修补（2026-11-07 browser-002 实测排障）。
RUN ln -s chromium-1254 /root/.cache/ms-playwright/chromium-1252 \
  && ln -s chromium_headless_shell-1254 /root/.cache/ms-playwright/chromium_headless_shell-1252
# Playwright MCP 的运行时目录 ~/.cache/ms-playwright-mcp 不在镜像层预置：
# compose 已单独挂可写 tmpfs（docker-compose.yml），避免只读根文件系统拦截 mkdir。

WORKDIR /app
COPY pi-runner/package.json pi-runner/package-lock.json ./
# 锁版本安装（对齐 backend 的 lockfile 纪律；--ignore-scripts 延续基础层供应链策略）
RUN npm ci --omit=dev --ignore-scripts
COPY pi-runner/server.js ./

ENV PORT=8787 \
    OUTPUT_DIR=/output \
    WORKSPACE_DIR=/workspace \
    UV_CACHE_DIR=/tmp/uv-cache \
    NPM_CONFIG_CACHE=/tmp/npm-cache \
    XDG_CONFIG_HOME=/tmp/.config \
    XDG_CACHE_HOME=/tmp/.cache \
    XDG_DATA_HOME=/tmp/.local/share \
    XDG_STATE_HOME=/tmp/.local/state \
    PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright
EXPOSE 8787
ENTRYPOINT ["node", "server.js"]
