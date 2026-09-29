# 数据库设计

SQLite，默认文件 `data/db.sqlite3`（可用 `DATABASE_PATH` 覆盖）。后端启动时自动 `migrate`，永远不需要手动建表。

## ER 概览

```
UserApiKey 1 ──── n RequestLog
NvidiaApiKey / Proxy / AIModel / SystemSetting（独立）
```

## 表结构

### nvidia_api_key

| 字段 | 类型 | 说明 |
|---|---|---|
| name | varchar(128) | |
| api_key | varchar(256) UNIQUE | 全库唯一，脱敏只在序列化层做（`nvapi-****...`） |
| status | varchar(16) | `available` / `rate_limited` / `error` / `disabled` / `invalid`（有索引） |
| rpm_limit | int | 默认 40 |
| minute_window_start | datetime | 当前计数窗口起点 |
| minute_request_count | int | 窗口内已用 |
| success_count / failure_count | int | 累计 |
| cooldown_until | datetime | 冷却截止（429/网络错误） |
| last_used_at | datetime | LRU 排序键 |
| last_error | varchar(256) | 最近一次错误摘要 |

### proxy

Proxy 字段：`protocol`(`socks5|socks5h|http|https`)、`host`、`port`、`username`、`password`、`country/region/city/isp`、`enabled`、`status`(`unknown|healthy|degraded|unhealthy|disabled`)、`latency_ms`、`public_ip`、`last_check_at`、`success/failure_count`、`consecutive_failures`、`cooldown_until`。

唯一约束 `(protocol, host, port, username)`，索引 `(enabled, status)`。

### model

`model_name` UNIQUE、`display_name`、`description`、`provider`、`status`、`enabled`（有索引，`enabled + model_name` 复合索引）。只有 `enabled=true` 的模型通过 `/v1/models` 暴露。

### user_api_key

存 `key_hash`(SHA-256，UNIQUE，索引)、`key_prefix`（展示用前 22 位）、`enabled`、`rate_limit`（**0 = 不限**）、`total/success/failed_requests`、`minute_*` 窗口字段、`last_used_at`。

### request_log

| 字段 | 说明 |
|---|---|
| request_id | `req_xxx`，索引 |
| model / status / http_status / error_type | |
| duration_ms | 总耗时（流式为 [DONE] 时调正） |
| first_token_ms | 首 chunk 耗时 TTFT（流式） |
| winner_route_type / winner_key_name / winner_proxy_name / proxy_public_ip | Winner 线路 |
| is_stream / routes_count | |
| prompt/completion/total/cached_tokens | token 指标（stream 时来自 `usage`，需 `stream_options.include_usage`） |
| routes | JSON：本次竞速每条线路的 `{name,kind,key_name,proxy_name,status,latency_ms,error,http_status}` |

### system_setting

`key` UNIQUE、`value`、`description`——即运行参数表（见 `sysconfig.RUNTIME_PARAMS` 注册表）。

## 并发策略

- SQLite 默认串行写。两个热点计数器都采用**条件更新**而非 `SELECT FOR UPDATE`：
  ```python
  base.filter(window_stale).update(count=1, window_start=now) or
  base.filter(count__lt=F("rpm_limit")).update(count=F("count")+1)
  ```
  单条 UPDATE 原子执行，无锁升级死锁，多线程下永不超过 RPM 上限（有并发测试验证）。
- `DATABASES.OPTIONS.timeout=30s`，写锁等待不至于立即报错。
- 未来迁移 PostgreSQL：所有表使用标准类型，无外键 CASCADE 之外的自定义逻辑，可直接 `migrate`。
