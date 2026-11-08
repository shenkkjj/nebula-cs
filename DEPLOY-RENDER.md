# Deploy 星云客服（Lite）to Render Free — no card

## Why lite?

Render **Free** web services have ~**512MB RAM**. Full **Dify Docker** (API + worker + DB + Redis + weaviate/…) will **not** fit.  
This deploy keeps the **E5 portal UX** (`web/`) and runs a **lite engine**: local FAQ retrieval + optional DeepSeek, or template answers from FAQ snippets.

## What works on Free

| Feature | Lite on Render |
|---------|----------------|
| E5 portal UI, chips, citations, multi-turn history | Yes |
| FAQ QA with citations (CloudCup Pro sample) | Yes (local `sample-kb/`) |
| Empty-retrieval refuse | Yes |
| Query rewrite / 转人工 / order stub | Yes (same proxy Agent layer) |
| DeepSeek polished answers | Yes if you set `DEEPSEEK_API_KEY` in Render |
| Full Dify Chatflow / control plane | **No** (use local box for that) |

## Free-tier caveats

- **No credit card** needed for Render Free signup (as of common Free plan; confirm on render.com).
- Free web services **spin down after ~15 minutes** of idle. First request after sleep can take **30–60s** (cold start).
- Public URL looks like `https://nebula-cs.onrender.com` (name may vary).

## Deploy steps (after GitHub connected)

1. Push this repo (parent agent will push once Render auth is ready). **Do not commit secrets.**
2. In Render: **New → Blueprint** → select the repo → apply `render.yaml`.  
   Or **New → Web Service** → Docker → root directory with this `Dockerfile`.
3. Plan: **Free**. Health check: `/api/health`.
4. Env (Blueprint sets most):
   - `LITE_MODE=1` (required)
   - `DEEPSEEK_API_KEY` (optional, dashboard secret)
5. Open the service URL → ask「保修政策是怎样的？」→ expect 12/6 months + citations.

## Local smoke (lite)

```bash
# from the repo root
LITE_MODE=1 PORTAL_PORT=8799 DEEPSEEK_API_KEY=... python3 server/proxy.py
# other terminal:
curl -s http://127.0.0.1:8799/api/health
curl -s -X POST http://127.0.0.1:8799/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"query":"保修政策是怎样的？","stream":false}'
```

## Rollback / full Dify

On the course box, leave `LITE_MODE` unset and start Dify + `scripts/start-portal.sh` as before. Lite and Dify share the same `web/` portal.
