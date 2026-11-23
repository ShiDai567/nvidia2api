"""OpenAI-compatible endpoints: GET /v1/models, POST /v1/chat/completions."""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import Future

from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt

from apps.core.models import AIModel, RequestLog
from services import api_key_service, key_service
from services.content_review import StreamContentReviewer, review_payload, review_text
from services.load_balancer import build_routes
from services.loop import run_coroutine, submit_coroutine
from services.race_engine import (
    AllRoutesFailed, NoRouteAvailable, race_chat,
)
from .auth import openai_error

logger = logging.getLogger("nvidia2api.openai")

_request_semaphore = threading.BoundedSemaphore(settings.MAX_CONCURRENT_REQUESTS)


def _authenticate(request):
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    return api_key_service.authenticate(auth[7:].strip())


def list_models(request):
    user_key = _authenticate(request)
    if user_key is None:
        return openai_error("Invalid API key", "invalid_api_key", 401, "authentication_error")
    if not user_key.enabled:
        return openai_error("API key disabled", "key_disabled", 403, "authentication_error")
    models = AIModel.objects.filter(enabled=True).order_by("model_name")
    allowed = getattr(user_key, "allowed_models", None) or []
    if allowed:
        models = models.filter(model_name__in=allowed)
    return JsonResponse({
        "object": "list",
        "data": [
            {
                "id": m.model_name,
                "object": "model",
                "created": int(m.created_at.timestamp()),
                "owned_by": m.provider,
            }
            for m in models
        ],
    })


ALLOWED_PARAMS = {
    "model", "messages", "temperature", "top_p", "max_tokens", "stream",
    "stop", "frequency_penalty", "presence_penalty", "response_format",
    "tools", "tool_choice", "n", "seed",
}


@csrf_exempt
def chat_completions(request):
    if request.method != "POST":
        return openai_error("Method not allowed", "method_not_allowed", 405)

    user_key = _authenticate(request)
    if user_key is None:
        return openai_error("Invalid API key", "invalid_api_key", 401, "authentication_error")
    if not user_key.enabled:
        return openai_error("API key disabled", "key_disabled", 403, "authentication_error")

    if len(request.body) > 4 * 1024 * 1024:
        return openai_error("Request body too large", "payload_too_large", 413)

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return openai_error("Invalid JSON body", "invalid_request", 400, "invalid_request_error")

    model_name = body.get("model", "")
    messages = body.get("messages")
    if not model_name or not isinstance(messages, list) or not messages:
        return openai_error("model and messages are required", "invalid_request",
                            400, "invalid_request_error")
    if not AIModel.objects.filter(model_name=model_name, enabled=True).exists():
        return openai_error(
            f"The model '{model_name}' does not exist or is not enabled. "
            f"Enable it in the console (Models page) or call GET /v1/models to list "
            f"available models.",
            "model_not_found", 404, "invalid_request_error")
    allowed = getattr(user_key, "allowed_models", None) or []
    if allowed and model_name not in allowed:
        return openai_error(
            f"The model '{model_name}' is not allowed for this API key",
            "model_not_allowed", 403, "invalid_request_error")

    # Rate-limit only after the request shape is known-good, so bad requests
    # don't burn the caller's quota.
    ok, reason = api_key_service.check_and_count(user_key)
    if not ok:
        if reason == "rate_limited":
            resp = openai_error("Rate limit exceeded", "rate_limit_exceeded", 429)
            resp["Retry-After"] = "60"
        else:
            resp = openai_error("API key disabled", "key_disabled", 403, "authentication_error")
        return resp

    if not _request_semaphore.acquire(blocking=False):
        resp = openai_error("Server busy, too many concurrent requests",
                            "server_overloaded", 429)
        resp["Retry-After"] = "1"
        return resp
    log = None
    try:
        stream = bool(body.get("stream"))
        upstream_body = {k: v for k, v in body.items() if k in ALLOWED_PARAMS and v is not None}

        request_id = key_service.new_request_id()
        routes = build_routes()
        log = RequestLog.objects.create(
            request_id=request_id, user_api_key=user_key, model=model_name,
            routes_count=len(routes), is_stream=stream,
        )
        started = time.monotonic()

        if not routes:
            api_key_service.record_result(user_key, False)
            _finish_log(log, started, False, 503, "no_available_route")
            return _with_request_id(
                openai_error("当前没有可用线路（没有可用的 NVIDIA Key）",
                             "no_available_route", 503), request_id)

        if stream:
            return _stream_response(routes, upstream_body, log, started,
                                    request_id, user_key, is_asgi=hasattr(request, "scope"))

        try:
            result = race_chat(routes, upstream_body, settings.NVIDIA_BASE_URL)
        except NoRouteAvailable:
            api_key_service.record_result(user_key, False)
            _finish_log(log, started, False, 503, "no_available_route")
            return _with_request_id(openai_error("当前没有可用线路", "no_available_route", 503),
                                    request_id)
        except AllRoutesFailed as exc:
            api_key_service.record_result(user_key, False)
            _finish_log(log, started, False, 502, "all_routes_failed", routes=exc.report)
            return _with_request_id(
                openai_error(f"所有线路均失败: {exc}", "upstream_error", 502), request_id)

        r = result.route
        usage = (result.payload or {}).get("usage") or {}
        _finish_log(log, started, True, result.http_status, "", route_kind=r.kind,
                    key_name=r.key.name, proxy_name=r.proxy.name if r.proxy else "",
                    proxy_ip=(r.proxy.public_ip if r.proxy else ""),
                    usage=usage, routes=result.report or [])
        api_key_service.record_result(user_key, True)
        payload = {**result.payload, "model": model_name}
        return _with_request_id(JsonResponse(review_payload(payload), status=200), request_id)
    finally:
        _request_semaphore.release()


