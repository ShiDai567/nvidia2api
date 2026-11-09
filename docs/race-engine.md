# 竞速引擎（services/race_engine.py）

不是"依次重试"，是真正的并行。

## 线路构建

```
D = min(direct_routes_per_request, 可用 Key 数, max_routes_per_request)
N = min(可调度代理数 + D, 可用 Key 数, max_routes_per_request)
route[0:D] = 直连 + 各自独立的 Key
route[D:N] = proxy[0:N-D] + 各自独立的 Key
```

`direct_routes_per_request` 默认 1，至少 1；管理后台“设置 → 每次请求并行直连数”保存后立即生效。直连优先占用名额；Key 不足或总线路上限较低时自动缩减。代理启用上限为 `max(未禁用 Key 数 - 配置直连数, 0)`，增加直连数后已有超额代理保留配置，构建线路时按剩余名额裁剪。

每个 Key 通过 `claim_rpm_slot` 原子地领到窗口配额后才进线路，一次请求内没有 Key 复用。若配额被并发请求抢占，会继续尝试后续可用 Key；最终线路数可少于计划数量。竞速引擎对所有直连与代理线路使用相同的有效响应判定。

## 有效响应判定

非流式 `is_valid_response`：
- HTTP 200
- JSON 里有非空 `choices`
- 首 choice 的 `message`/`delta`/`text` 至少一个有内容
- 不能有 `error` 字段

流式首 chunk 判定 `is_valid_stream_chunk`：
- 以 `data:` 开头
- JSON 可解析、非 `[DONE]`
- 有 `choices`、无 `error`

**HTTP 200 本身不构成成功**：上游 200 但 body 是错误对象、或流为空，都被视为失败（`invalid_response` / `empty_stream`）。

## 竞速循环（非流式）

```python
pending = {task(route_i): route_i}
while pending:
    done, pending = await wait(pending, return_when=FIRST_COMPLETED)
    for t in done:
        r = t.result()
        if r.ok:
            cancel(*pending); report.append(winner); return r
        report.append(failed(r.error_type))
raise AllRoutesFailed(errors, report)
```

时间维度独立计时（每线路自己的 latency_ms），报告里保存每条线路的 winner/failed/cancelled 结果，最终写入 `RequestLog.routes`。

## 流式竞速

```
route_i ── open POST stream ──► 等第一个有效 SSE chunk
                                     │
首选有效 chunk ──────────────────────┤ Winner
                                     ▼
                              其余线路 cancel + 释放 httpx Client
```

后台对话接口先返回 `StreamingHttpResponse`，并异步等待 `race_stream`；等待首个有效 chunk 期间每 5 秒发 SSE 注释心跳，避免线路连接或慢模型触发反向代理读超时。对外 `/v1` 流式接口仍在响应头发出前同步确定 Winner，以保留真实 HTTP 502/503。

`race_stream_winner` 返回 `StreamWinner(route, cm, req_cm, ait, first_line, report)`，调用方随后将首个 chunk 与后续 `aiter_lines()` 转发出去。后台接口竞速失败时，由于 SSE 响应已经开始，错误通过 SSE `error` 事件传递，而不是更改 HTTP 状态码。

只在第一条 `data:` 有效时才算 Winner；第一条 `data:` 无效直接判 `invalid_response`，不等完整流。

### 转发（必须非阻塞）

Winner 确认后，视图起一个"泵"协程把 `winner.lines()` 写入 `queue.Queue`，Django 生成器再从中逐条 `yield`。泵**必须**用 `services.loop.submit_coroutine()` 提交（fire-and-forget），不能用会阻塞到协程结束的 `run_coroutine()`：

- 用 `submit_coroutine`：视图立即返回 `StreamingHttpResponse`，上游 chunk 边到边发（真正的逐字流式）。
- 若误用 `run_coroutine`：视图会在返回响应前先把**整条上游流**读完塞进队列，客户端直到 `[DONE]` 才一次性收到全部内容（表现为"不流式"）。

`race_stream_winner`（取 Winner）仍然用 `run_coroutine` 阻塞等待，以保证竞速失败时能返回真实的 502/503——只有"泵送"阶段需要非阻塞。

## 故障分级

| 现象 | error_type | 处置 |
|---|---|---|
| HTTP 401/403 | invalid_key / forbidden | Key → `invalid` |
| HTTP 429 | rate_limited | Key → `rate_limited` + 冷却 60s |
| HTTP 404 | model_not_found | 不再尝试其他线路由用户换模型 |
| HTTP 5xx | upstream_server_error | 冷却 60s |
| 本地文件不存在（例如 CA bundle 路径无效） | local_file_error | 记录为部署配置问题；不惩罚 Key 或代理，检查 SSL_CERT_FILE / SSL_CERT_DIR / 代理配置 |
| 代理 connect/timeout | connect_error / timeout / network_error | 代理计数失败；连续 3 次标记 unhealthy + 冷却 |
| 200 但无 choices | invalid_response | 30s 冷却 |

代理与 Key 的失败互不影响：单个 Key 失效不会抑制代理，反之亦然。
所有线路失败时，502 错误摘要会附线路名与上游 HTTP 状态（若有）；详情同时保存在 `routes`，可用于区分 Key 拒绝、模型错误、限流和本地网络/证书故障。

## 取消语义

```
对 pending 任务 cancel() → gather(return_exceptions=True)
httpx.AsyncClient 在 __aexit__ 释放连接池
Django 侧 StreamingHttpResponse 在 finally 里 winner.close()
```

不会残留后台 task 或-connection。
