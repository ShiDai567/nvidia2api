from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import (
    AIModel, NvidiaApiKey, NvidiaApiKeyStatus, Proxy, ProxyGroup, ProxyStatus,
    RequestLog, SystemSetting, UserApiKey,
)
from services import api_key_service, key_service, nvidia_service, proxy_service
from services.proxy_checker import check_all, check_proxy_retry

from .auth import AdminRequiredMixin
from .serializers import (
    ModelSerializer, NvidiaKeySerializer, ProxyGroupSerializer, ProxySerializer,
    ProxyWriteSerializer, RequestLogSerializer, SettingSerializer, UserApiKeySerializer,
)


class LoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        u = request.data.get("username", "")
        p = request.data.get("password", "")
        if u == settings.ADMIN_USERNAME and p == settings.ADMIN_PASSWORD:
            return Response({"token": settings.ADMIN_TOKEN})
        return Response({"detail": "Invalid credentials"}, status=401)


# ---------------------------------------------------------------- nvidia keys

class NvidiaKeyListView(AdminRequiredMixin, APIView):
    def get(self, request):
        qs = NvidiaApiKey.objects.order_by("id")
        return Response(NvidiaKeySerializer(qs, many=True).data)

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        key = (request.data.get("api_key") or "").strip()
        rpm = int(request.data.get("rpm_limit") or settings.DEFAULT_NVIDIA_RPM)
        if not key:
            return Response({"error": {"message": "api_key required", "code": "bad_request"}}, status=400)
        if NvidiaApiKey.objects.filter(api_key=key).exists():
            return Response({"error": {"message": "duplicate key", "code": "duplicate"}}, status=400)
        if not name:
            name = f"NVIDIA Key {NvidiaApiKey.objects.count() + 1:03d}"
        rec = NvidiaApiKey.objects.create(name=name, api_key=key, rpm_limit=rpm)
        return Response(NvidiaKeySerializer(rec).data, status=201)


class NvidiaKeyImportView(AdminRequiredMixin, APIView):
    def post(self, request):
        text = request.data.get("text", "")
        if not text.strip():
            return Response({"error": {"message": "text required", "code": "bad_request"}}, status=400)
        return Response(key_service.bulk_import_keys(text))


class NvidiaKeyDetailView(AdminRequiredMixin, APIView):
    def _get(self, pk):
        try:
            return NvidiaApiKey.objects.get(pk=pk)
        except NvidiaApiKey.DoesNotExist:
            return None

    def get(self, request, pk):
        rec = self._get(pk)
        if not rec:
            return Response({"detail": "not found"}, status=404)
        data = NvidiaKeySerializer(rec).data
        if request.query_params.get("reveal") == "1":
            data["api_key"] = rec.api_key
        return Response(data)

    def patch(self, request, pk):
        rec = self._get(pk)
        if not rec:
            return Response({"detail": "not found"}, status=404)
        name = request.data.get("name")
        if name:
            rec.name = name.strip()
        if "rpm_limit" in request.data:
            rec.rpm_limit = int(request.data["rpm_limit"])
        action = request.data.get("action")
        enabled = request.data.get("enabled")
        if enabled is False or action == "disable":
            rec.status = NvidiaApiKeyStatus.DISABLED
        elif enabled is True or action == "enable":
            rec.status = NvidiaApiKeyStatus.AVAILABLE
            rec.cooldown_until = None
        rec.save()
        return Response(NvidiaKeySerializer(rec).data)

    def delete(self, request, pk):
        rec = self._get(pk)
        if not rec:
            return Response({"detail": "not found"}, status=404)
        rec.delete()
        return Response(status=204)


class NvidiaKeyTestView(AdminRequiredMixin, APIView):
    def post(self, request, pk):
        try:
            rec = NvidiaApiKey.objects.get(pk=pk)
        except NvidiaApiKey.DoesNotExist:
            return Response({"detail": "not found"}, status=404)
        return Response(key_service.test_key(rec))