def _with_request_id(resp, request_id: str):
    resp["X-Request-Id"] = request_id
    return resp


def _with_stream_model(chunk: str, model_name: str) -> str:
    """统一成功 SSE 分片的模型名，保留心跳、结束标记和错误事件。"""
    if not model_name or not chunk.startswith("data:"):
        return chunk
    try:
        payload = json.loads(chunk[5:].strip())
    except (ValueError, TypeError):
        return chunk
    if not isinstance(payload, dict) or "error" in payload:
        return chunk
    if "choices" not in payload and "usage" not in payload:
        return chunk
    payload["model"] = model_name
    return "data: " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n\n"


def _stream_response(routes, upstream_body, log, started, request_id, user_key, *, is_asgi=True):
    """Streaming with correct HTTP semantics: the race is resolved BEFORE the
    response object is returned, so callers get a real status code:
    502/503 with an OpenAI-style JSON error when every route fails, and 200 +
    SSE only when a winner exists.

    The upstream pump runs on the shared loop; an async queue bridges to the
    ASGI response loop with bounded capacity, preserving backpressure.
    """
    import asyncio

    from services.race_engine import race_stream
    from apps.core.models import ContentReviewRule

    SENTINEL = object()
    queue_ready: Future = Future()
    review_rules = list(ContentReviewRule.objects.filter(enabled=True).order_by("id").values_list(
        "forbidden_text", "replacement_text"
    ))
    review_enabled = bool(review_rules)
    stream_reviewer = StreamContentReviewer(review_rules) if review_enabled else None
    model_name = upstream_body.get("model", "")

    def outgoing_chunks(chunk):
        # 审查可能补发尾部分片，故在审查完成后统一模型名。
        chunks = stream_reviewer.process(chunk) if stream_reviewer else [chunk]
        for outgoing in chunks:
            yield _with_stream_model(outgoing, model_name)

    # Ask upstream to include usage in the final chunk so tokens can be logged.
    upstream_body = dict(upstream_body)
    opts = upstream_body.get("stream_options")
    upstream_body["stream_options"] = {**(opts if isinstance(opts, dict) else {}),
                                       "include_usage": True}

    try:
        winner = run_coroutine(race_stream(routes, upstream_body, settings.NVIDIA_BASE_URL))
    except NoRouteAvailable:
        api_key_service.record_result(user_key, False)
        _finish_log(log, started, False, 503, "no_available_route")
        return _with_request_id(openai_error("当前没有可用线路", "no_available_route", 503),
                                request_id)
    except AllRoutesFailed as exc:
        api_key_service.record_result(user_key, False)
        _finish_log(log, started, False, 502, "all_routes_failed", routes=exc.report)
        return _with_request_id(
            openai_error(f"所有线路均失败: {exc}", "upstream_error", 502), request_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("stream race failed")
        api_key_service.record_result(user_key, False)
        _finish_log(log, started, False, 502, "stream_error")
        return _with_request_id(
            openai_error(f"stream error: {exc}", "upstream_error", 502), request_id)

    # Winner confirmed — record it, then stream the remaining chunks.
    w = winner
    log.winner_route_type = w.route.kind
    log.winner_key_name = w.route.key.name
    log.winner_proxy_name = w.route.proxy.name if w.route.proxy else ""
    log.proxy_public_ip = w.route.proxy.public_ip if w.route.proxy else ""
    log.status = "success"
    log.http_status = 200
    log.first_token_ms = round((time.monotonic() - started) * 1000, 1)
    log.routes = w.report or []
    log.save()
    api_key_service.record_result(user_key, True)

    def save_usage(usage):
        log.duration_ms = round((time.monotonic() - started) * 1000, 1)
        log.prompt_tokens = usage.get("prompt_tokens", 0) or 0
        log.completion_tokens = usage.get("completion_tokens", 0) or 0
        log.total_tokens = usage.get("total_tokens", 0) or 0
        log.cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
        log.save()

    def extract_usage(chunk, usage):
        try:
            if chunk.startswith("data:"):
                payload = json.loads(chunk[5:].strip())
                if isinstance(payload, dict) and payload.get("usage"):
                    return payload["usage"]
        except (ValueError, TypeError):
            pass
        return usage

    def error_chunk(exc):
        return "data: " + json.dumps({
            "error": {"message": f"stream error: {exc}", "type": "api_error",
                      "param": None, "code": "stream_error"}
        }) + "\n\n"

    def sync_gen():
        usage = {}
        iterator = w.lines().__aiter__()

        async def next_chunk():
            return await anext(iterator, SENTINEL)

        try:
            while True:
                chunk = run_coroutine(next_chunk())
                if chunk is SENTINEL:
                    break
                usage = extract_usage(chunk, usage)
                yield from outgoing_chunks(chunk)
            save_usage(usage)
        except Exception as exc:  # noqa: BLE001
            logger.exception("stream pump failed")
            _finish_log(log, started, False, 502, "stream_error")
            yield error_chunk(exc)
            yield "data: [DONE]\n\n"
        finally:
            run_coroutine(w.close())

    async def _send(response_queue, response_loop, item):
        pending = asyncio.run_coroutine_threadsafe(response_queue.put(item), response_loop)
        await asyncio.wrap_future(pending)

    async def _pump():
        usage: dict = {}
        response_queue, response_loop = await asyncio.wrap_future(queue_ready)
        try:
            async for chunk in w.lines():
                usage = extract_usage(chunk, usage)
                for outgoing in outgoing_chunks(chunk):
                    await _send(response_queue, response_loop, outgoing)
        except Exception as exc:  # noqa: BLE001
            logger.exception("stream pump failed")
            await _send(response_queue, response_loop, SENTINEL)
            await _send(response_queue, response_loop, exc)
            return
        finally:
            await w.close()
        await _send(response_queue, response_loop, SENTINEL)
        await _send(response_queue, response_loop, usage)

    async def async_gen():
        from asgiref.sync import sync_to_async

        usage: dict = {}
        response_queue = asyncio.Queue(maxsize=1)
        pump_task = submit_coroutine(_pump())
        queue_ready.set_result((response_queue, asyncio.get_running_loop()))
        try:
            while True:
                item = await response_queue.get()
                if item is SENTINEL:
                    nxt = await response_queue.get()
                    if isinstance(nxt, Exception):
                        await sync_to_async(_finish_log, thread_sensitive=True)(
                            log, started, False, 502, "stream_error"
                        )
                        yield error_chunk(nxt)
                        yield "data: [DONE]\n\n"
                        return
                    usage = nxt or {}
                    break
                yield item
            await sync_to_async(save_usage, thread_sensitive=True)(usage)
        finally:
            if not pump_task.done():
                pump_task.cancel()

    response = StreamingHttpResponse(
        async_gen() if is_asgi else sync_gen(), content_type="text/event-stream"
    )
    # /v1 同样经过 Next.js 反代，避免 gzip 将流式分片缓冲到结束。
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"
    return _with_request_id(response, request_id)


def _finish_log(log: RequestLog, started: float, success: bool, http_status: int,
                error_type: str = "", route_kind: str = "", key_name: str = "",
                proxy_name: str = "", proxy_ip: str = "", usage: dict | None = None,
                routes: list | None = None):
    log.status = "success" if success else "error"
    log.http_status = http_status
    log.error_type = error_type
    log.duration_ms = round((time.monotonic() - started) * 1000, 1)
    if route_kind:
        log.winner_route_type = route_kind
        log.winner_key_name = key_name
        log.winner_proxy_name = proxy_name
        log.proxy_public_ip = proxy_ip
    if usage:
        log.prompt_tokens = usage.get("prompt_tokens", 0) or 0
        log.completion_tokens = usage.get("completion_tokens", 0) or 0
        log.total_tokens = usage.get("total_tokens", 0) or 0
        log.cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
    if routes:
        log.routes = routes
    log.save()


def _review_sse_chunks(chunks: list[str], rules=None) -> list[str]:
    """缓冲 SSE 文本后统一审查，确保跨 chunk 的违禁词也能命中。"""
    output = []
    trailing = []
    text_parts = {"content": [], "reasoning_content": []}
    template = None
    for chunk in chunks:
        if not chunk.startswith("data:"):
            output.append(chunk)
            continue
        raw = chunk[5:].strip()
        if raw == "[DONE]":
            continue
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            output.append(chunk)
            continue
        choices = payload.get("choices") if isinstance(payload, dict) else None
        delta = choices[0].get("delta") if choices else None
        fields = [key for key in text_parts if isinstance(delta.get(key), str)] \
            if isinstance(delta, dict) else []
        if fields:
            if template is None:
                template = (payload, choices[0], delta)
            for field in fields:
                text_parts[field].append(delta[field])
        else:
            (trailing if _is_trailing_sse_chunk(chunk) else output).append(chunk)
    if template is not None:
        payload, choice, delta = template
        for field, parts in text_parts.items():
            if parts:
                delta[field] = review_text("".join(parts), rules=rules)
        output.append("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n")
    output.extend(trailing)
    output.append("data: [DONE]\n\n")
    return output


def _is_trailing_sse_chunk(chunk: str) -> bool:
    try:
        data = json.loads(chunk[5:].strip())
        return bool(data.get("usage") or (
            data.get("choices") and data["choices"][0].get("finish_reason")
        ))
    except (ValueError, TypeError, KeyError):
        return False
