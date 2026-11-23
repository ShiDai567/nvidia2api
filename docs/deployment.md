# 部署与环境变量

## 环境变量（.env）

```ini
SECRET_KEY=change-me
DEBUG=false

# 数据目录 / DB
DATA_DIR=./data
DATABASE_PATH=./data/db.sqlite3

# 管理后台密码 / token（管理后台只需密码登录，API 仍使用固定 Token）
ADMIN_PASSWORD=admin123
ADMIN_TOKEN=dev-admin-token

# 上游
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1

# 默认配额（可在管理后台"设置"页覆盖，免重启）
DEFAULT_NVIDIA_RPM=40
MAX_ROUTES_PER_REQUEST=50
DIRECT_ROUTES_PER_REQUEST=1  # 每次请求并行直连数；可在后台设置中覆盖，立即生效
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

后端需要 Python 3.12+ 和 [uv](https://docs.astral.sh/uv/)。在 `backend/` 下执行 `uv sync --dev` 会根据 `uv.lock` 创建虚拟环境并安装开发依赖。

```bash
cd backend
uv sync --dev
uv run python manage.py runserver 0.0.0.0:8000     # 启动时自动 migrate，无需手动建表

cd ../frontend
npm install
npm run dev                                  # http://localhost:3000
```

测试：

```bash
cd backend && uv run pytest tests
```

## Docker 一体化

管理面板导航栏显示当前构建的版本。GitLab 发布镜像显示发布标签，本地开发时从 Git 读取版本。自行构建镜像时可通过 `--build-arg APP_VERSION=版本号` 指定显示值，缺少版本信息时显示 `dev`。

运行环境变量直接配置在 `docker-compose.yml` 的 `environment` 中，无需创建 `.env` 文件。启动前修改其中的 `SECRET_KEY`、`ADMIN_PASSWORD` 和 `ADMIN_TOKEN`；数据目录保持容器路径 `/app/data` 和 `/app/data/db.sqlite3`，通过卷挂载持久化到宿主机 `./data`。

镜像通过显式 `ENTRYPOINT` 使用 `/bin/sh` 执行独立脚本 `docker/start.sh`（镜像内为 `/app/start.sh`），只使用 POSIX sh 语法，无需 `wait -n` 或 Bash。先验证 Nginx 配置，数据库迁移成功后启动 Django、Next.js 和 Nginx；脚本每秒检查服务状态，任一服务退出时会停止其余服务并以失败状态退出，交给容器重启策略恢复。收到容器停止信号时会转发给三个服务并等待它们退出。

仅 Docker 打包产物启用 Nginx 统一入口，宿主机端口映射仍为 `3000:3000`：

| 路径 | 容器内目标 |
| --- | --- |
| `/api`、`/api/*`、`/v1`、`/v1/*`、`/health` | Django `127.0.0.1:8000` |
| 页面及静态资源 | Next.js standalone `127.0.0.1:3001` |

配置位于 `docker/nginx.conf`，API 直接转发到 Django，不经过 Next.js rewrites 的默认 30 秒反代超时。API 关闭响应缓冲、缓存和 gzip，保留 SSE 分片；连接超时 10 秒、读写空闲超时 180 秒，生成请求失败时不由 Nginx 重试。请求体上限为 10 MiB；`/v1/chat/completions` 仍由后端执行 4 MiB 校验。若提高上游超时，应同步调整 Nginx 以及外部入口网关、调用方的超时。修改 Nginx 配置后重新构建镜像。本地开发和测试的 `frontend/next.config.mjs` rewrites 与启动命令保持原样。

Nginx 每个 worker 配置 4096 个连接，客户端和上游连接分别占用名额；这不是后端并发容量承诺。Compose 将 `nofile` 软硬上限设为 16384，入口脚本也会尝试将软上限提高到 16384。使用 `docker run` 且运行时限制较低时，增加 `--ulimit nofile=16384:16384`，避免文件描述符不足。

升级时删除部署配置中临时添加的 `entrypoint` 和 `command` 覆盖项，再执行 `docker compose up -d --pull always --force-recreate nvidia2api`。若日志仍显示旧的 `sh: 1: wait: Illegal option -n`，用 `docker inspect nvidia2api --format '{{json .Config.Entrypoint}} {{json .Config.Cmd}} {{.Image}}'` 核对实际容器启动配置；新入口应为 `["/bin/sh","/app/start.sh"]`。

运行镜像显式安装 Nginx 和 SQLite 动态库 `libsqlite3-0`，后者供从 Python 镜像复制的解释器使用。GitLab 构建后使用镜像默认入口执行启动检查：通过 Nginx `3000` 访问 `/health` 和 `/login` 均返回 HTTP 200，未认证的 `/api/admin/settings` 与 `/v1/models` 返回 JSON 401，容器正常停止后，才推送版本镜像。Compose 健康检查同样通过 Nginx 访问 `/health` 和 `/login`，覆盖入口及前后端服务。

`sh docker/smoke-test.sh <镜像名>` 还会在独立容器内使用替身后端验证真实 Nginx：API 与页面分流（包括 `/api-keys` 页面）、请求体及鉴权头、错误状态、SSE 分片，以及等待 31 秒后返回的慢请求，测试无需 NVIDIA 凭据。

```bash
docker compose up -d --build
```

Docker 镜像从 `uv.lock` 安装 Django 运行依赖，并在 Node 22 构建阶段生成 Next.js standalone 产物；运行阶段在同一容器内启动 Nginx、Node.js 和 Python 服务。SQLite 落到挂载的 `./data`，数据目录为 `/app/data`。

## CI 基础镜像拉取

Tag 流水线使用 Docker-in-Docker 构建并推送镜像，成功后创建 GitLab Release。CI 默认通过 `mirror.gcr.io/library` 拉取 Node 和 Python 官方基础镜像；`uv` 仍从 `ghcr.io/astral-sh/uv` 拉取。

产物镜像直接使用 GitLab 的 `CI_REGISTRY_IMAGE`（已包含命名空间和项目名），同时推送 Git Tag 和 `latest` 标签。例如本项目的镜像地址为 `repo.elsworld.cn:8443/shidai/nvidia2api:latest`，无需再追加 `/nvidia2api`。

GitLab Release 标题为 `NVIDIA2API <Git Tag>`，正文包含更新说明（优先 Tag 注解，轻量 Tag 回退到提交信息）、本版本镜像拉取命令、首次部署与升级步骤，以及后台和 API 访问地址。部署建议使用与 Git Tag 一致的镜像标签，`latest` 会随后续 Tag 发布更新。首次部署使用 Release 中的 `docker run` 命令即可，无需下载源码；仓库的 `docker-compose.yml` 使用 `build: .`，用于完整源码目录中的本地构建，不能只下载该文件就直接运行发布镜像。

GitHub Release 同样提供固定版本标签（如 `ghcr.io/<组织>/<项目>:v1.2`）和独立于源码的 `docker run` 部署步骤；GitHub 的 `latest` 由默认分支构建更新。

若构建在 `load metadata` 阶段报 `registry-1.docker.io ... EOF`，说明拉取基础镜像的网络连接中断，应用构建尚未开始。可在 GitLab 项目的 **Settings → CI/CD → Variables** 中设置 `DOCKERHUB_PREFIX`，覆盖为 Runner 可访问的可信缓存或私有仓库前缀（包含 `library` 路径，仓库内需提供相同镜像和标签）。直连 Docker Hub 时设为 `docker.io/library`。

本地构建默认使用 Docker Hub，也可以显式指定缓存源：

```bash
docker build --build-arg DOCKERHUB_PREFIX=mirror.gcr.io/library -t nvidia2api:local .
```

该参数仅影响 Dockerfile 内的 Node/Python 基础镜像，不影响 Runner 启动任务时拉取 `docker:27-cli`、`docker:27-dind` 或 Release 任务镜像。若这些镜像拉取失败，需在 Runner 层配置可用的镜像源。修改 CI 配置后需在包含修改的提交上运行流水线；重试旧 Tag 的任务仍会使用该 Tag 的旧配置。

## 生产注意点

- **外部前置代理**（nginx/caddy）需放行 SSE：关闭响应缓冲，读取超时覆盖容器内 Nginx 的超时预算（默认 180s）。
- 管理后台对话接口在 ASGI 下逐块发送 SSE；更新后需重启后端或重新构建并启动 Docker 镜像，前置代理仍须关闭响应缓冲。
- SSE 响应携带 `Cache-Control: no-cache, no-transform`，开发环境的 Next.js 反代可据此跳过 gzip；Docker 内置 Nginx 已关闭 API 压缩和响应缓冲，外部前置代理也应保留该响应头。
- 单实例 SQLite 适合中小流量；Nginx 入口不解决数据库写锁或后端容量问题。大规模并发需要先治理数据库写入和并发准入，再通过压测确定容量；可迁移 PostgreSQL + Redis。
- SQLite 默认启用 WAL 和 IMMEDIATE 短事务；首次升级时先停止旧服务，再启动新镜像。持久化整个 `./data` 目录至本机磁盘，在线备份使用 SQLite backup API，详见 [database.md](database.md#wal-存储与备份)。
- 不要让 `/api/admin/*` 直接裸露公网，绑 Basic Auth 或放到内网域名