# ---------------------------------------------------------------- proxies

class ProxyGroupListView(AdminRequiredMixin, APIView):
    def get(self, request):
        qs = ProxyGroup.objects.annotate(proxy_count=Count("proxies")).order_by("id")
        return Response(ProxyGroupSerializer(qs, many=True).data)

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"error": {"message": "name required", "code": "bad_request"}}, status=400)
        if ProxyGroup.objects.filter(name=name).exists():
            return Response({"error": {"message": "duplicate group", "code": "duplicate"}}, status=400)
        g = ProxyGroup.objects.create(
            name=name,
            description=request.data.get("description", ""),
            country=request.data.get("country", ""),
            enabled=request.data.get("enabled", True),
        )
        data = ProxyGroupSerializer(g).data
        data["proxy_count"] = 0
        return Response(data, status=201)


class ProxyGroupDetailView(AdminRequiredMixin, APIView):
    def _get(self, pk):
        try:
            return ProxyGroup.objects.get(pk=pk)
        except ProxyGroup.DoesNotExist:
            return None

    def patch(self, request, pk):
        g = self._get(pk)
        if not g:
            return Response({"detail": "not found"}, status=404)
        for f in ("name", "description", "country", "enabled"):
            if f in request.data:
                setattr(g, f, request.data[f])
        g.save()
        data = ProxyGroupSerializer(g).data
        data["proxy_count"] = Proxy.objects.filter(group=g).count()
        return Response(data)

    def delete(self, request, pk):
        g = self._get(pk)
        if not g:
            return Response({"detail": "not found"}, status=404)
        Proxy.objects.filter(group=g).update(group=None)
        g.delete()
        return Response(status=204)


class ProxyListView(AdminRequiredMixin, APIView):
    def get(self, request):
        qs = Proxy.objects.select_related("group").order_by("id")
        n_keys = NvidiaApiKey.objects.exclude(status=NvidiaApiKeyStatus.DISABLED).count()
        max_allowed = max(n_keys - 1, 0)
        enabled = qs.filter(enabled=True).count()
        return Response({
            "results": ProxySerializer(qs, many=True).data,
            "summary": {
                "nvidia_keys": n_keys,
                "max_enabled_proxies": max_allowed,
                "enabled_proxies": enabled,
                "direct_routes": 1 if n_keys else 0,
                "total_routes": enabled + (1 if n_keys else 0),
            },
        })

    def post(self, request):
        ser = ProxyWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if not request.data.get("name"):
            ser.validated_data["name"] = f"代理 {Proxy.objects.count() + 1:03d}"
        p = Proxy.objects.create(**ser.validated_data)
        return Response(ProxySerializer(p).data, status=201)


class ProxyImportView(AdminRequiredMixin, APIView):
    def post(self, request):
        text = request.data.get("text", "")
        if not text.strip():
            return Response({"error": {"message": "text required", "code": "bad_request"}}, status=400)
        return Response(proxy_service.bulk_import_proxies(text))


class ProxyDetailView(AdminRequiredMixin, APIView):
    def _get(self, pk):
        try:
            return Proxy.objects.select_related("group").get(pk=pk)
        except Proxy.DoesNotExist:
            return None

    def patch(self, request, pk):
        p = self._get(pk)
        if not p:
            return Response({"detail": "not found"}, status=404)
        if "enabled" in request.data:
            ok, msg = proxy_service.set_enabled(p, bool(request.data["enabled"]))
            if not ok:
                return Response(
                    {"error": {"message": msg, "code": "proxy_limit_exceeded"}}, status=400
                )
        for f in ("name", "protocol", "host", "port", "username", "password", "group"):
            if f in request.data:
                setattr(p, f, request.data[f])
        p.save()
        return Response(ProxySerializer(p).data)

    def delete(self, request, pk):
        p = self._get(pk)
        if not p:
            return Response({"detail": "not found"}, status=404)
        p.delete()
        return Response(status=204)


