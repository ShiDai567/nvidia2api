"""End-to-end view tests: streaming must return real HTTP status codes,
validation errors must not consume rate-limit quota, and user keys honour
allowed_models restrictions."""
from __future__ import annotations

import json
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase

from apps.core.models import AIModel, NvidiaApiKey, UserApiKey
from services import api_key_service
from services.race_engine import RaceResult, StreamWinner


def _make_user_key(name="u1", rate_limit=0):
    rec, raw = api_key_service.create_key(name, rate_limit=rate_limit)
    return rec, raw


def _auth_header(raw):
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


def _streaming_body(response):
    if response.is_async:
        from asgiref.sync import async_to_sync

        async def collect():
            return b"".join([chunk async for chunk in response.streaming_content])

        return async_to_sync(collect)().decode()
    return b"".join(response.streaming_content).decode()


class ChatViewValidationTests(TestCase):
    def setUp(self):
        self.rec, self.raw = _make_user_key()
        AIModel.objects.create(model_name="m/test", enabled=True)

    def _post(self, body):
        from django.test import Client
        c = Client()
        return c.post("/v1/chat/completions", data=json.dumps(body),
                      content_type="application/json", **_auth_header(self.raw))

    def test_invalid_json_401_first(self):
        from django.test import Client
        c = Client()
        resp = c.post("/v1/chat/completions", data="{bad json",
                      content_type="application/json", **_auth_header(self.raw))
        self.assertEqual(resp.status_code, 400)

    def test_missing_model_400(self):
        resp = self._post({"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(resp.status_code, 400)

    def test_unknown_model_404_and_quota_not_burned(self):
        count_before = UserApiKey.objects.get(pk=self.rec.pk).total_requests
        resp = self._post({"model": "no/such", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(UserApiKey.objects.get(pk=self.rec.pk).total_requests, count_before)

    def test_forbidden_model_403(self):
        self.rec.allowed_models = ["other/model"]
        self.rec.save()
        resp = self._post({"model": "m/test", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(resp.status_code, 403)
        body = resp.json()
        self.assertEqual(body["error"]["code"], "model_not_allowed")

    def test_models_list_filtered_by_allowed(self):
        AIModel.objects.create(model_name="m/other", enabled=True)
        self.rec.allowed_models = ["m/test"]
        self.rec.save()
        from django.test import Client
        c = Client()
        resp = c.get("/v1/models", **_auth_header(self.raw))
        ids = [m["id"] for m in resp.json()["data"]]
        self.assertEqual(ids, ["m/test"])

    def test_health_endpoint(self):
        from django.test import Client
        c = Client()
        resp = c.get("/health")
        self.assertEqual(resp.status_code, 200)


class StreamingStatusTests(TestCase):
    """stream=true must return 502/503 (not 200) when the race fails."""

    def setUp(self):
        self.rec, self.raw = _make_user_key()
        AIModel.objects.create(model_name="m/test", enabled=True)
        NvidiaApiKey.objects.create(name="k1", api_key="nvapi-k1")

    def _post_stream(self):
        from django.test import Client
        c = Client()
        return c.post(
            "/v1/chat/completions",
            data=json.dumps({"model": "m/test", "stream": True,
                             "messages": [{"role": "user", "content": "hi"}]}),
            content_type="application/json", **_auth_header(self.raw),
        )

    def test_stream_all_failed_returns_502(self):
        from services.race_engine import AllRoutesFailed

        async def fake_race_stream(routes, body, base_url):
            raise AllRoutesFailed(["r0:timeout"], report=[])

        with patch("api.openai_views.race_stream", create=True,
                   new=None), \
             patch("services.race_engine.race_stream", fake_race_stream):
            resp = self._post_stream()
        self.assertEqual(resp.status_code, 502)
        body = resp.json()
        self.assertEqual(body["error"]["code"], "upstream_error")

    def test_stream_no_routes_returns_503(self):
        from services.race_engine import NoRouteAvailable

        async def fake_race_stream(routes, body, base_url):
            raise NoRouteAvailable()

        with patch("services.race_engine.race_stream", fake_race_stream):
            resp = self._post_stream()
        self.assertEqual(resp.status_code, 503)

    def test_stream_winner_returns_sse_200(self):
        async def fake_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"A"}}]}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"B"}}]}\n\n'
            yield "data: [DONE]\n\n"

        async def fake_race_stream(routes, body, base_url):
            # Use an unsaved key instance: the shared loop thread has its own
            # DB connection and cannot see this test's uncommitted transaction.
            from services.load_balancer import Route
            key = NvidiaApiKey(name="k1", api_key="nvapi-k1")
            w = StreamWinner(
                route=Route(kind="direct", key=key),
                client=None, resp_cm=None, aiter=None,
                first_line='data: {"choices":[{"delta":{"content":"A"}}]}',
                report=[],
            )
            w.lines = fake_lines.__get__(w)  # type: ignore[method-assign]
            return w

        with patch("services.race_engine.race_stream", fake_race_stream):
            resp = self._post_stream()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/event-stream")
        self.assertIn("no-transform", resp["Cache-Control"])
        body = _streaming_body(resp)
        self.assertIn('"content":"A"', body)
        self.assertIn("data: [DONE]", body)

    def test_stream_pump_uses_non_blocking_submit(self):
        """Regression: the pump must be fire-and-forget via ``submit_coroutine``.

        Blocking on it (``run_coroutine``) drains the whole upstream stream into
        the queue before the view returns, so every SSE chunk reaches the client
        at once instead of incrementally.
        """
        async def fake_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"A"}}]}\n\n'
            yield "data: [DONE]\n\n"

        async def fake_race_stream(routes, body, base_url):
            from services.load_balancer import Route
            key = NvidiaApiKey(name="k1", api_key="nvapi-k1")
            w = StreamWinner(
                route=Route(kind="direct", key=key),
                client=None, resp_cm=None, aiter=None,
                first_line='data: {"choices":[{"delta":{"content":"A"}}]}',
                report=[],
            )
            w.lines = fake_lines.__get__(w)  # type: ignore[method-assign]
            return w

        scheduled = []
        import services.loop as loop_mod

        def spy(coro):
            scheduled.append(coro)
            return loop_mod.submit_coroutine(coro)

        with patch("services.race_engine.race_stream", fake_race_stream), \
             patch("api.openai_views.submit_coroutine", spy, create=True):
            resp = self._post_stream()
            self.assertEqual(resp.status_code, 200)
            # The view scheduled the pump without awaiting it.
            self.assertEqual(len(scheduled), 1)
            self.assertEqual(resp["Content-Type"], "text/event-stream")

        body = _streaming_body(resp)
        self.assertIn('"content":"A"', body)
        self.assertIn("data: [DONE]", body)


