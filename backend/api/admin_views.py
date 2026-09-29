from __future__ import annotations

import hmac
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import (
    AIModel, NvidiaApiKey, NvidiaApiKeyStatus, Proxy, ProxyStatus,
    RequestLog, SystemSetting, UserApiKey,
)
from services import api_key_service, key_service, nvidia_service, proxy_service
from services.proxy_checker import check_all, check_proxy_retry

from .auth import AdminRequiredMixin, check_login_allowed, note_login_failure
from .serializers import (
    ModelSerializer, NvidiaKeySerializer, ProxySerializer,
    ProxyWriteSerializer, RequestLogSerializer, SettingSerializer, UserApiKeySerializer,
)


class LoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        if not check_login_allowed(request):
            return Response(
                {"detail": "尝试次数过多，请 5 分钟后再试"},
                status=429, headers={"Retry-After": "300"},
            )
        u = str(request.data.get("username", ""))
        p = str(request.data.get("password", ""))
        u_ok = hmac.compare_digest(u.encode("utf-8"), str(settings.ADMIN_USERNAME).encode("utf-8"))
        p_ok = hmac.compare_digest(p.encode("utf-8"), str(settings.ADMIN_PASSWORD).encode("utf-8"))
        if u_ok and p_ok:
            return Response({"token": settings.ADMIN_TOKEN})
        note_login_failure(request)
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


class NvidiaKeyBulkView(AdminRequiredMixin, APIView):
    """Bulk actions on NVIDIA keys: {action: enable|disable|test, ids: [...]}.
    ids omitted = all keys."""

    def post(self, request):
        action = request.data.get("action", "")
        ids = request.data.get("ids") or None
        qs = NvidiaApiKey.objects.all()
        if ids:
            qs = qs.filter(pk__in=ids)
        if action == "enable":
            updated = qs.update(
                status=NvidiaApiKeyStatus.AVAILABLE, cooldown_until=None)
        elif action == "disable":
            updated = qs.update(status=NvidiaApiKeyStatus.DISABLED)
        elif action == "test":
            results = []
            for rec in qs:
                results.append({"id": rec.id, **key_service.test_key(rec)})
            return Response({"tested": len(results), "results": results})
        else:
            return Response({"error": {"message": "action must be enable/disable/test",
                                       "code": "bad_request"}}, status=400)
        return Response({"updated": updated})


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
        return Response(NvidiaKeySerializer(rec).data)

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
        # Warn if enabled proxies now exceed the new limit (surfaced in UI).
        over = Proxy.objects.filter(enabled=True).count() - proxy_service.max_proxies_for_current_keys()
        return Response(status=204, headers={"X-Proxy-Over-Limit": str(max(over, 0))})


class NvidiaKeyTestView(AdminRequiredMixin, APIView):
    def post(self, request, pk):
        try:
            rec = NvidiaApiKey.objects.get(pk=pk)
        except NvidiaApiKey.DoesNotExist:
            return Response({"detail": "not found"}, status=404)
        return Response(key_service.test_key(rec))


# ---------------------------------------------------------------- proxies

class ProxyListView(AdminRequiredMixin, APIView):
    def get(self, request):
        qs = Proxy.objects.order_by("id")
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


class ProxyBulkView(AdminRequiredMixin, APIView):
    """Bulk actions on proxies: {action: enable|disable|delete|check, ids: [...]}.
    For enable, the backend proxy limit is enforced per the current key count."""

    def post(self, request):
        action = request.data.get("action", "")
        ids = request.data.get("ids") or None
        qs = Proxy.objects.all()
        if ids:
            qs = qs.filter(pk__in=ids)
        if action == "enable":
            enabled_n = 0
            skipped = 0
            for p in qs:
                ok, _msg = proxy_service.set_enabled(p, True)
                if ok:
                    enabled_n += 1
                else:
                    skipped += 1
            return Response({"updated": enabled_n, "skipped": skipped})
        if action == "disable":
            updated = qs.update(enabled=False, status=ProxyStatus.DISABLED)
            return Response({"updated": updated})
        if action == "delete":
            deleted, _ = qs.delete()
            return Response({"deleted": deleted})
        if action == "check":
            return Response(proxy_service.run_async(check_all()))
        return Response({"error": {"message": "action must be enable/disable/delete/check",
                                   "code": "bad_request"}}, status=400)


