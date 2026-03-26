# ── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

# Upgrade system packages to patch CVEs, then install build tools
RUN apt-get update \
    && apt-get dist-upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm

# Upgrade all system packages to pick up security patches
RUN apt-get update \
    && apt-get dist-upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy pre-built packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY server.py agent.py database.py ./

# Persistent volume for the SQLite database
VOLUME ["/data"]

# Environment variables (override at runtime via --env or .env file)
ENV OLLAMA_URL=http://host.docker.internal:8088 \
    MODEL_FAST=qwen3.5:9b \
    MODEL_SMART=qwen3.5:35b \
    DATABASE_URL=sqlite+aiosqlite:////data/research_data.db

EXPOSE 8050

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8050"]
