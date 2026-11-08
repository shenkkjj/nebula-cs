# Nebula CS — lite portal for Render Free (~512MB). No Dify Docker.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LITE_MODE=1 \
    PORTAL_HOST=0.0.0.0 \
    PORT=8787

WORKDIR /app

# Copy only what the lite portal needs (skip design shot PNGs).
COPY requirements.txt ./
COPY server/ ./server/
COPY web/ ./web/
COPY sample-kb/ ./sample-kb/
COPY ENGINE.txt README.md ./

# No pip packages required; touch install for clarity / future deps.
RUN pip install --no-cache-dir -r requirements.txt || true

EXPOSE 8787

# Render injects $PORT; proxy.py honors PORT and binds 0.0.0.0.
CMD ["python3", "server/proxy.py"]