class ProxyDetailView(AdminRequiredMixin, APIView):
    def _get(self, pk):
        try:
            return Proxy.objects.get(pk=pk)
        except Proxy.DoesNotExist:
            return None

    def patch(self, request, pk):
        p = self._get(pk)
        if not p:
            return Response({"detail": "not found"}, status=404)
        cred_changed = any(f in request.data for f in ("host", "port", "protocol", "username", "password"))
        if "enabled" in request.data:
            ok, msg = proxy_service.set_enabled(p, bool(request.data["enabled"]))
            if not ok:
                return Response(
                    {"error": {"message": msg, "code": "proxy_limit_exceeded"}}, status=400
                )
        for f in ("name", "protocol", "host", "port", "username"):
            if f in request.data:
                setattr(p, f, request.data[f])
        if "password" in request.data:
            pwd = request.data["password"] or ""
            # mask char means "unchanged"; empty string or a real value updates
            if pwd != "••••••":
                p.password = pwd
        if cred_changed:
            # endpoint changed -> previously measured latency/IP/status no longer valid
            p.status = ProxyStatus.UNKNOWN
            p.latency_ms = None
            p.public_ip = ""
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
            return Response(
                {"error": {"message": str(exc), "code": "upstream_error"}},
                status=502,
            )


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
        if "allowed_models" in request.data:
            models = request.data["allowed_models"]
            if models is None:
                models = []
            if not isinstance(models, list) or not all(isinstance(m, str) for m in models):
                return Response(
                    {"error": {"message": "allowed_models must be a list of model names",
                               "code": "bad_request"}}, status=400)
            rec.allowed_models = models
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
        key_id = request.query_params.get("api_key")
        since = request.query_params.get("since")
        until = request.query_params.get("until")
        if model:
            qs = qs.filter(model__icontains=model)
        if status:
            qs = qs.filter(status=status)
        if key_id:
            qs = qs.filter(user_api_key_id=key_id)
        if since:
            qs = qs.filter(created_at__gte=since)
        if until:
            qs = qs.filter(created_at__lte=until)

        try:
            limit = min(max(int(request.query_params.get("limit", 200)), 1), 1000)
        except ValueError:
            limit = 200
        try:
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except ValueError:
            offset = 0

        total = qs.count()
        rows = list(qs[offset:offset + limit])
        data = RequestLogSerializer(rows, many=True).data
        return Response({
            "results": data,
            "total": total,
            "limit": limit,
            "offset": offset,
            "next_offset": offset + limit if offset + limit < total else None,
        })


class DashboardView(AdminRequiredMixin, APIView):
    def get(self, request):
        from django.db.models import Avg, Count, Sum

        today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        keys = NvidiaApiKey.objects.all()
        proxies = Proxy.objects.all()
        logs_today = RequestLog.objects.filter(created_at__gte=today)

        key_status = {s: keys.filter(status=s).count() for s, _ in NvidiaApiKeyStatus.choices}
        proxy_status = {s: proxies.filter(status=s).count() for s, _ in ProxyStatus.choices}
        today_count = logs_today.count()
        success_count = logs_today.filter(status="success").count()
        agg = logs_today.filter(status="success").aggregate(
            avg_ms=Avg("duration_ms"), total_tokens=Sum("total_tokens"))

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
            "avg_latency_s": round((agg["avg_ms"] or 0) / 1000, 2),
            "tokens_today": agg["total_tokens"] or 0,
            "active_requests": settings.MAX_CONCURRENT_REQUESTS - _request_semaphore_free(),
            "key_status": key_status,
            "proxy_status": proxy_status,
        })


