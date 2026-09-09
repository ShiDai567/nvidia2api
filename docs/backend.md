# 后端模块

```
backend/
├── manage.py
├── config/          # settings / urls / asgi
├── apps/core/       # models + AdminConfig.ready() 自动迁移
├── services/        # 纯业务，零 Django View
├── api/             # Admin API + OpenAI API
└── tests/           # 27 个用例（导入/限流/竞速/并发/启停上限）
```

## services/

| 文件 | 职责 |
|---|---|
| `key_service.py` | bulk_import（去重/自动命名）、`claim_rpm_slot`（条件更新）、`report_failure` 状态机（401→invalid，429→rate_limited+60s 冷却，其余 60s 冷却）、脱敏 |
| `proxy_service.py` | `bulk_import_proxies`、`set_enabled`（**强制 enabled ≤ keys-1**）、`report_proxy_result`（连续 3 败 → unhealthy + 冷却）、`schedulable_proxies`（排除 cooldown/unhealthy，按延迟排序） |
| `proxy_checker.py` | `check_proxy`（多源 IP/地理探测，风控不计失败）、`check_proxy_retry`（换源重试）、`check_all`（一键检测：Semaphore(5) + 错峰启动，风控单独计数） |
| `load_balancer.py` | `build_routes`：线路数 = min(启用代理数+1, 可用 Key 数, max_routes)；第 i 个代理配第 i 个 Key，最后一条直连 |
| `race_engine.py` | 竞速与流式竞速（见 race-engine.md） |
| `api_key_service.py` | `generate_key`（sk-nvidia2api-36hex）、hash 查询、可选限流（rate_limit>0 时每分钟窗口） |
| `nvidia_service.py` | 上游 HTTP（`list_models`、`sync_models` 幂等 upsert） |
| `sysconfig.py` | 运行时参数注册表：`RUNTIME_PARAMS` 定义 (key, type, default, description)；`get()` 读 SystemSetting 覆盖 Settings；`set_params()` 批量写 |

## api/

- `api/urls.py`：所有端点注册
- `api/auth.py`：`admin_required`/`AdminRequiredMixin`（`Authorization: Token <ADMIN_TOKEN>`）、`openai_error()` 统一错误格式
- `api/admin_views.py`：后台全部视图（登录/Keys/Proxies/Groups/Models/UserKeys/Logs/Dashboard/Usage/Settings/Chat）
- `api/openai_views.py`：`/v1/models`、`/v1/chat/completions`，全局 `BoundedSemaphore(MAX_CONCURRENT_REQUESTS)`，OpenAI 错误码
- `api/serializers.py`：所有序列化器；NVIDIA Key 默认脱敏，仅 `?reveal=1` 时返回明文

## 日志

所有关键动作打到 logger `nvidia2api.*`，级别由 `LOG_LEVEL` 控制。敏感值（完整 NVIDIA Key、代理密码）不会出现在日志里。

## 自动迁移

`apps/core/apps.py` 的 `ready()` 里：

```python
if not any(cmd in sys.argv for cmd in ("migrate", "makemigrations", "test", "pytest")):
    call_command("migrate", run_syncdb=True, verbosity=0)
```

删除数据库后再启动服务，表会自动重建，避免 `no such table` 类事故。
