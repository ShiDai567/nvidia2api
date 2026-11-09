# nvidia2api all-in-one image: Django (127.0.0.1:8000, internal) + Next.js (:3000, only exposed port)

# Stage 1: build frontend standalone
FROM node:22-slim AS fe
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
# 确保 public 目录存在（Git 不跟踪空目录，frontend/public 可能为空）
RUN mkdir -p public && touch public/.gitkeep
RUN npm run build

# Stage 2: Python runtime (Django 6 requires Python 3.12+)
FROM python:3.12-slim-bookworm AS python-runtime

# Stage 3: runtime (Node for Next.js + Python for Django, same container)
FROM node:22-bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=python-runtime /usr/local /usr/local
COPY --from=ghcr.io/astral-sh/uv:0.11.11 /uv /uvx /bin/
WORKDIR /app
ENV PYTHONUNBUFFERED=1 DATA_DIR=/app/data

COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN cd backend && uv sync --frozen --no-dev --no-install-project
ENV PATH="/app/backend/.venv/bin:${PATH}"
COPY backend/ .

# Next.js standalone server + static assets
COPY --from=fe /fe/.next/standalone ./frontend
COPY --from=fe /fe/.next/static ./frontend/.next/static
COPY --from=fe /fe/public ./frontend/public

EXPOSE 3000
# Django listens on 127.0.0.1 only; Next.js (3000) is the single entry point.
# If Django dies, the whole container should restart (restart: unless-stopped).
CMD ["sh", "-c", "python3 manage.py migrate && python3 -m uvicorn config.asgi:application --host 127.0.0.1 --port 8000 & BACKEND_PID=$!; cd frontend && HOSTNAME=0.0.0.0 PORT=3000 node server.js & FRONT_PID=$!; trap 'kill $BACKEND_PID $FRONT_PID 2>/dev/null' TERM INT; wait -n $BACKEND_PID $FRONT_PID; exit 1"]