class OpenAIStreamingASGITests(TransactionTestCase):
    def test_content_reaches_client_before_upstream_completes(self):
        """公开 OpenAI 接口在 ASGI 下必须逐段发送 SSE。"""
        import asyncio
        from concurrent.futures import Future
        from types import SimpleNamespace

        from asgiref.sync import async_to_sync
        from asgiref.testing import ApplicationCommunicator
        from django.test import AsyncRequestFactory

        from config.asgi import application

        _, raw = _make_user_key()
        AIModel.objects.create(model_name="m/test", enabled=True)
        key = NvidiaApiKey.objects.create(name="k1", api_key="nvapi-k1")
        release = Future()

        async def lines():
            yield 'data: {"choices":[{"delta":{"content":"首段"}}]}\n\n'
            await asyncio.wrap_future(release)
            yield "data: [DONE]\n\n"

        async def close():
            pass

        async def race(*args):
            return SimpleNamespace(
                route=SimpleNamespace(kind="direct", key=key, proxy=None),
                report=[], lines=lines, close=close,
            )

        request = AsyncRequestFactory().post(
            "/v1/chat/completions",
            data=json.dumps({"model": "m/test", "stream": True,
                             "messages": [{"role": "user", "content": "hi"}]}),
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw}"},
        )

        async def check():
            communicator = ApplicationCommunicator(application, request.scope)
            await communicator.send_input({"type": "http.request", "body": request.body})
            try:
                start = await communicator.receive_output(timeout=2)
                self.assertEqual(start["status"], 200)
                body = b""
                while "首段".encode() not in body:
                    event = await communicator.receive_output(timeout=2)
                    self.assertEqual(event["type"], "http.response.body")
                    body += event.get("body", b"")
                self.assertFalse(release.done())
                release.set_result(None)
                while True:
                    event = await communicator.receive_output(timeout=2)
                    body += event.get("body", b"")
                    if not event.get("more_body", False):
                        break
                self.assertIn(b"data: [DONE]", body)
                await communicator.wait(timeout=2)
            finally:
                if not release.done():
                    release.set_result(None)
                communicator.stop()

        with patch("services.race_engine.race_stream", side_effect=race):
            async_to_sync(check)()


