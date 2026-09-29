# 总体架构

## 定位

NVIDIA2API 是面向 NVIDIA AI API 的聚合代理平台：

- 管理多个 NVIDIA API Key（40 RPM/Key 默认）、多协议代理（SOCKS5/HTTP/HTTPS）两者组成"线路池"
- 对外暴露 OpenAI 兼容的 `/v1/models`、`/v1/chat/completions`
- 核心能力：**多线路并发竞速 + 首个有效响应 Winner + 其余线路立即取消**

## 分层

```
┌────────────────────────── 客户端 ──────────────────────────┐
│ Browser (Next.js 控制台)   OpenAI SDK / curl (用户 API)     │
└──────────────┬────────────────────────┬────────────────────┘
               │ Admin Token            │ Bearer sk-nvidia2api-*
┌──────────────▼────────────────────────▼────────────────────┐
│                Django + DRF (api/)                         │
│   /api/admin/*                 /v1/*                       │
│   管理 CRUD/统计               OpenAI 兼容                 │
└──────────────┬─────────────────────────────────────────────┘
               │
┌──────────────▼────────────────┐
│        services/ 服务层        │
│  key_service      Key 限流冷却 │
│  proxy_service    代理启用限制 │
│  proxy_checker    并发测速/IP  │
│  load_balancer    线路构建     │
│  race_engine      竞速执行     │
│  loop             共享事件循环  │
│  api_key_service        用户Key│
│  sysconfig        运行时参数   │
└──────────────┬────────────────┘
               │ httpx(异步, 连接池复用) + SQLite
┌──────────────▼────────┐   ┌───────────────┐
│  SQLite (data/)       │   │ NVIDIA 上游    │
└───────────────────────┘   └───────────────┘
```

## 关键决策

1. **业务不落 View**：`api/*` 只做参数校验与响应拼装，业务都在 `services/`。
2. **同步视图 + 共享后台事件循环**：竞速在常驻后台线程的单一 event loop 上执行（`services/loop.py`），httpx 连接按代理维度池化、跨请求复用（TCP+TLS 免重复握手）；视图保持同步，避免 ASGI 迁移复杂度。
3. **SQLite 并发控制**：Key 的 RPM 计数用数据库侧条件 `UPDATE ... WHERE count < rpm_limit`，放弃 `SELECT FOR UPDATE`，避免 SQLite 锁升级死锁（detail 见 [database.md](database.md)）。
4. **运行时参数优先于环境变量**：`SystemSetting` 表中的值覆盖 `.env`，改后即时生效（`sysconfig.py`）。
5. **线路数 = 启用代理数 + 1 直连**：代理数量上限 = NVIDIA Key 数 − 1，由后端在 `set_enabled` 强制（不是前端校验）。
6. **流式错误语义**：流式请求的竞速在返回响应对象**之前**完成——全部线路失败返回真实 502/503 JSON，Winner 确认后才返回 200 + SSE；chunk 通过线程安全队列从事件循环泵给 Django 生成器，事件循环永不被生成器阻塞。

## 请求路径（聊天）

```
POST /v1/chat/completions
  验证 Bearer（UserApiKey, sha256）
  验证 body/model（400/404 不消耗配额）
  验证 allowed_models 白名单（若配置）
  用户 Key 限流（rate_limit>0 才计数；429 带 Retry-After）
  全局并发信号量
  build_routes() → [代理+Key]*N + [直连+Key]
  race (asyncio.FIRST_COMPLETED, 共享 loop + 连接池)
    ├ 首个"有效响应"判定 Winner（见 race-engine.md）
    ├ 其余任务 cancel + 连接归还连接池
    └ 写 RequestLog（含每条线路明细）
  返回用户（SSE 或 JSON，含 X-Request-Id）
```
