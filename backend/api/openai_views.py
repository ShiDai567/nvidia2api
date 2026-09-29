"""OpenAI-compatible endpoints: GET /v1/models, POST /v1/chat/completions."""
from __future__ import annotations

import json
import logging
import threading
import time

from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt

from apps.core.models import AIModel, RequestLog
from services import api_key_service, key_service
from services.load_balancer import build_routes
from services.loop import run_coroutine
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
                                    request_id, user_key)

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
        return _with_request_id(JsonResponse(result.payload, status=200), request_id)
    finally:
        _request_semaphore.release()


def _with_request_id(resp, request_id: str):
    resp["X-Request-Id"] = request_id
    return resp


def _stream_response(routes, upstream_body, log, started, request_id, user_key):
    """Streaming with correct HTTP semantics: the race is resolved BEFORE the
    response object is returned, so callers get a real status code:
    502/503 with an OpenAI-style JSON error when every route fails, and 200 +
    SSE only when a winner exists.

    While streaming, the shared loop pumps chunks into a thread-safe queue;
    the Django generator drains it without blocking the event loop (no
    per-chunk run_until_complete).
    """
    import queue as _queue

    from services.race_engine import race_stream

    q: _queue.Queue = _queue.Queue()
    SENTINEL = object()

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

    async def _pump():
        usage: dict = {}
        try:
            async for chunk in w.lines():
                try:
                    if chunk.startswith("data:"):
                        payload = json.loads(chunk[5:].strip())
                        if isinstance(payload, dict) and payload.get("usage"):
                            usage = payload["usage"]
                except Exception:  # noqa: BLE001
                    pass
                q.put(chunk)
        except Exception as exc:  # noqa: BLE001
            logger.exception("stream pump failed")
            q.put(SENTINEL)
            q.put(exc)
            return
        finally:
            await w.close()
        q.put(SENTINEL)
        q.put(usage)

    run_coroutine(_pump())  # schedules the pump coroutine; returns immediately

    def gen():
        usage: dict = {}
        while True:
            item = q.get()
            if item is SENTINEL:
                nxt = q.get()
                if isinstance(nxt, Exception):
                    _finish_log(log, started, False, 502, "stream_error")
                    yield "data: " + json.dumps({
                        "error": {"message": f"stream error: {nxt}", "type": "api_error",
                                  "param": None, "code": "stream_error"}
                    }) + "\n\n"
                    yield "data: [DONE]\n\n"
                    return
                usage = nxt or {}
                break
            yield item
        log.duration_ms = round((time.monotonic() - started) * 1000, 1)
        log.prompt_tokens = usage.get("prompt_tokens", 0) or 0
        log.completion_tokens = usage.get("completion_tokens", 0) or 0
        log.total_tokens = usage.get("total_tokens", 0) or 0
        log.cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
        log.save()

    response = StreamingHttpResponse(gen(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
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
