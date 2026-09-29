# 管理 API（`/api/admin/*`）

## 认证

```
POST /api/admin/login
{"username": "admin", "password": "admin123"}
→ {"token": "<ADMIN_TOKEN>"}

之后所有请求带：
Authorization: Token <token>
# 或
Authorization: Bearer <token>
```

用户名密码与 token 都来自 `.env`（`ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_TOKEN`）。

**安全说明**：
- 登录接口有防爆破保护：同一 IP 5 分钟内失败 10 次后返回 429（`Retry-After: 300`）。
- Token 校验为常数时间比较。
- Key 明文不提供查询接口，只在导入/创建时可见。

统一错误格式（与 OpenAI 一致）：

```json
{"error": {"message": "…", "type": "api_error", "code": "…"}}
```

## 健康检查

```
GET /health  →  {"status": "ok"}
```

## 仪表盘

| 端点 | 说明 |
|---|---|
| `GET /api/admin/dashboard` | keys/proxies/models/请求数/成功率/延迟/今日 tokens/实时并发 + key_status、proxy_status 分布 |
| `GET /api/admin/dashboard/usage?days=7` | 按天的 token 明细（prompt/completion/total + 请求数，按本地时区分桶） |
| `GET/PATCH /api/admin/settings` | 运行参数。GET 返回 `[{key,type,value,default,description}]`；PATCH body `{settings:{key:value,...}}` |

## NVIDIA Keys

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/nvidia-keys` | 列表（始终脱敏） |
| POST | `/api/admin/nvidia-keys` | 新建 `{name, api_key, rpm_limit}` |
| POST | `/api/admin/nvidia-keys/import` | 批量导入 `{text}`，`name---key` 或每行一个 key |
| POST | `/api/admin/nvidia-keys/bulk` | 批量操作 `{action: enable\|disable\|test, ids: [...]}`（缺省 ids = 全部） |
| PATCH | `/api/admin/nvidia-keys/{id}` | `{name, rpm_limit, enabled}` |
| DELETE | `/api/admin/nvidia-keys/{id}` | 删除；响应头 `X-Proxy-Over-Limit: N` 表示启用代理已超限的数量 |
| POST | `/api/admin/nvidia-keys/{id}/test` | 检测（走 `/models`），返回 `{ok, http_status}` |

import 返回 `{success, duplicate, invalid, failed, errors[]}`。

## 代理

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/proxies` | 列表 + summary（nvidia_keys、max_enabled_proxies、enabled、total_routes） |
| POST | `/api/admin/proxies` / `import` | 新增 / 批量导入（格式同 Key，`socks5://user:pass@host:port`） |
| POST | `/api/admin/proxies/bulk` | 批量操作 `{action: enable\|disable\|delete\|check, ids: [...]}`；enable 时后端强制 N−1 上限 |
| PATCH | `/api/admin/proxies/{id}` | 改字段；密码传 `••••••` 视为未修改；修改 host/port/protocol/username 后状态重置为 unknown；`{"enabled":true}` 超过 N−1 上限时返回 400 `proxy_limit_exceeded` |
| POST | `/api/admin/proxies/{id}/fetch-ip` | 获取公网 IP + 归属地（多源回退，风控不计失败） |
| POST | `/api/admin/proxies/check-all` | 一键检测全部启用代理（低并发 + 错峰防风控；返回 `{total, ok, failed, rate_limited}`） |
| DELETE | `/api/admin/proxies/{id}` | 删除 |

## 分组

`GET/POST /api/admin/proxy-groups`、`PATCH/DELETE /api/admin/proxy-groups/{id}`。删除分组会把组内代理置为无分组。

## 模型

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/models?q=` | 列表 |
| POST | `/api/admin/models` | 新建 |
| PATCH | `/api/admin/models/{id}` | display_name/description/enabled |
| DELETE | `/api/admin/models/{id}` | 删除 |
| POST | `/api/admin/models/sync` | 从 NVIDIA 拉 `/v1/models` 并 upsert |

## 用户 API Key

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/api-keys` | 列表（不含 hash） |
| POST | `/api/admin/api-keys` | 创建 `{name, rate_limit}`（0=不限），**响应含完整 Key 一次** |
| PATCH | `/api/admin/api-keys/{id}` | `{enabled, rate_limit, name, allowed_models}`；`allowed_models` 为模型名数组，`[]` = 允许全部 |
| DELETE | `/api/admin/api-keys/{id}` | 删除 |

## 日志

```
GET /api/admin/logs?model=&status=success|error&api_key=<id>&since=&until=&limit=200&offset=0
```

返回 `{results, total, limit, offset, next_offset}`，字段含 `first_token_ms`、
`prompt/completion/total/cached_tokens`、`routes[]`、`winner_*`。
`model` 为模糊匹配，`since`/`until` 接受 ISO 时间。

## 日志清理

```
python manage.py clean_logs --days 30     # 删除 30 天前日志
python manage.py clean_logs --keep 100000 # 只保留最近 10 万条
```

## 对话测试

```
POST /api/admin/chat
{"model":"m","messages":[...],"stream":true|false}
```

非流式返回 `{request_id, payload, meta:{routes, duration_ms, usage,…}}`。
流式返回 SSE：首包 `{"meta":{…}}` → 上游 chunk → 结束 `{"summary":{duration_ms,first_token_ms,prompt/completion/total/cached_tokens}}`。
