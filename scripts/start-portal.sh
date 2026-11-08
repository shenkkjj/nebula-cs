#!/usr/bin/env bash
# 启动星云客服自研门户（默认 127.0.0.1:8787）
# LITE_MODE=1 时不需要 Dify / API Key（适合 Render 同款轻量模式本地试跑）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PORTAL_HOST="${PORTAL_HOST:-127.0.0.1}"
export PORTAL_PORT="${PORTAL_PORT:-8787}"
export DIFY_CHAT_URL="${DIFY_CHAT_URL:-http://127.0.0.1/v1/chat-messages}"
export DIFY_APP_API_KEY_FILE="${DIFY_APP_API_KEY_FILE:-/tmp/dify-app-api-key.txt}"

LITE="${LITE_MODE:-0}"
LITE_LC="$(echo "$LITE" | tr '[:upper:]' '[:lower:]')"

if [[ "$LITE_LC" != "1" && "$LITE_LC" != "true" && "$LITE_LC" != "yes" && "$LITE_LC" != "on" ]]; then
  if [[ -z "${DIFY_APP_API_KEY:-}" && ! -f "$DIFY_APP_API_KEY_FILE" ]]; then
    echo "错误：找不到应用 API Key。"
    echo "请设置 DIFY_APP_API_KEY，或把 Key 写入 $DIFY_APP_API_KEY_FILE"
    echo "或：LITE_MODE=1 bash $0   # 本地 FAQ 轻量模式（无 Dify）"
    exit 1
  fi
  if command -v ss >/dev/null 2>&1; then
    if ss -ltn "sport = :${PORTAL_PORT}" 2>/dev/null | grep -q ":${PORTAL_PORT}"; then
      echo "端口 ${PORTAL_PORT} 已被占用。可先：kill \$(lsof -t -iTCP:${PORTAL_PORT} -sTCP:LISTEN) 或换 PORTAL_PORT。"
      exit 1
    fi
  fi
  if ! curl -sf -o /dev/null --max-time 2 "http://127.0.0.1/" ; then
    echo "警告：本机 http://127.0.0.1/ 暂不可达。请先启动 Dify：/workspace/dify/start.sh"
  fi
else
  export LITE_MODE=1
  echo "LITE_MODE=1 — 使用本地 FAQ（sample-kb），不连接 Dify"
fi

if command -v ss >/dev/null 2>&1; then
  if ss -ltn "sport = :${PORTAL_PORT}" 2>/dev/null | grep -q ":${PORTAL_PORT}"; then
    echo "端口 ${PORTAL_PORT} 已被占用。可换 PORTAL_PORT。"
    exit 1
  fi
fi

echo "启动门户 → http://${PORTAL_HOST}:${PORTAL_PORT}/"
exec python3 "$ROOT/server/proxy.py"
