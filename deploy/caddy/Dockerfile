# 自定义 Caddy：内置 DNSPod DNS-01 插件（github.com/caddy-dns/dnspod）
#
# 背景（2026-10-18）：域名未做 ICP 备案时，腾讯云拦截 80/443 端口。
# - 访客侧：80/443 进不来 → 站点改用 8443 端口提供服务（见 Caddyfile）
# - 证书侧：Let's Encrypt 只在 80（HTTP-01）/ 443（TLS-ALPN-01）验证，
#   换端口救不了证书 → 改用 DNS-01：经 DNSPod API 自动加 TXT 记录验证，
#   完全不依赖入站端口
#
# 需要 .env 配置 DNSPOD_TOKEN（格式「令牌ID,令牌Key」）。
#
# 备案通过后撤销本方案：删掉本目录 → docker-compose.yml 的 caddy 改回
# image: caddy:2-alpine → Caddyfile 删 (dns_tls) 片段及各处 import →
# .env 删 DNSPOD_TOKEN → up -d --build。详见 docs/部署指南-v1.md §1.1。

FROM caddy:2-builder AS builder

# 国内网络默认走 goproxy.cn 镜像拉 Go 模块；海外可构建时覆盖为官方源
ARG GOPROXY=https://goproxy.cn,direct

RUN xcaddy build --with github.com/caddy-dns/dnspod

FROM caddy:2-alpine

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
