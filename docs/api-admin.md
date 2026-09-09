# 管理 API（`/api/admin/*`）

## 认证

```
POST /api/admin/login
{"username": "admin", "password": "admin123"}
→ {"token": "<ADMIN_TOKEN>"}

之后所有请求带：
Authorization: Token <token>
```

用户名密码与 token 都来自 `.env`（`ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_TOKEN`）。

统一错误格式（与 OpenAI 一致）：

```json
{"error": {"message": "…", "type": "api_error", "code": "…"}}
```

## 仪表盘

| 端点 | 说明 |
|---|---|
| `GET /api/admin/dashboard` | keys/proxies/models/请求数/成功率/延迟汇总 + key_status、proxy_status 分布 |
| `GET /api/admin/dashboard/usage?days=7` | 按天的 token 明细（prompt/completion/total + 请求数） |
| `GET/PATCH /api/admin/settings` | 运行参数。GET 返回 `[{key,type,value,default,description}]`；PATCH body `{settings:{key:value,...}}` |

## NVIDIA Keys

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/nvidia-keys` | 列表（默认脱敏） |
| POST | `/api/admin/nvidia-keys` | 新建 `{name, api_key, rpm_limit}` |
| POST | `/api/admin/nvidia-keys/import` | 批量导入 `{text}`，`name---key` 或每行一个 key |
| GET | `/api/admin/nvidia-keys/{id}?reveal=1` | 查看明文 Key |
| PATCH | `/api/admin/nvidia-keys/{id}` | `{name, rpm_limit, enabled}` |
| DELETE | `/api/admin/nvidia-keys/{id}` | 删除 |
| POST | `/api/admin/nvidia-keys/{id}/test` | 检测（走 `/models`） |

import 返回 `{success, duplicate, invalid, failed, errors[]}`。

## 代理

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/proxies` | 列表 + summary（nvidia_keys、max_enabled_proxies、enabled、total_routes） |
| POST | `/api/admin/proxies` / `import` | 新增 / 批量导入（格式同 Key，`socks5://user:pass@host:port`） |
| PATCH | `/api/admin/proxies/{id}` | 改字段；`{"enabled":true}` 超过 N−1 上限时返回 400 `proxy_limit_exceeded` |
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
| PATCH | `/api/admin/api-keys/{id}` | `{enabled, rate_limit, name}` |
| DELETE | `/api/admin/api-keys/{id}` | 删除 |

## 日志

```
GET /api/admin/logs?model=&status=success|error
```

返回最多 200 条，字段含 `first_token_ms`、`prompt/completion/total/cached_tokens`、`routes[]`、`winner_*`。

## 对话测试

```
POST /api/admin/chat
{"model":"m","messages":[...],"stream":true|false}
```

非流式返回 `{request_id, payload, meta:{routes, duration_ms, usage,…}}`。
流式返回 SSE：首包 `{"meta":{…}}` → 上游 chunk → 结束 `{"summary":{duration_ms,first_token_ms,prompt/completion/total/cached_tokens}}`。
