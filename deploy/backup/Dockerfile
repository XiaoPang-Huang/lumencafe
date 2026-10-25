# syntax=docker/dockerfile:1
# 流光咖啡馆 · 备份镜像（底座步 4，2026-10-25）
#
# 底座 = restic 官方镜像（tag@digest 锁定，D6）+ 从本项目已锁 digest 的 postgres
# 镜像复制官方 pg_dump 18 及其全部依赖库。
#
# 为什么不 apk 安装 pg 客户端：Alpine 源内的 postgresql-client 主版本低于服务器
# 时直接拒绝工作（实测 PG16 客户端对 PG18 服务器：server version mismatch）。
# 复制的二进制与库来自 docker-compose.yml db 服务**同 digest** 的 postgres 镜像
# （同为 Alpine 3.24 分支，ABI 完全匹配），版本随 digest 锁定，无浮动源（D6）。
#
# D14 选型与加固（trivy 三版本对比实测，见依赖锁定清单 §5.3）：
#   - restic 0.17.3/0.18.1：openssl 3.3.x 带 4 条可修 CRITICAL（Alpine 3.20 分支
#     已 EOL，容器内无可升级形态）且 Go 构建内嵌旧 stdlib/x-crypto 大量可修 HIGH；
#     0.19.1（Alpine 3.24）可修面最小，故底座取 0.19.1。
#   - 移除镜像自带但本部署不用的 openssh-client*/jq（备份走本地 repo，无 ssh/sftp
#     面；步 2「镜像自带包清理」同款处置，openssh 可修 CRITICAL 随之清零）。
#   - libcrypto3/libssl3 精确锁到 alpine v3.24 分支仓库的修复版（版本号写死，
#     源内该版被移除时构建响亮失败，不静默漂移）。
# 残余（restic 二进制内嵌 Go stdlib/x-net 等可修 HIGH，全生态无容器内修复形态）：
# 按 v2.4 先例接受 + 挂跟修触发器（restic 发新版重建）。
#
# 升级任一侧基础镜像 → 按 D13 影响面评估后改本文件 + 依赖锁定清单 §5。
#
# 构建：docker compose build backup

# 已锁 digest 的 postgres 镜像（docker-compose.yml db 服务同款，见依赖锁定清单 §5）
FROM postgres:18-alpine@sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873 AS pg

# restic 官方镜像（0.19.1：Alpine 3.24；三版本 trivy 对比可修面最小，论证见上）
FROM restic/restic:0.19.1@sha256:136600b6ff6843d61d355f7f71f460a166429f35de6fd11b568fece3c9a4d510

# D14 加固：移除不用的 openssh-client/jq + 精确锁 openssl 修复版
RUN apk del --no-cache openssh-client-default openssh-client-common openssh-keygen jq \
 && apk add --no-cache libcrypto3=3.5.9-r0 libssl3=3.5.9-r0

# pg_dump 18 + 依赖库（ldd 实测清单，全部来自 postgres 镜像层，版本随其 digest 锁定）
COPY --from=pg /usr/local/bin/pg_dump /usr/local/bin/pg_dump
COPY --from=pg /usr/local/lib/libpq.so.5 /usr/local/lib/libpq.so.5
COPY --from=pg \
    /usr/lib/libzstd.so.1 \
    /usr/lib/liblz4.so.1 \
    /usr/lib/libcrypto.so.3 \
    /usr/lib/libz.so.1 \
    /usr/lib/libssl.so.3 \
    /usr/lib/libgssapi_krb5.so.2 \
    /usr/lib/libldap.so.2 \
    /usr/lib/libkrb5.so.3 \
    /usr/lib/libk5crypto.so.3 \
    /usr/lib/libcom_err.so.2 \
    /usr/lib/libkrb5support.so.0 \
    /usr/lib/liblber.so.2 \
    /usr/lib/libsasl2.so.3 \
    /usr/lib/libkeyutils.so.1 \
    /usr/lib/
