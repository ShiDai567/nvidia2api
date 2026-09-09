# AGENTS.md

NVIDIA2API: NVIDIA AI API 的 Key 池/代理池聚合代理（OpenAI 兼容）。Django 后端 + Next.js 前端，SQLite 存储。文档与注释均为中文，提交 message 也用中文。

## 布局

- `backend/` — Django 6 + DRF。`config/` 配置，`apps/core/` 模型，`services/` 业务逻辑（竞速引擎 `race_engine.py` 在核心），`api/` Admin + OpenAI 路由，`tests/`。
- `frontend/` — Next.js 16 (App Router) + React 19 + Tailwind 3。
- `data/` — SQLite 目录，本地运行和 Docker 都会自动创建挂载。
- `docs/` — 中文架构/API 文档，改对应模块时同步更新。

## 命令

```bash
# 后端（在 backend/ 下）
pip install -r requirements.txt
python manage.py migrate
python -m pytest tests                 # pytest.ini 已配 DJANGO_SETTINGS_MODULE
python -m pytest tests/test_race.py -k test_xxx   # 单测
python manage.py runserver 0.0.0.0:8000

# 前端（在 frontend/ 下）
npm install && npm run dev             # :3000
npm run build && npm run lint          # 提交前验证
```

## 关键事实（容易踩坑）

- **settings 不读 `.env` 文件**，只读环境变量（docker-compose/docker run 注入；本地需 `export` 或自行加载）。后端目录下 `python manage.py` 跑测试会用 `data/test_db.sqlite3`，真实库是 `data/db.sqlite3`。
- `settings.py` 设了 `DJANGO_ALLOW_ASYNC_UNSAFE=true`：竞速引擎在 asyncio 单事件循环内做短暂序列化 SQLite 写，这是有意设计；RPM 计数用 SQL 条件更新（`UPDATE ... WHERE count < rpm_limit`）保证原子性，**不要**改成读-改-写。
- 代理启用数被后端强制 `≤ NVIDIA Key 数 - 1`（每 Key 一条线路，留 1 条直连），改此规则要同步改竞速引擎和测试。
- 用户 API Key（`sk-nvidia2api-*`）只存 SHA-256 hash；Admin API 鉴权是固定 token：`Authorization: Bearer $ADMIN_TOKEN`（不是登录换短期 token）。
- Docker 是单镜像：Django 只监听容器内 `127.0.0.1:8000`，Next.js (`output: "standalone"`) 通过 `next.config.mjs` rewrites 把 `/api`、`/v1` 反代给后端（后端地址取 `BACKEND_INTERNAL_URL`）。本地 dev 则前端调 `NEXT_PUBLIC_API_BASE_URL`。
- **CI（`.gitlab-ci.yml`）只在打 Tag 时构建镜像并建 release**；MR 仅有手动触发入口。没有跑 lint/test 的 CI。
- `httpx[socks]` + `httpx-socks` 两者都需要（SOCKS 代理支持）。
- 默认管理员 `admin / admin123`（env 可改）。

## 测试注意事项

- 测试覆盖竞速、限流、代理限制、并发安全（SQLite 原子更新）——修改这些逻辑必须跑全套 `python -m pytest tests` 并更新对应测试。
- 竞速判定是"首个**有效 AI 响应**"（HTTP 200 + 有 choices/message 且无 error），不是"最快连接"；流式同理取首个有效 chunk。改 `race_engine.py` 时保持该语义。
