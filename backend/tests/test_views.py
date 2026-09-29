"""End-to-end view tests: streaming must return real HTTP status codes,
validation errors must not consume rate-limit quota, and user keys honour
allowed_models restrictions."""
from __future__ import annotations

import json
from unittest.mock import patch

from django.test import TestCase

from apps.core.models import AIModel, NvidiaApiKey, UserApiKey
from services import api_key_service
from services.race_engine import RaceResult, StreamWinner


def _make_user_key(name="u1", rate_limit=0):
    rec, raw = api_key_service.create_key(name, rate_limit=rate_limit)
    return rec, raw


def _auth_header(raw):
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


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
        body = b"".join(resp.streaming_content).decode()
        self.assertIn('"content":"A"', body)
        self.assertIn("data: [DONE]", body)


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


class LoginSecurityTests(TestCase):
    def test_login_lockout_after_failures(self):
        from django.test import Client
        from api.auth import _LOGIN_FAILS, _LOGIN_MAX_FAILS, _LOGIN_WINDOW
        import time

        _LOGIN_FAILS.clear()
        c = Client()
        for _ in range(_LOGIN_MAX_FAILS):
            resp = c.post("/api/admin/login", {"username": "admin", "password": "wrong"})
            self.assertEqual(resp.status_code, 401)
        resp = c.post("/api/admin/login", {"username": "admin", "password": "admin123"})
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
