# NVIDIA2API

针对 NVIDIA AI API 的 API 聚合、代理加速、Key 池管理、代理池管理与 OpenAI 兼容中转平台。

![cover](docs/img/cover.png)

## 功能

- NVIDIA API Key 管理：CRUD、批量导入（`name---key` 或纯 `key`）、默认 40 RPM、服务端滑动窗口限流、429/401/5xx 自动冷却与状态管理
- 代理池：SOCKS5/HTTP/HTTPS、批量导入、分组、并发异步测速（延迟 + 公网 IP + 地理位置）、启用数量强制 `≤ NVIDIA Key 数 - 1`（后端强制，前端仅展示）
- 模型管理：从 NVIDIA 同步模型、启停控制，仅 `enabled=true` 的模型通过 OpenAI API 暴露
- OpenAI 兼容 API：`GET /v1/models`、`POST /v1/chat/completions`（含 `stream=true` SSE）
- 请求竞速引擎：一次请求 = 每代理 1 条线路 + 1 条直连线路，每条线路绑定不同的 NVIDIA Key，`asyncio` 并发 + `FIRST_COMPLETED` + 响应有效性校验，首个有效响应为 Winner，其余任务立即取消
- 用户 API Key：`sk-nvidia2api-*`，仅存 SHA-256 Hash，创建时完整展示一次，支持每 Key 独立 RPM
- 请求日志：request_id、耗时、Winner 线路、Key、代理、状态、Token 统计
- Dashboard：Key/Proxy/Model/请求量/成功率/平均延迟统计
- 管理后台登录：`/api/admin/login`（用户名密码 → 固定 Token）

## 技术栈

- 后端：Python 3.12+、Django 6、DRF、SQLite、httpx（含 httpx[socks]/httpx-socks）、asyncio
- 前端：Next.js 14、TypeScript、Tailwind CSS、lucide-react

## 结构

```
backend/     Django（config/ 配置、apps/core/ 数据模型、services/ 业务服务、api/ Admin + OpenAI API、tests/ 测试）
frontend/    Next.js 控制台（dashboard、nvidia-keys、proxies、proxy-groups、models、api-keys、request-logs、settings、login）
data/        SQLite 数据目录（Docker 卷挂载点）
```

## 快速开始

```bash
cp .env.example .env

# 后端
cd backend
pip install -r requirements.txt
python manage.py migrate
python -m pytest tests          # 23 个测试：导入/限流/代理限制/竞速/并发安全
python manage.py runserver 0.0.0.0:8000

# 前端
cd frontend
npm install
npm run dev                     # http://localhost:3000
```

默认管理员：`admin / admin123`（用 `.env` 中 `ADMIN_USERNAME/ADMIN_PASSWORD/ADMIN_TOKEN` 修改）。

## Docker

```bash
docker compose up -d
```

单镜像运行前后端：仅暴露 Next.js `3000` 端口，Django 只监听容器内 `127.0.0.1:8000`，由 Next.js rewrites 将 `/api`、`/v1` 反代到后端。SQLite 数据保存在 `./data`（已挂载到容器 `/app/data`）。

## 使用流程

1. 登录控制台 → **NVIDIA Keys** → 批量导入 Key（`主账号01---nvapi-xxx` 或每行一个 `nvapi-xxx`，自动去重/自动命名）
2. **Proxies** → 批量导入代理、测速、获取 IP、启用（数量受 Key 数 - 1 限制）
3. **Models** → 点击「同步 NVIDIA 模型」，启用要暴露的模型
4. **API Keys** → 创建用户 Key（完整 Key 仅显示一次）
5. 用 OpenAI SDK 调用：

```python
from openai import OpenAI

client = OpenAI(api_key="sk-nvidia2api-xxxx", base_url="http://localhost:8000/v1")
resp = client.chat.completions.create(
    model="meta/llama-3.3-70b-instruct",
    messages=[{"role": "user", "content": "你好"}],
)
print(resp.choices[0].message.content)
```

## 竞速机制

```
用户 → 验证 Key/模型/限流 → build_routes()
  代理A + Key1 ┐
  代理B + Key2 ├ asyncio 并发 (FIRST_COMPLETED)
  直连  + Key3 ┘
        ↓
  是有效的 AI Protocol 响应才判定 Winner → 取消其余任务 → 返回用户
```

- `is_valid_response`：HTTP 200 + 有 choices + 有 message/delta 且无 error 字段
- 429 → Key 标记 rate_limited + 60s 冷却；401/403 → invalid；单代理/单 Key 故障不影响整体请求
- 流式：首条有效 SSE chunk 到达即判定 Winner，随后转发剩余 chunk，其余线路取消

## 并发说明

Key 的 RPM 计数使用 SQLite 条件更新（`UPDATE ... WHERE count < rpm_limit`）保证原子性，多线程下不会超限；项目预留了迁移 PostgreSQL/Redis 的结构空间。

## 环境变量

见 `.env.example`。

## 文档

详见 [docs/](docs)：架构、数据库、后端模块、竞速引擎、Admin API、OpenAI API、前端、部署。