class ProxyFetchIpView(AdminRequiredMixin, APIView):
    """获取代理公网 IP 与归属地（多次尝试，风控响应不计为代理失败）。"""

    def post(self, request, pk):
        try:
            p = Proxy.objects.get(pk=pk)
        except Proxy.DoesNotExist:
            return Response({"detail": "not found"}, status=404)
        return Response(proxy_service.run_async(check_proxy_retry(p)))


class ProxyCheckAllView(AdminRequiredMixin, APIView):
    """一键检测全部启用代理（低并发 + 错峰，防风控；风控不计失败）。"""

    def post(self, request):
        return Response(proxy_service.run_async(check_all()))


# ---------------------------------------------------------------- models

class ModelListView(AdminRequiredMixin, APIView):
    def get(self, request):
        qs = AIModel.objects.order_by("model_name")
        q = request.query_params.get("q")
        if q:
            qs = qs.filter(model_name__icontains=q)
        return Response(ModelSerializer(qs, many=True).data)

    def post(self, request):
        name = (request.data.get("model_name") or "").strip()
        if not name:
            return Response({"error": {"message": "model_name required", "code": "bad_request"}}, status=400)
        rec, created = AIModel.objects.get_or_create(model_name=name, defaults={
            "display_name": request.data.get("display_name", ""),
            "description": request.data.get("description", ""),
            "enabled": request.data.get("enabled", False),
        })
        return Response(ModelSerializer(rec).data, status=201 if created else 200)


class ModelSyncView(AdminRequiredMixin, APIView):
    def post(self, request):
        try:
            return Response(nvidia_service.sync_models())
        except ValueError as exc:
            msg = str(exc)
            code = "no_available_key" if msg == "no_available_nvidia_key" else "upstream_error"
            status = 503 if code == "no_available_key" else 502
            return Response({"error": {"message": msg, "code": code}}, status=status)


class ModelDetailView(AdminRequiredMixin, APIView):
    def _get(self, pk):
        try:
            return AIModel.objects.get(pk=pk)
        except AIModel.DoesNotExist:
            return None

    def patch(self, request, pk):
        rec = self._get(pk)
        if not rec:
            return Response({"detail": "not found"}, status=404)
        for f in ("display_name", "description", "enabled", "status"):
            if f in request.data:
                setattr(rec, f, request.data[f])
        rec.save()
        return Response(ModelSerializer(rec).data)

    def delete(self, request, pk):
        rec = self._get(pk)
        if not rec:
            return Response({"detail": "not found"}, status=404)
        rec.delete()
        return Response(status=204)


# ---------------------------------------------------------------- user api keys

class UserApiKeyListView(AdminRequiredMixin, APIView):
    def get(self, request):
        return Response(UserApiKeySerializer(UserApiKey.objects.order_by("-id"), many=True).data)

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"error": {"message": "name required", "code": "bad_request"}}, status=400)
        rec, raw = api_key_service.create_key(
            name, rate_limit=int(request.data.get("rate_limit") or 0)
        )
        data = UserApiKeySerializer(rec).data
        data["key"] = raw  # full key shown once at creation only
        return Response(data, status=201)


class UserApiKeyDetailView(AdminRequiredMixin, APIView):
    def _get(self, pk):
        try:
            return UserApiKey.objects.get(pk=pk)
        except UserApiKey.DoesNotExist:
            return None

    def patch(self, request, pk):
        rec = self._get(pk)
        if not rec:
            return Response({"detail": "not found"}, status=404)
        if "enabled" in request.data:
            rec.enabled = bool(request.data["enabled"])
        if "rate_limit" in request.data:
            rec.rate_limit = int(request.data["rate_limit"])
        if "name" in request.data:
            rec.name = request.data["name"]
        rec.save()
        return Response(UserApiKeySerializer(rec).data)

    def delete(self, request, pk):
        rec = self._get(pk)
        if not rec:
            return Response({"detail": "not found"}, status=404)
        rec.delete()
        return Response(status=204)


