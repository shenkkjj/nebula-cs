#!/usr/bin/env bash
# Default product: self-built campus knowledge base. No Dify, no Ollama.
# Vector search needs: pip install -r requirements-campus.txt
# Without that package the process still answers from the BM25 index.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "已从 .env.example 生成 .env。DEEPSEEK_API_KEY 可以先留空，办事问答仍按知识库原文回答。"
fi

export ENGINE=campus
unset LITE_MODE
export PORTAL_HOST="${PORTAL_HOST:-127.0.0.1}"
export PORTAL_PORT="${PORTAL_PORT:-8080}"

exec python3 server/proxy.py
