#!/bin/sh
# 流光咖啡馆 · restic 本机备份（底座步 4，2026-10-25 拍板）
#
# 备份内容：
#   1) pg_dump -Fc（备份容器内经 compose 网络直连 db:5432，官方 pg_dump 18）
#   2) ./skills 技能库（只读挂载 /skills）
# 加密：RESTIC_PASSWORD（.env 注入，restic 仓库级 AES 加密）
# 调度：容器内 sh 循环 24h（2 人规模不引 cron 守护）；手动触发/验收：
#       docker compose run --rm backup --once
# 状态：每轮写 /state/last_run.json {succeeded, at, error}（成功/失败都写），
#       api 容器经 backup_state 卷只读读取 → GET /api/status 状态灯数据源。
set -u

export RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-/repo}"
STATE_FILE="${BACKUP_STATE_FILE:-/state/last_run.json}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"

log() { echo "[backup $(date -u +"%Y-%m-%dT%H:%M:%SZ")] $*"; }

# JSON 字符串转义 + 截断（错误信息仅作展示，不追求完整）
json_escape() {
  printf '%s' "$1" | tr -d '\r\n' | sed 's/\\/\\\\/g; s/"/\\"/g' | cut -c1-500
}

# $1 = true|false；$2 = 错误信息（空 = 成功）
write_state() {
  ok="$1"; err="$2"
  if [ "$ok" = "true" ]; then
    err_json="null"
  else
    err_json="\"$(json_escape "$err")\""
  fi
  at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  tmp="${STATE_FILE}.tmp"
  printf '{"succeeded": %s, "at": "%s", "error": %s}\n' "$ok" "$at" "$err_json" > "$tmp"
  mv "$tmp" "$STATE_FILE"
  log "last_run.json ← succeeded=$ok at=$at"
}

run_once() {
  log "===== 备份开始（pg_dump + skills → restic）====="
  work="$(mktemp -d)"
  err=""

  # 1) pg_dump（-Fc 自定义格式，恢复走 pg_restore）
  if ! pg_dump -Fc -h "${PGHOST:-db}" -p "${PGPORT:-5432}" -U "${PGUSER:-lumencafe}" \
         -d "${PGDATABASE:-lumencafe}" -f "$work/db.dump" 2>"$work/pg.err"; then
    err="pg_dump 失败：$(tail -n 2 "$work/pg.err")"
  # 2) restic 加密备份（内容寻址去重，重复跑增量）
  elif ! restic backup --tag auto "$work/db.dump" /skills 2>&1 | tail -n 5; then
    err="restic backup 失败（见上方日志）"
  # 3) 保留策略：日备 7 份 + 周备 4 份，prune 立即释放空间
  elif ! restic forget --keep-daily 7 --keep-weekly 4 --prune 2>&1 | tail -n 5; then
    err="restic forget/prune 失败（见上方日志）"
  fi

  if [ -n "$err" ]; then
    log "备份失败：$err"
    write_state false "$err"
  else
    log "备份完成"
    write_state true ""
  fi
  rm -rf "$work"
}

# 初始化 repo（幂等：cat config 成功 = 已初始化，跳过）
if ! restic cat config >/dev/null 2>&1; then
  log "初始化 restic 仓库..."
  if ! restic init; then
    log "FATAL: restic init 失败（RESTIC_PASSWORD 与既有仓库不匹配？）"
    exit 1
  fi
fi

if [ "${1:-}" = "--once" ]; then
  run_once
else
  log "进入循环调度（间隔 ${INTERVAL}s；docker compose run --rm backup --once 手动跑一轮）"
  while true; do
    run_once
    sleep "$INTERVAL"
  done
fi
