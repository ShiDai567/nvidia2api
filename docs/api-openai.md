# OpenAI 兼容 API（`/v1/*`）

## 认证

`Authorization: Bearer sk-nvidia2api-xxxxxxxx`

## 端点

### `GET /health`

健康检查（无需鉴权）。

### `GET /v1/models`

```json
{
  "object": "list",
  "data": [
    {"id": "meta/llama-3.3-70b-instruct", "object": "model", "created": 0, "owned_by": "nvidia"}
  ]
}
```

只包含 `enabled=true` 的模型；若用户 Key 配置了 `allowed_models`，只返回允许的模型。

### `POST /v1/chat/completions`

支持的参数（透传 NVIDIA；未列出的会被丢弃）：`model`、`messages`、`temperature`、`top_p`、`max_tokens`、`stream`、`stop`、`n`、`seed`、`frequency_penalty`、`presence_penalty`、`response_format`、`tools`、`tool_choice`。

- **非流式**：竞速在返回前完成——返回经内容审查的上游 JSON，成功响应顶层 `model` 统一使用本服务收到的请求 `model`；失败时返回对应错误状态码。
- **流式**：竞速同样在返回前完成。所有线路失败时返回真实的 502/503 + OpenAI 风格 JSON 错误（**不会**返回 200 后在流里塞错误）；有 Winner 时返回 `200 + text/event-stream`。成功的内容、工具调用、结束及 usage 分片的顶层 `model` 均使用请求模型名，审查补发分片同样处理；保留 `data: [DONE]`、心跳与错误事件。
- 模型名统一仅影响对外响应标识，上游请求的模型参数仍按请求透传，权限校验与日志 `model` 仍使用请求体模型。外层中转站如已改写模型，可通过约定请求头 `X-Original-Model` 传入原始名称；成功 JSON 和 SSE 分片优先使用该头的非空值，否则使用请求体 `model`。该头不会发往 NVIDIA；本服务无法从映射后的模型自动推导原始名称。
- ASGI 部署（包括 Docker 内的 Uvicorn）使用异步响应迭代器逐段发送 SSE，首段内容在上游生成结束前即可到达客户端。
- 响应头 `X-Request-Id` 可用于在请求日志页定位记录。
- 平台自动注入 `stream_options.include_usage` 以记录 token 用量（对用户透明）。
- 流式请求在发送 `data: [DONE]` 之前保存总耗时与已收到的 usage，避免下游收到结束标记立即关闭时丢失统计。上游不返回 usage 时，token 保持 0，但总耗时仍保存。
- 下游在结束前中断时保存已收到的用量与耗时，日志标记为 `error / client_disconnected / 499`；上游传输异常标记为 `stream_error / 502`。日志里的 499/502 表示结束原因，已发出的 SSE HTTP 200 无法追溯更改。首字时间表示竞速胜出时间，不能代替完整响应耗时。

### New API 模型映射配置

New API 渠道将 `google/gemini-3.1-pro` 映射到 `nvidia/nemotron-3.5-lightning-30b-a3b` 时，本服务收到的请求体 `model` 已是 Nemotron。要让响应使用原始别名，需升级到包含 `X-Original-Model` 支持的本服务版本，并在 New API 对应渠道的「参数覆盖」中合并以下操作：

```json
{
  "operations": [
    {
      "mode": "set_header",
      "path": "X-Original-Model",
      "value": "google/gemini-3.1-pro",
      "conditions": [
        {
          "path": "original_model",
          "mode": "full",
          "value": "google/gemini-3.1-pro"
        }
      ]
    }
  ]
}
```

此配置基于 New API 当前主分支的 `set_header` 操作和 `original_model` 条件上下文；旧版本需先确认支持这两个功能。一个渠道有多个别名时，每个别名添加一条对应条件与头值的操作。不要将 `{original_model}` 当作自动插值模板，当前核对的源码不会对 `set_header.value` 执行这种替换。

仅服务一个固定别名的渠道，也可在「请求头覆盖」设置 `{"X-Original-Model":"google/gemini-3.1-pro"}`；多个别名共用渠道时应使用上面的条件操作，避免全部返回同一个名称。不要覆盖渠道原有鉴权或其他自定义头配置。

配置后普通和流式响应的 `model` 应为 `google/gemini-3.1-pro`，New API 的「上游请求模型」仍可显示 Nemotron，因为它记录真实出站请求。对外别名不会改变实际模型能力，管理员应保留模型映射信息。

