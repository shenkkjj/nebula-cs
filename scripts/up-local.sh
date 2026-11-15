#!/usr/bin/env bash
# One command for the local demo: Ollama check, Dify compose if present, then the gateway.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "已从 .env.example 生成 .env。请填入 DIFY_APP_API_KEY 后再问办事问题。"
fi

if command -v ollama >/dev/null 2>&1; then
  echo "Ollama: $(ollama --version 2>/dev/null || true)"
  if ! ollama list 2>/dev/null | grep -q "bge-m3"; then
    echo "未看到 bge-m3。在这台机器上执行：ollama pull bge-m3"
  fi
else
  echo "未安装 ollama。嵌入模型要在宿主机安装 Ollama 并拉取 bge-m3，Dify 才能用它做向量。"
fi

DIFY_HOME="${DIFY_HOME:-}"
if [[ -z "$DIFY_HOME" && -d /workspace/dify/docker ]]; then
  DIFY_HOME=/workspace/dify
elif [[ -z "$DIFY_HOME" && -d "$ROOT/../dify/docker" ]]; then
  DIFY_HOME="$(cd "$ROOT/../dify" && pwd)"
fi

if [[ -n "$DIFY_HOME" && -f "$DIFY_HOME/docker/docker-compose.yaml" ]]; then
  echo "启动 Dify：$DIFY_HOME/docker"
  (cd "$DIFY_HOME/docker" && docker compose up -d)
else
  echo "没有找到 Dify 1.19.0 的 docker 目录。"
  echo "把官方仓库放到 /workspace/dify，或设置 DIFY_HOME 后重跑本脚本。"
  echo "网关仍会启动。自检失败时，门户显示「知识库维护中」。"
fi

docker compose up -d --build
echo "门户 http://127.0.0.1:8080/  坐席 /agent  后台 /admin  登录 /login"
