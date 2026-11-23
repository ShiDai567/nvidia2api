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
- 流式请求在发送 `data: [DONE]` 前保存已收到的 token 用量与总耗时。下游提前断开时日志记录 `client_disconnected`（499），上游传输异常记录 `stream_error`（502）。

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
| EC-07 | 429 | `rate_limit_exceeded` / `server_overloaded` | 带 `Retry-After` 头 |
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

每个进程按 `max_concurrent_requests` 限制并发，默认取环境变量 `MAX_CONCURRENT_REQUESTS`（默认 100）。后台修改后对新请求生效。达到上限时立即返回 HTTP 429（`server_overloaded`），并附 `Retry-After: 1`。流式请求选出胜出线路并返回响应后释放名额。无可用线路时直接返回 HTTP 503（`no_available_route`）。