# ---------------------------------------------------------------- logs / dashboard / settings

class LogListView(AdminRequiredMixin, APIView):
    def get(self, request):
        qs = RequestLog.objects.order_by("-id")
        model = request.query_params.get("model")
        status = request.query_params.get("status")
        if model:
            qs = qs.filter(model=model)
        if status:
            qs = qs.filter(status=status)
        qs = qs[:200]
        return Response({"results": RequestLogSerializer(qs, many=True).data})


class DashboardView(AdminRequiredMixin, APIView):
    def get(self, request):
        today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        keys = NvidiaApiKey.objects.all()
        proxies = Proxy.objects.all()
        logs_today = RequestLog.objects.filter(created_at__gte=today)

        key_status = {s: keys.filter(status=s).count() for s, _ in NvidiaApiKeyStatus.choices}
        proxy_status = {s: proxies.filter(status=s).count() for s, _ in ProxyStatus.choices}
        today_count = logs_today.count()
        success_count = logs_today.filter(status="success").count()
        success_durations = logs_today.filter(duration_ms__gt=0)
        avg = 0.0
        if success_durations.exists():
            avg = round(sum(l.duration_ms for l in success_durations) / success_durations.count() / 1000, 2)

        n_active_keys = keys.exclude(status=NvidiaApiKeyStatus.DISABLED).count()
        enabled_proxies = proxies.filter(enabled=True).count()
        return Response({
            "nvidia_keys": keys.count(),
            "enabled_keys": keys.exclude(
                status__in=[NvidiaApiKeyStatus.DISABLED, NvidiaApiKeyStatus.INVALID]).count(),
            "proxies": proxies.count(),
            "enabled_proxies": enabled_proxies,
            "max_enabled_proxies": max(n_active_keys - 1, 0),
            "models": AIModel.objects.count(),
            "enabled_models": AIModel.objects.filter(enabled=True).count(),
            "requests_today": today_count,
            "success_rate": round(success_count / today_count * 100, 1) if today_count else 0.0,
            "avg_latency_s": avg,
            "key_status": key_status,
            "proxy_status": proxy_status,
        })


class SettingsView(AdminRequiredMixin, APIView):
    def get(self, request):
        from services import sysconfig
        return Response(sysconfig.all_params())

    def patch(self, request):
        from services import sysconfig
        updates = request.data.get("settings")
        if not isinstance(updates, dict):
            key = request.data.get("key")
            if not key:
                return Response({"detail": "settings or key required"}, status=400)
            updates = {key: request.data.get("value")}
        sysconfig.set_params(updates)
        return Response(sysconfig.all_params())


class DashboardUsageView(AdminRequiredMixin, APIView):
    """Per-day token usage + request counts for the dashboard chart."""

    def get(self, request):
        from collections import defaultdict
        days = max(1, min(int(request.query_params.get("days", 7)), 30))
        today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=days - 1)

        buckets: dict = {}
        cur = start
        while cur <= today:
            key = cur.strftime("%Y-%m-%d")
            buckets[key] = {"date": key, "prompt_tokens": 0, "completion_tokens": 0,
                            "total_tokens": 0, "requests": 0, "success": 0}
            cur += timedelta(days=1)

        logs = RequestLog.objects.filter(created_at__gte=start).values(
            "created_at", "prompt_tokens", "completion_tokens", "total_tokens", "status"
        )
        for row in logs:
            key = timezone.localtime(row["created_at"]).strftime("%Y-%m-%d")
            b = buckets.get(key)
            if not b:
                continue
            b["prompt_tokens"] += row["prompt_tokens"] or 0
            b["completion_tokens"] += row["completion_tokens"] or 0
            b["total_tokens"] += row["total_tokens"] or 0
            b["requests"] += 1
            if row["status"] == "success":
                b["success"] += 1
        return Response({"days": list(buckets.values())})


