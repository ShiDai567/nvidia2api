# nvidia2api all-in-one image: Django (127.0.0.1:8000, internal) + Next.js (:3000, only exposed port)

# CI 可覆盖为镜像缓存前缀；本地默认从 Docker Hub 拉取。
ARG DOCKERHUB_PREFIX=docker.io/library

# Stage 1: build frontend standalone
FROM ${DOCKERHUB_PREFIX}/node:22-slim AS fe
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
# 确保 public 目录存在（Git 不跟踪空目录，frontend/public 可能为空）
RUN mkdir -p public && touch public/.gitkeep
RUN npm run build

# Stage 2: Python runtime (Django 6 requires Python 3.12+)
FROM ${DOCKERHUB_PREFIX}/python:3.12-slim-bookworm AS python-runtime

# Stage 3: runtime (Node for Next.js + Python for Django, same container)
FROM ${DOCKERHUB_PREFIX}/node:22-bookworm-slim
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
# Django 仅监听内部地址，Next.js 的 3000 端口作为统一入口。
# Debian 的 sh 不支持 wait -n；使用 Bash 监控两个服务并转发停止信号。
# 迁移成功后才启动服务；任一服务退出时清理另一服务并以失败状态退出。
CMD ["bash", "-c", "python3 manage.py migrate || exit 1; python3 -m uvicorn config.asgi:application --host 127.0.0.1 --port 8000 & BACKEND_PID=$!; (cd frontend && exec env HOSTNAME=0.0.0.0 PORT=3000 node server.js) & FRONT_PID=$!; cleanup() { kill $BACKEND_PID $FRONT_PID 2>/dev/null || true; wait $BACKEND_PID $FRONT_PID 2>/dev/null || true; }; trap 'cleanup; exit 0' TERM INT; wait -n $BACKEND_PID $FRONT_PID; cleanup; exit 1"]
