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

- **非流式**：竞速在返回前完成——直接返回 NVIDIA 原始 JSON，或对应的错误状态码。
- **流式**：竞速同样在返回前完成。所有线路失败时返回真实的 502/503 + OpenAI 风格 JSON 错误（**不会**返回 200 后在流里塞错误）；有 Winner 时返回 `200 + text/event-stream`，上游 chunk 透传，结尾 `data: [DONE]`。
- 响应头 `X-Request-Id` 可用于在请求日志页定位记录。
- 平台自动注入 `stream_options.include_usage` 以记录 token 用量（对用户透明）。

## 错误格式

与 OpenAI 完全一致：

```json
{"error": {"message": "…", "type": "api_error", "param": null, "code": "invalid_request"}}
```

| HTTP | code | 备注 |
|---|---|---|
| 400 | `invalid_request` | |
| 401 | `invalid_api_key` | |
| 403 | `key_disabled` / `model_not_allowed` | Key 被禁用 / Key 的 allowed_models 不含该模型 |
| 404 | `model_not_found` | 模型不存在或未在控制台启用 |
| 413 | `payload_too_large` | 请求体 > 4MB |
| 429 | `rate_limit_exceeded` / `server_overloaded` | 带 `Retry-After` 头 |
| 502 | `upstream_error` | 所有线路均失败 |
| 503 | `no_available_route` | 没有可用 NVIDIA Key/线路 |

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

全局并发上限 `MAX_CONCURRENT_REQUESTS`（线程 semaphore）。
