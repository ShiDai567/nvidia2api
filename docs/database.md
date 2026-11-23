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

`model_name` UNIQUE、`display_name`、`description`、`provider`、`status`、`enabled`（有索引，`enabled + model_name` 复合索引）、`test_latency_ms`（最近一次成功测试耗时）、`last_tested_at`（最近一次成功测试时间）。只有 `enabled=true` 的模型通过 `/v1/models` 暴露。

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

- 每个数据库连接初始化时执行 `PRAGMA journal_mode=WAL`，允许读事务与写事务并行；SQLite 仍只允许一个写入者。
- `transaction_mode=IMMEDIATE` 让显式事务在开始时领取写锁，避免默认 DEFERRED 事务先读后写时发生锁升级冲突；`timeout=30s` 是写锁等待预算。事务应保持短小，不在事务内执行上游网络请求。
- 用户 Key 配额和 NVIDIA Key RPM 各用一条**条件 UPDATE** 完成窗口重置或递增：`WHERE` 校验启用状态、冷却和配额，`CASE` 判断窗口是否过期，`F()` 在数据库内递增计数。NVIDIA RPM 非正值不领取名额，用户 `rate_limit<=0` 不限流，但仍按分钟记录调用数。
- 用户总请求数、成功/失败数及 NVIDIA Key 成功/失败数均用 `F()` 递增，避免并发调用使用旧模型对象覆盖计数。Key 成功仅将 `rate_limited` 恢复为 `available`，保留当前禁用或失效状态。
- 代理结果通过单条 UPDATE 同时递增成功/失败数、更新连续失败次数与健康状态；`CASE` 按本次递增后的连续失败次数判断冷却阈值，成功时清零连续失败并清除冷却。
- 原有用户限流、Key 和代理结果使用 `atomic + select_for_update + save`；SQLite 不提供行锁，并发读后写可报 `database is locked`。仅启用 WAL 无法修复这些锁升级冲突，因此热点更新不再采用该模式。
- 回归测试位于 `backend/tests/test_database_concurrency.py`：覆盖旧 DEFERRED 模式下的读后写竞争、跨连接限流、旧对象计数、代理阈值，以及 32 个线程执行 300 次混合请求写入（含 RequestLog）。该测试验证一致性，不代表端到端 300 请求/秒容量。
- 未来迁移 PostgreSQL：表使用标准类型，但需要另行配置驱动、连接参数和存量数据迁移；SQLite 的 WAL/IMMEDIATE 选项仅适用于 SQLite。

## WAL 存储与备份

WAL 模式运行期间，数据库旁可能出现 `db.sqlite3-wal` 和 `db.sqlite3-shm`；已提交数据可能仍在 WAL 文件中。数据目录必须可写，并与数据库一起挂载在本机磁盘上，不能只挂载单个数据库文件；不使用 NFS 等网络文件系统。保持默认持久化级别，不为吞吐关闭同步写盘。

首次升级开启 WAL 时先停止旧版本服务，再启动新版本，使新连接统一应用配置；无需表结构迁移。运行期间备份使用 SQLite backup API，避免只复制主数据库文件造成数据缺失。宿主机在 `backend/` 下可执行（按实际部署修改路径）：

```bash
uv run python - <<'PY'
import sqlite3
from datetime import datetime

destination = "../data/backup-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".sqlite3"
with sqlite3.connect("file:../data/db.sqlite3?mode=ro", uri=True) as source:
    with sqlite3.connect(destination) as backup:
        source.backup(backup)
print(destination)
PY
```

长时间不结束的读事务会阻碍 WAL 回收；应监控磁盘占用，并保持日志查询分页及事务及时结束。不要在服务运行时删除 WAL/SHM 文件。