参考：[New API 参数覆盖源码](https://github.com/QuantumNous/new-api/blob/main/relay/common/override.go)、[渠道管理文档](https://docs.newapi.pro/zh/docs/guide/feature-guide/admin/channel)。

## 错误格式

与 OpenAI 完全一致：

```json
{"error": {"message": "…", "type": "api_error", "param": null, "code": "invalid_request"}}
```

| 用例 ID | HTTP | code | 备注 |
|---|---|---|---|
| EC-01 | 401 | `invalid_api_key` | 无效用户 API Key |
| EC-02 | 403 | `key_disabled` | 用户 API Key 被禁用 |
| EC-03 | 403 | `model_not_allowed` | Key 的 allowed_models 不含该模型 |
| EC-04 | 404 | `model_not_found` | 模型不存在或未在控制台启用 |
| EC-05 | 400 | `invalid_request` | |
| EC-06 | 413 | `payload_too_large` | 请求体 > 4MB |
| EC-07 | 429 | `rate_limit_exceeded` / `queue_full` / `queue_timeout` | 带 `Retry-After` 头 |
| EC-08 | 502 | `upstream_error` | 所有线路均失败 |
| EC-09 | 503 | `no_available_route` | 没有可用 NVIDIA Key/线路 |
| EC-10 | 待 API 契约裁定 | 待 API 契约裁定 | SRS-F-020 要求覆盖内部错误并返回 OpenAI 风格错误对象；状态映射、`error.code`、消息脱敏规则及运行时行为待确认/验证 |

注：参数校验失败（400/403/404/413）不计入用户 Key 的配额。

## 调用示例

```python
from openai import OpenAI
client = OpenAI(api_key="sk-nvidia2api-...", base_url="http://localhost:8000/v1")

r = client.chat.completions.create(
    model="meta/llama-3.3-70b-instruct",
    messages=[{"role": "user", "content": "你好"}],
    stream=True,
)
for chunk in r:
    delta = chunk.choices[0].delta
    if delta.reasoning_content:
        print("[思考]", delta.reasoning_content)
    if delta.content:
        print(delta.content, end="")
```

## 指标

每条请求都写入 RequestLog：

- `first_token_ms`（首 chunk 到达时间；只有流式）
- `duration_ms`（总耗时，流式里 [DONE] 时结算）
- `prompt/completion/total/cached_tokens`（流式会自动让上游带 `stream_options.include_usage`，非流式从 usage 字段取）
- `routes[]`（每条线路的 winner/failed/cancelled 明细）

## 保护

聊天接口采用按服务端到达时间排序的等待队列。同一到达时间按登记顺序处理；先鉴权并校验请求，通过后排队，排队不占用用户及 NVIDIA RPM 配额。当前没有启用且有效的 Key 时直接返回 503；Key 暂时冷却或 RPM 耗尽时等待恢复。

动态并发上限为 `min(max_concurrent_requests, floor(可调度 Key 数 / 单次计划竞速线路数))`。计划线路数沿用线路构建规则：`min(可调度代理数 + 配置直连数, 可调度 Key 数, max_routes_per_request)`，直连至少一条；没有可调度 Key 时容量为 0。例如 12 个可调度 Key、每次 3 条线路，允许同时执行 4 个对话。容量约每 0.2 秒重算；缩容时已开始的对话继续执行，等待活跃数降到新上限后才放行。

非流式对话执行完成后归还名额；流式对话在结束、上游错误或客户端断开并完成清理后归还，首字到达不会释放名额。此上限限制对话数量，不额外保证不同对话独占 Key；Key 的 RPM 仍通过数据库条件更新领取。后台 `/api/admin/chat` 的模型测试不进入此队列。

运行参数可在控制台设置，无需重启：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `max_concurrent_requests` | 环境变量 `MAX_CONCURRENT_REQUESTS`，默认 100 | 动态并发数的硬上限 |
| `max_queued_requests` | 1000 | 等待队列最大长度，不含执行中的对话 |
| `request_queue_timeout` | 120 秒 | 从聊天入口到达时刻开始计算的最大排队时间 |

队列满或超时返回 HTTP 429 与 OpenAI 风格错误，`error.code` 分别为 `queue_full`、`queue_timeout`，并带 `Retry-After: 1`。客户端应将响应头等待超时设为大于排队时间与上游首字等待时间之和；ASGI 下排队断开会移除等待项。

队列和活跃计数保存在单个后端进程内，与默认 Docker 单 Uvicorn worker 一致；多 worker 或多副本部署时各进程分别调度，不能将此上限视为集群共享上限。WSGI 下排队会占用请求线程，推荐使用默认 ASGI 部署。排队失败的请求不创建竞速日志；现有首字时间和总耗时从准入后开始计算，不含排队时间。
