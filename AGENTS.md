# AGENTS.md

NVIDIA2API: NVIDIA AI API 的 Key 池/代理池聚合代理（OpenAI 兼容）。Django 后端 + Next.js 前端，SQLite 存储。文档与注释均为中文，提交 message 也用中文。

## 布局

- `backend/` — Django 6 + DRF。`config/` 配置，`apps/core/` 模型，`services/` 业务逻辑（竞速引擎 `race_engine.py` 在核心），`api/` Admin + OpenAI 路由，`tests/`。
- `frontend/` — Next.js 16 (App Router) + React 19 + Tailwind 3。
- `data/` — SQLite 目录，本地运行和 Docker 都会自动创建挂载。
- `docs/` — 中文架构/API 文档，改对应模块时同步更新。

## 命令

```bash
# 后端（在 backend/ 下，Python 3.12+；依赖由 uv.lock 锁定）
uv sync --dev
uv run python manage.py migrate
uv run pytest tests
uv run pytest tests/test_race.py -k test_xxx   # 单测
uv run python manage.py runserver 0.0.0.0:8000

# 前端（在 frontend/ 下）
npm install && npm run dev             # :3000
npm run build && npm run format:check && npm run lint && npm test
npm run deps:check                     # 模块依赖循环/解析检查
npm run deps:graph                     # 输出 DOT 依赖图
npm run test:mutation                  # 独立运行，手动或夜间，不属于快速测试循环
```

## 关键事实（容易踩坑）

- **settings 不读 `.env` 文件**，只读环境变量（docker-compose/docker run 注入；本地需 `export` 或自行加载）。后端命令使用 `uv run`；后端目录下运行测试会用 `data/test_db.sqlite3`，真实库是 `data/db.sqlite3`。
- SQLite 默认启用 WAL + IMMEDIATE 短事务；用户/NVIDIA RPM 配额用 SQL 条件更新，结果计数用 `F()` 原子递增，**不要**改成读-改-写。`settings.py` 的 `DJANGO_ALLOW_ASYNC_UNSAFE=true` 允许竞速引擎在单事件循环中做短暂同步写；事务内保持无网络等待。并发与 WAL 备份约定见 `docs/database.md`。
- 直连数由运行参数 `direct_routes_per_request` 配置（默认 1，至少 1），每条线路使用不同 Key；代理启用上限为 `max(NVIDIA Key 数 - 配置直连数, 0)`。调度优先预留直连名额，受可用 Key 和总线路上限限制；改此规则要同步改线路构建和测试。
- 用户 API Key（`sk-nvidia2api-*`）只存 SHA-256 hash；Admin API 鉴权是固定 token：`Authorization: Bearer $ADMIN_TOKEN`（不是登录换短期 token）。
- Docker 是单镜像：Nginx 监听 `3000`，`/api`、`/v1`、`/health` 直达 Django `127.0.0.1:8000`，页面到 Next.js standalone `127.0.0.1:3001`；配置在 `docker/nginx.conf`。本地开发和测试保留 Next.js rewrites（`BACKEND_INTERNAL_URL`）及 `NEXT_PUBLIC_API_BASE_URL`，仅打包产物使用 Nginx。改入口或进程管理时验证 `test_container_startup.py` 和 `docker/smoke-test.sh`。
- **CI（`.gitlab-ci.yml`）只在打 Tag 时构建镜像并建 release**；MR 仅有手动触发入口。没有跑 lint/test 的 CI。
- Release 说明取自 tag 内容：优先 tag 注解消息（`git tag -a`），轻量 tag 回退到 commit 信息——用 `release-cli create --description <文件>` 实现（`release:` 关键字只能传字符串，改回它就拿不到多行/回退逻辑）。
- `httpx[socks]` + `httpx-socks` 两者都需要（SOCKS 代理支持）。
- 管理后台仅需密码，默认 `admin123`（`ADMIN_PASSWORD` 可改）；Admin API 仍使用固定 `ADMIN_TOKEN`。

## 测试注意事项

- 测试覆盖竞速、限流、代理限制、并发安全（SQLite 原子更新）——修改这些逻辑必须跑全套 `uv run pytest tests` 并更新对应测试。
- 竞速判定是"首个**有效 AI 响应**"（HTTP 200 + 有 choices/message 且无 error），不是"最快连接"；流式同理取首个有效 chunk。改 `race_engine.py` 时保持该语义。

## Agent skills

### Issue tracker

Issues and specs live in this repo's GitLab Issues; use `glab`. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context domain docs live at the repo root and in `docs/adr/`. See `docs/agents/domain.md`.