class AdminChatView(AdminRequiredMixin, APIView):
    """Playground: run a real chat completion through the race engine."""

    ALLOWED = {"model", "messages", "temperature", "top_p", "max_tokens",
               "frequency_penalty", "presence_penalty", "stream"}

    def post(self, request):
        from services.load_balancer import build_routes
        from services.race_engine import AllRoutesFailed, NoRouteAvailable, race_chat
        from services import key_service

        model = (request.data.get("model") or "").strip()
        prompt = request.data.get("prompt")
        messages = request.data.get("messages")
        if prompt and not messages:
            messages = [{"role": "user", "content": str(prompt)}]
        if not model or not messages:
            return Response({"error": {"message": "model and prompt/messages required",
                                       "code": "bad_request"}}, status=400)
        if not AIModel.objects.filter(model_name=model, enabled=True).exists():
            return Response({"error": {"message": f"模型 {model} 不存在或未启用",
                                       "code": "model_not_found"}}, status=404)

        body = {k: v for k, v in request.data.items() if k in self.ALLOWED and v is not None}
        body["model"] = model
        body["messages"] = messages

        if request.data.get("stream"):
            return self._stream(body, model)

        routes = build_routes()
        started = timezone.now().timestamp()
        request_id = key_service.new_request_id()
        log = RequestLog.objects.create(request_id=request_id, model=model,
                                        routes_count=len(routes))
        if not routes:
            log.status, log.http_status, log.error_type = "error", 503, "no_available_route"
            log.save()
            return Response({"error": {"message": "当前没有可用线路（没有可用的 NVIDIA Key）",
                                       "code": "no_available_route"}}, status=503)
        import time
        t0 = time.monotonic()
        try:
            result = race_chat(routes, body, settings.NVIDIA_BASE_URL)
        except AllRoutesFailed as exc:
            log.status, log.error_type = "error", "all_routes_failed"
            log.http_status = 502
            log.routes = exc.report
            log.save()
            return Response({"error": {"message": f"所有线路均失败: {exc}",
                                       "code": "upstream_error"},
                             "routes": exc.report}, status=502)
        except NoRouteAvailable:
            log.status, log.error_type = "error", "no_available_route"
            log.http_status = 503
            log.save()
            return Response({"error": {"message": "当前没有可用线路",
                                       "code": "no_available_route"}}, status=503)
        duration = round((time.monotonic() - t0) * 1000, 1)
        r = result.route
        usage = (result.payload or {}).get("usage") or {}
        log.status, log.http_status = "success", 200
        log.duration_ms = duration
        log.winner_route_type = r.kind
        log.winner_key_name = r.key.name
        log.winner_proxy_name = r.proxy.name if r.proxy else ""
        log.proxy_public_ip = r.proxy.public_ip if r.proxy else ""
        log.prompt_tokens = usage.get("prompt_tokens", 0) or 0
        log.completion_tokens = usage.get("completion_tokens", 0) or 0
        log.total_tokens = usage.get("total_tokens", 0) or 0
        log.cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
        log.routes = result.report or []
        log.save()
        return Response({
            "request_id": request_id,
            "payload": result.payload,
            "meta": {
                "route_type": r.kind,
                "key_name": r.key.name,
                "proxy_name": r.proxy.name if r.proxy else "",
                "duration_ms": duration,
                "usage": usage,
                "routes": result.report or [],
            },
        })

    def _stream(self, body, model):
        """SSE: race streaming connections, first valid chunk wins, rest cancelled.

        Emits a leading `data: {"meta": {...}}` event describing the winning route,
        then relays upstream chunks verbatim, terminated by data: [DONE].
        """
        import asyncio
        import json

        from django.http import StreamingHttpResponse

        from services import key_service
        from services.load_balancer import build_routes
        from services.race_engine import AllRoutesFailed, NoRouteAvailable, race_stream

        routes = build_routes()
        request_id = key_service.new_request_id()
        log = RequestLog.objects.create(
            request_id=request_id, model=model, routes_count=len(routes), is_stream=True
        )
        # Ask upstream for usage in the last SSE chunk so we can record tokens.
        body = dict(body)
        body.setdefault("stream_options", {}).update({"include_usage": True})
        if not routes:
            log.status, log.http_status, log.error_type = "error", 503, "no_available_route"
            log.save()
            return Response({"error": {"message": "当前没有可用线路",
                                       "code": "no_available_route"}}, status=503)

        def gen():
            import time
            t0 = time.monotonic()
            loop = asyncio.new_event_loop()
            winner = None
            try:
                winner = loop.run_until_complete(
                    race_stream(routes, body, settings.NVIDIA_BASE_URL))

                duration = round((time.monotonic() - t0) * 1000, 1)
                log.status, log.http_status = "success", 200
                log.duration_ms = duration
                log.winner_route_type = winner.route.kind
                log.winner_key_name = winner.route.key.name
                log.winner_proxy_name = winner.route.proxy.name if winner.route.proxy else ""
                log.proxy_public_ip = winner.route.proxy.public_ip if winner.route.proxy else ""
                log.routes = winner.report or []
                log.save()

                yield "data: " + json.dumps({
                    "meta": {
                        "request_id": request_id,
                        "route_type": winner.route.kind,
                        "key_name": winner.route.key.name,
                        "proxy_name": winner.route.proxy.name if winner.route.proxy else "",
                        "first_chunk_ms": duration,
                        "routes": winner.report or [],
                    }
                }) + "\n\n"

                stream = winner.lines()
                usage: dict = {}
                while True:
                    chunk = loop.run_until_complete(_next_line(stream))
                    if chunk is None:
                        break
                    # harvest usage snapshot if present
                    try:
                        payload = json.loads(chunk[5:].strip()) if chunk.startswith("data:") else {}
                        if isinstance(payload, dict) and payload.get("usage"):
                            usage = payload["usage"]
                    except Exception:  # noqa: BLE001
                        pass
                    yield chunk

                total_ms = round((time.monotonic() - t0) * 1000, 1)
                log.duration_ms = total_ms
                log.first_token_ms = duration
                log.prompt_tokens = usage.get("prompt_tokens", 0) or 0
                log.completion_tokens = usage.get("completion_tokens", 0) or 0
                log.total_tokens = usage.get("total_tokens", 0) or 0
                details = (usage.get("prompt_tokens_details") or {})
                log.cached_tokens = details.get("cached_tokens", 0) or 0
                log.save()
                yield "data: " + json.dumps({
                    "summary": {
                        "duration_ms": total_ms,
                        "first_token_ms": duration,
                        "prompt_tokens": log.prompt_tokens,
                        "completion_tokens": log.completion_tokens,
                        "total_tokens": log.total_tokens,
                        "cached_tokens": log.cached_tokens,
                    }
                }) + "\n\n"
            except (NoRouteAvailable, AllRoutesFailed) as exc:
                log.status, log.http_status, log.error_type = "error", 502, "all_routes_failed"
                if isinstance(exc, AllRoutesFailed):
                    log.routes = exc.report
                log.save()
                yield "data: " + json.dumps({
                    "error": {"message": f"所有线路均失败: {exc}", "type": "api_error",
                              "param": None, "code": "upstream_error"}
                }) + "\n\n"
                yield "data: [DONE]\n\n"
            except Exception as exc:  # noqa: BLE001
                log.status, log.error_type = "error", "stream_error"
                log.save()
                yield "data: " + json.dumps({
                    "error": {"message": f"stream error: {exc}", "type": "api_error",
                              "param": None, "code": "stream_error"}
                }) + "\n\n"
                yield "data: [DONE]\n\n"
            finally:
                try:
                    if winner is not None:
                        loop.run_until_complete(winner.close())
                except Exception:  # noqa: BLE001
                    pass
                loop.close()

        async def _next_line(ait):
            try:
                return await ait.__anext__()
            except StopAsyncIteration:
                return None

        response = StreamingHttpResponse(gen(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