class NonStreamingViewTests(TestCase):
    def setUp(self):
        self.rec, self.raw = _make_user_key()
        AIModel.objects.create(model_name="m/test", enabled=True)
        NvidiaApiKey.objects.create(name="k1", api_key="nvapi-k1")

    def test_success_returns_payload(self):
        from services.load_balancer import Route

        key = NvidiaApiKey(name="k1", api_key="nvapi-k1")
        result = RaceResult(
            ok=True, route=Route(kind="direct", key=key), payload={
                "choices": [{"message": {"role": "assistant", "content": "hello"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
            http_status=200,
        )

        with patch("api.openai_views.race_chat", return_value=result):
            from django.test import Client
            c = Client()
            resp = c.post(
                "/v1/chat/completions",
                data=json.dumps({"model": "m/test",
                                 "messages": [{"role": "user", "content": "hi"}]}),
                content_type="application/json", **_auth_header(self.raw),
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["choices"][0]["message"]["content"], "hello")
        self.assertTrue(resp.has_header("X-Request-Id"))

    def test_all_failed_502(self):
        from services.race_engine import AllRoutesFailed

        with patch("api.openai_views.race_chat",
                   side_effect=AllRoutesFailed(["r0:timeout"], report=[])):
            from django.test import Client
            c = Client()
            resp = c.post(
                "/v1/chat/completions",
                data=json.dumps({"model": "m/test",
                                 "messages": [{"role": "user", "content": "hi"}]}),
                content_type="application/json", **_auth_header(self.raw),
            )
        self.assertEqual(resp.status_code, 502)


class AdminChatViewTests(TestCase):
    def setUp(self):
        from django.conf import settings

        self.admin_token = settings.ADMIN_TOKEN
        AIModel.objects.create(model_name="m/test", enabled=True)
        NvidiaApiKey.objects.create(name="k1", api_key="nvapi-k1")

    def test_stream_failure_is_forwarded_as_sse_error(self):
        from django.test import Client
        from services.race_engine import AllRoutesFailed

        report = [{
            "name": "direct:k1", "kind": "direct", "key_name": "k1",
            "proxy_name": "", "status": "failed", "latency_ms": 12.3,
            "error": "invalid_key", "http_status": 401,
        }]
        with patch("services.race_engine.race_stream", side_effect=AllRoutesFailed(
            ["direct:k1:invalid_key (HTTP 401)"], report=report
        )):
            response = Client().post(
                "/api/admin/chat",
                data=json.dumps({
                    "model": "m/test", "stream": True,
                    "messages": [{"role": "user", "content": "hi"}],
                }),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Token {self.admin_token}",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        # Next.js 压缩中间件遵循 no-transform，否则 gzip 会攒满回复才发送。
        self.assertIn("no-transform", response["Cache-Control"])
        body = b"".join(response.streaming_content).decode()
        self.assertIn('"code": "upstream_error"', body)
        self.assertIn("HTTP 401", body)
        self.assertIn("data: [DONE]", body)

    def test_stream_sends_heartbeat_while_upstream_is_pending(self):
        from concurrent.futures import Future
        from django.test import Client

        future = Future()
        def keep_pending(coro):
            coro.close()
            return future

        with patch("services.loop.submit_coroutine", side_effect=keep_pending):
            response = Client().post(
                "/api/admin/chat",
                data=json.dumps({
                    "model": "m/test", "stream": True,
                    "messages": [{"role": "user", "content": "hi"}],
                }),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Token {self.admin_token}",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(next(iter(response.streaming_content)), b": keep-alive\n\n")

    def test_asgi_stream_yields_before_upstream_finishes(self):
        from concurrent.futures import Future
        from asgiref.sync import async_to_sync
        from django.test import AsyncRequestFactory
        from api.admin_views import AdminChatView

        future = Future()

        def keep_pending(coro):
            coro.close()
            return future

        request = AsyncRequestFactory().post(
            "/api/admin/chat",
            data=json.dumps({"model": "m/test", "stream": True,
                             "messages": [{"role": "user", "content": "hi"}]}),
            content_type="application/json",
            headers={"Authorization": f"Token {self.admin_token}"},
        )
        with patch("services.loop.submit_coroutine", side_effect=keep_pending):
            response = AdminChatView.as_view()(request)

        self.assertTrue(response.is_async)

        async def first_chunk():
            iterator = response.streaming_content
            chunk = await anext(iterator)
            await iterator.aclose()
            return chunk

        self.assertEqual(async_to_sync(first_chunk)(), b": keep-alive\n\n")
        self.assertFalse(future.done())


class AdminChatASGIStreamingTests(TransactionTestCase):
    def test_content_reaches_client_before_upstream_completes(self):
        """通过完整 ASGI 处理链，首段文字必须在上游结束前发出。"""
        import asyncio
        from concurrent.futures import Future
        from types import SimpleNamespace

        from asgiref.sync import async_to_sync
        from asgiref.testing import ApplicationCommunicator
        from django.conf import settings
        from django.test import AsyncRequestFactory

        from config.asgi import application

        AIModel.objects.create(model_name="m/test", enabled=True)
        key = NvidiaApiKey.objects.create(name="k1", api_key="nvapi-k1")
        release = Future()
        closed = Future()

        async def lines():
            yield 'data: {"choices":[{"delta":{"content":"首段"}}]}\n\n'
            await asyncio.wrap_future(release)
            yield 'data: {"choices":[],"usage":{"total_tokens":3}}\n\n'
            yield 'data: [DONE]\n\n'

        async def close():
            closed.set_result(True)

        async def race(*args):
            return SimpleNamespace(
                route=SimpleNamespace(kind="direct", key=key, proxy=None),
                report=[], lines=lines, close=close,
            )

        request = AsyncRequestFactory().post(
            "/api/admin/chat",
            data=json.dumps({"model": "m/test", "stream": True,
                             "messages": [{"role": "user", "content": "hi"}]}),
            content_type="application/json",
            headers={"Authorization": f"Token {settings.ADMIN_TOKEN}"},
        )

        async def check():
            communicator = ApplicationCommunicator(application, request.scope)
            await communicator.send_input({"type": "http.request", "body": request.body})
            try:
                start = await communicator.receive_output(timeout=2)
                self.assertEqual(start["status"], 200)
                body = b""
                while "首段".encode() not in body:
                    event = await communicator.receive_output(timeout=2)
                    self.assertEqual(event["type"], "http.response.body")
                    body += event.get("body", b"")
                self.assertFalse(release.done())
                self.assertFalse(closed.done())
                release.set_result(None)
                while True:
                    event = await communicator.receive_output(timeout=2)
                    body += event.get("body", b"")
                    if not event.get("more_body", False):
                        break
                self.assertIn(b'"summary"', body)
                self.assertIn(b'"total_tokens": 3', body)
                self.assertTrue(closed.done())
                await communicator.wait(timeout=2)
            finally:
                if not release.done():
                    release.set_result(None)
                communicator.stop()

        with patch("services.race_engine.race_stream", side_effect=race):
            async_to_sync(check)()


class LoginSecurityTests(TestCase):
    def test_login_requires_password_only_and_ignores_legacy_username(self):
        from django.conf import settings
        from django.test import Client
        from api.auth import _LOGIN_FAILS

        _LOGIN_FAILS.clear()
        c = Client()
        resp = c.post("/api/admin/login", {"password": settings.ADMIN_PASSWORD})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["token"], settings.ADMIN_TOKEN)
        resp = c.post("/api/admin/login", {
            "username": "legacy value is ignored", "password": settings.ADMIN_PASSWORD,
        })
        self.assertEqual(resp.status_code, 200)
        _LOGIN_FAILS.clear()

    def test_model_sync_reports_enabled_conflicts(self):
        from django.test import Client
        from django.conf import settings

        rec = AIModel.objects.create(model_name="a/removed", enabled=True)
        with patch("api.admin_views.nvidia_service.sync_models", return_value={
            "created": 0, "existing": 0, "total": 0, "retired": 1,
            "retired_models": [{"id": rec.id, "model_name": rec.model_name,
                                "was_enabled": True}],
            "conflicts": [{"id": rec.id, "model_name": rec.model_name,
                           "was_enabled": True}],
            "restored": 0, "restored_models": [],
        }):
            resp = Client().post(
                "/api/admin/models/sync", data="{}", content_type="application/json",
                HTTP_AUTHORIZATION=f"Token {settings.ADMIN_TOKEN}",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["conflicts"][0]["model_name"], "a/removed")

    def test_retired_model_cannot_be_enabled(self):
        from django.conf import settings
        from django.test import Client

        rec = AIModel.objects.create(model_name="a/removed", enabled=False, status="retired")
        resp = Client().patch(
            f"/api/admin/models/{rec.id}", data=json.dumps({"enabled": True}),
            content_type="application/json", HTTP_AUTHORIZATION=f"Token {settings.ADMIN_TOKEN}",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "model_retired")

    def test_login_lockout_after_failures(self):
        from django.test import Client
        from api.auth import _LOGIN_FAILS, _LOGIN_MAX_FAILS, _LOGIN_WINDOW
        import time

        _LOGIN_FAILS.clear()
        c = Client()
        for _ in range(_LOGIN_MAX_FAILS):
            resp = c.post("/api/admin/login", {"password": "wrong"})
            self.assertEqual(resp.status_code, 401)
        from django.conf import settings
        resp = c.post("/api/admin/login", {"password": settings.ADMIN_PASSWORD})
        self.assertEqual(resp.status_code, 429)
        _LOGIN_FAILS.clear()

    def test_admin_accepts_bearer_and_token(self):
        from django.conf import settings
        from django.test import Client
        c = Client()
        for scheme in ("Bearer", "Token"):
            resp = c.get("/api/admin/dashboard",
                         HTTP_AUTHORIZATION=f"{scheme} {settings.ADMIN_TOKEN}")
            self.assertEqual(resp.status_code, 200)
