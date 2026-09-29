# 部署与环境变量

## 环境变量（.env）

```ini
SECRET_KEY=change-me
DEBUG=false

# 数据目录 / DB
DATA_DIR=./data
DATABASE_PATH=./data/db.sqlite3

# 管理后台账号 / token
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123
ADMIN_TOKEN=dev-admin-token

# 上游
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1

# 默认配额（可在管理后台"设置"页覆盖，免重启）
DEFAULT_NVIDIA_RPM=40
MAX_ROUTES_PER_REQUEST=50
UPSTREAM_CONNECT_TIMEOUT=10
UPSTREAM_READ_TIMEOUT=120
PROXY_TIMEOUT=10
MAX_CONCURRENT_REQUESTS=100

LOG_LEVEL=INFO

# 前端直连后端地址
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000

# 前端远程开发：经代理域名访问 dev server 时加入白名单（仅 dev 生效）
# 主机名即可（不含协议/端口），逗号分隔；Coder 环境设置 VSCODE_PROXY_URI 可自动识别
ALLOWED_DEV_ORIGINS=code-3000.elsworld.cn
```

生产务必改 `SECRET_KEY`、`ADMIN_PASSWORD`、`ADMIN_TOKEN`。

## 本地开发

```bash
cd backend
pip install -r requirements.txt
python manage.py runserver 0.0.0.0:8000     # 启动时自动 migrate，无需手动建表

cd ../frontend
npm install
npm run dev                                  # http://localhost:3000
```

测试：

```bash
cd backend && python -m pytest tests
```

## Docker 一体化

```bash
docker compose up -d
```

- `backend` 容器内运行 Django，SQLite 落到挂载的 `./data`
- `frontend` 容器 `npm install && npm run build && npm run start`

仅后端 + 已有前端静态资源可用根 `Dockerfile`：前端先 build（Node 22 阶段），后端挂在 Python 3.12-slim，`DATA_DIR=/app/data`。

## 生产注意点

- **前置代理**（nginx/caddy）需放行 SSE：`proxy_buffering off`，长连接 `read_timeout` ≥ `UPSTREAM_READ_TIMEOUT`（默认 120s）
- 单实例 SQLite 适合中小流量；要承载大规模并发请迁移 PostgreSQL + Redis，并把 `MAX_CONCURRENT_REQUESTS` 提升
- 定期备份 `./data/db.sqlite3`
- 不要让 `/api/admin/*` 直接裸露公网，绑 Basic Auth 或放到内网域名
