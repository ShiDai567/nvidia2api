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

# Stage 2: runtime (Node for Next.js + Python for Django, same container)
FROM node:22-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PYTHONUNBUFFERED=1 DATA_DIR=/app/data

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt
COPY backend/ .

# Next.js standalone server + static assets
COPY --from=fe /fe/.next/standalone ./frontend
COPY --from=fe /fe/.next/static ./frontend/.next/static
COPY --from=fe /fe/public ./frontend/public

EXPOSE 3000
# Django 只监听 127.0.0.1，容器外不可达；对外仅暴露 Next.js 3000 端口
CMD ["sh", "-c", "python3 manage.py migrate && (uvicorn config.asgi:application --host 127.0.0.1 --port 8000 &) && cd frontend && HOSTNAME=0.0.0.0 PORT=3000 node server.js"]
