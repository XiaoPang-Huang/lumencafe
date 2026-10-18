#!/usr/bin/env bash
# n8n 中文界面一键配置（服务器仓库根目录执行：bash deploy/n8n-zh-setup.sh）
#
# 流程：下载对应版本的汉化包 → sha256 校验 → 解压到 n8n-zh/dist → 带覆盖层重建 n8n
# 只替换前端构建产物（editor-ui/dist），不碰后端、数据库、工作流与凭据。
# 回滚英文：见 deploy/docker-compose.n8n-zh.yml 头部说明。
set -euo pipefail

cd "$(dirname "$0")/.."   # 仓库根目录

# 汉化包版本：必须与 docker-compose.yml 里的 n8n 镜像版本一致（升级 n8n 时同步改这里）
N8N_VER=2.43.5
ASSET="n8n-editor-ui@${N8N_VER}.tar.gz"
URL="https://github.com/bsi-bcp/n8n-i18n-chinese/releases/download/release/${N8N_VER}/${ASSET//@/%40}"
SHA256="97322489bf03508588589de18ba04c8ae66b4e77539ab85a71d18d12e1d815a3"

# 版本一致性检查：compose 里的镜像版本与汉化包版本对不上就中止，避免错配
COMPOSE_N8N=$(grep -oE 'n8nio/n8n:[0-9]+\.[0-9]+\.[0-9]+' docker-compose.yml | head -1 | cut -d: -f2 || true)
if [ "${COMPOSE_N8N}" != "${N8N_VER}" ]; then
  echo "版本不一致：compose 里 n8n 镜像是 ${COMPOSE_N8N:-未找到}，本脚本的汉化包是 ${N8N_VER}。"
  echo "请先同步改本脚本的 N8N_VER（并到 bsi-bcp/n8n-i18n-chinese 确认该版本已发布）。"
  exit 1
fi

mkdir -p n8n-zh

if [ ! -f n8n-zh/dist/index.html ]; then
  if [ ! -f "n8n-zh/${ASSET}" ]; then
    echo "==> 下载中文界面包 ${ASSET}（约 16MB，国内服务器直连 GitHub 可能很慢）"
    if ! curl -fL --noproxy '*' -C - --retry 3 --retry-delay 3 -o "n8n-zh/${ASSET}" "$URL"; then
      cat <<EOF
下载失败。请改从本机下载后上传：
  1. 本机浏览器打开：${URL}
  2. WinSCP/scp 上传到服务器：~/lumencafe/n8n-zh/${ASSET}
  3. 重新执行：bash deploy/n8n-zh-setup.sh
EOF
      exit 1
    fi
  fi
  echo "==> 校验完整性（sha256）"
  echo "${SHA256}  n8n-zh/${ASSET}" | sha256sum -c -
  rm -rf n8n-zh/dist
  echo "==> 解压到 n8n-zh/dist"
  tar -xzf "n8n-zh/${ASSET}" -C n8n-zh
fi

echo "==> 重建 n8n 容器（挂载中文界面）"
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml -f deploy/docker-compose.n8n-zh.yml up -d n8n

N8N_HOST=$(grep -E '^N8N_HOST=' .env 2>/dev/null | head -1 | cut -d= -f2 | tr -d '"'"'"'' || true)
echo ""
echo "完成。浏览器打开 http://${N8N_HOST:-<服务器IP>}:5678 （Ctrl+F5 强刷）验证中文界面。"