def _request_semaphore_free() -> int:
    from api.openai_views import _request_semaphore
    with _request_semaphore._cond:
        return _request_semaphore._value


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
        days = max(1, min(int(request.query_params.get("days", 7)), 30))
        today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
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
        Uses the shared asyncio loop; chunks are pumped through a queue so the
        event loop is never blocked by the Django generator.
        """
        import json
        import queue as _queue
        import time

        from django.http import StreamingHttpResponse

        from services.load_balancer import build_routes
        from services.loop import run_coroutine
        from services.race_engine import AllRoutesFailed, NoRouteAvailable, race_stream

        routes = build_routes()
        request_id = key_service.new_request_id()
        log = RequestLog.objects.create(
            request_id=request_id, model=model, routes_count=len(routes), is_stream=True
        )
        # Ask upstream for usage in the last SSE chunk so we can record tokens.
        body = dict(body)
        opts = body.get("stream_options")
        body["stream_options"] = {**(opts if isinstance(opts, dict) else {}),
                                  "include_usage": True}
        if not routes:
            log.status, log.http_status, log.error_type = "error", 503, "no_available_route"
            log.save()
            return Response({"error": {"message": "当前没有可用线路",
                                       "code": "no_available_route"}}, status=503)

        t0 = time.monotonic()
        try:
            winner = run_coroutine(race_stream(routes, body, settings.NVIDIA_BASE_URL))
        except (NoRouteAvailable, AllRoutesFailed) as exc:
            log.status, log.http_status, log.error_type = "error", 502, "all_routes_failed"
            if isinstance(exc, AllRoutesFailed):
                log.routes = exc.report
            log.save()
            resp = Response({"error": {"message": f"所有线路均失败: {exc}",
                                       "code": "upstream_error"},
                             "routes": exc.report if isinstance(exc, AllRoutesFailed) else []},
                            status=502)
            return resp
        except Exception as exc:  # noqa: BLE001
            log.status, log.error_type = "error", "stream_error"
            log.save()
            return Response({"error": {"message": f"stream error: {exc}",
                                       "code": "stream_error"}}, status=502)

        duration = round((time.monotonic() - t0) * 1000, 1)
        log.status, log.http_status = "success", 200
        log.duration_ms = duration
        log.first_token_ms = duration
        log.winner_route_type = winner.route.kind
        log.winner_key_name = winner.route.key.name
        log.winner_proxy_name = winner.route.proxy.name if winner.route.proxy else ""
        log.proxy_public_ip = winner.route.proxy.public_ip if winner.route.proxy else ""
        log.routes = winner.report or []
        log.save()

        q: _queue.Queue = _queue.Queue()
        SENTINEL = object()

        async def _pump():
            usage: dict = {}
            try:
                async for chunk in winner.lines():
                    try:
                        payload = json.loads(chunk[5:].strip()) if chunk.startswith("data:") else {}
                        if isinstance(payload, dict) and payload.get("usage"):
                            usage = payload["usage"]
                    except Exception:  # noqa: BLE001
                        pass
                    q.put(chunk)
            except Exception as exc:  # noqa: BLE001
                q.put(SENTINEL)
                q.put(exc)
                return
            finally:
                await winner.close()
            q.put(SENTINEL)
            q.put(usage)

        run_coroutine(_pump())

        def gen():
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

            usage: dict = {}
            while True:
                item = q.get()
                if item is SENTINEL:
                    nxt = q.get()
                    if isinstance(nxt, Exception):
                        log.status, log.error_type = "error", "stream_error"
                        log.save()
                        yield "data: " + json.dumps({
                            "error": {"message": f"stream error: {nxt}", "type": "api_error",
                                      "param": None, "code": "stream_error"}
                        }) + "\n\n"
                        yield "data: [DONE]\n\n"
                        return
                    usage = nxt or {}
                    break
                yield item

            total_ms = round((time.monotonic() - t0) * 1000, 1)
            log.duration_ms = total_ms
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

        response = StreamingHttpResponse(gen(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
