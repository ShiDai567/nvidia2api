"""动态容量与真实 ASGI 聊天排队生命周期。"""

import asyncio
import json
from concurrent.futures import Future
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from asgiref.sync import async_to_sync, sync_to_async
from asgiref.testing import ApplicationCommunicator
from django.test import AsyncRequestFactory, TransactionTestCase
from django.utils import timezone

from apps.core.models import AIModel, NvidiaApiKey, UserApiKey
from config.asgi import application
from services import api_key_service, sysconfig
from services.load_balancer import Route
from services.request_queue import RequestQueue, capacity_snapshot
from services.race_engine import AllRoutesFailed


class QueueIntegrationTests(TransactionTestCase):
    def test_queue_timeout_returns_openai_error_without_consuming_quota(self):
        from django.test import Client

        key = NvidiaApiKey.objects.create(name="上游", api_key="local-timeout")
        user, raw = api_key_service.create_key("调用方")
        AIModel.objects.create(model_name="m/test", enabled=True)
        queue = RequestQueue(poll_interval=0.001)
        with patch("api.openai_views.request_queue", queue), \
             patch("api.openai_views.cached_capacity_snapshot", return_value=(0, 10, 0.02)):
            response = Client().post(
                "/v1/chat/completions",
                {"model": "m/test", "messages": [{"role": "user", "content": "hi"}]},
                content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {raw}",
            )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"]["code"], "queue_timeout")
        self.assertEqual(response["Retry-After"], "1")
        self.assertEqual(queue.stats()["queued_requests"], 0)
        user.refresh_from_db()
        key.refresh_from_db()
        self.assertEqual(user.total_requests, 0)
        self.assertEqual(key.minute_request_count, 0)

    def test_queue_limits_reject_invalid_values_without_partial_save(self):
        for key, value in (("max_queued_requests", -1), ("request_queue_timeout", "nan"),
                           ("request_queue_timeout", "inf"), ("max_concurrent_requests", 0)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                sysconfig.set_params({"direct_routes_per_request": 3, key: value})
        self.assertEqual(sysconfig.get("direct_routes_per_request"), 1)

    def test_failed_race_and_unstarted_response_release_slots(self):
        from django.test import Client

        key = NvidiaApiKey.objects.create(name="上游", api_key="local-unstarted")
        _, raw = api_key_service.create_key("调用方")
        AIModel.objects.create(model_name="m/test", enabled=True)
        queue = RequestQueue()
        body = {"model": "m/test", "stream": True,
                "messages": [{"role": "user", "content": "hi"}]}
        with patch("api.openai_views.request_queue", queue), \
             patch("services.race_engine.race_stream", side_effect=AllRoutesFailed([], report=[])):
            response = Client().post("/v1/chat/completions", body, content_type="application/json",
                                     HTTP_AUTHORIZATION=f"Bearer {raw}")
            self.assertEqual(response.status_code, 502)
            self.assertEqual(queue.stats()["active_requests"], 0)

        closed = Future()

        async def close():
            if not closed.done():
                closed.set_result(None)

        async def race(*args):
            return SimpleNamespace(route=Route(kind="direct", key=key), report=[], close=close)

        with patch("api.openai_views.request_queue", queue), \
             patch("services.race_engine.race_stream", side_effect=race):
            response = Client().post("/v1/chat/completions", body, content_type="application/json",
                                     HTTP_AUTHORIZATION=f"Bearer {raw}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(queue.stats()["active_requests"], 1)
            response.close()
            self.assertTrue(closed.done())
            self.assertEqual(queue.stats()["active_requests"], 0)

    def test_capacity_tracks_keys_routes_rpm_and_runtime_limit(self):
        for i in range(12):
            NvidiaApiKey.objects.create(name=f"k{i}", api_key=f"local-{i}")
        sysconfig.set_params({"direct_routes_per_request": 3})
        self.assertEqual(capacity_snapshot()[0], 4)
        sysconfig.set_params({"max_concurrent_requests": 2})
        self.assertEqual(capacity_snapshot()[0], 2)
        sysconfig.set_params({"max_concurrent_requests": 100, "direct_routes_per_request": 4})
        self.assertEqual(capacity_snapshot()[0], 3)
        NvidiaApiKey.objects.filter(name__in=["k0", "k1", "k2", "k3"]).update(
            cooldown_until=timezone.now() + timedelta(seconds=30)
        )
        self.assertEqual(capacity_snapshot()[0], 2)
        NvidiaApiKey.objects.update(minute_window_start=timezone.now(), minute_request_count=40)
        self.assertEqual(capacity_snapshot()[0], 0)
        NvidiaApiKey.objects.update(minute_window_start=timezone.now() - timedelta(seconds=61))
        self.assertEqual(capacity_snapshot()[0], 2)

    def test_stream_keeps_slot_and_queued_disconnect_does_not_consume_quota(self):
        key = NvidiaApiKey.objects.create(name="上游", api_key="local-queue")
        user, raw = api_key_service.create_key("调用方")
        AIModel.objects.create(model_name="m/test", enabled=True)
        queue = RequestQueue(poll_interval=0.005)
        release = Future()
        calls = []

        async def race(routes, body, base_url):
            label = body["messages"][0]["content"]
            calls.append(label)

            async def lines():
                yield 'data: {"choices":[{"delta":{"content":"首段"}}]}\n\n'
                if label == "first":
                    await asyncio.wrap_future(release)
                yield 'data: [DONE]\n\n'

            async def close():
                pass

            return SimpleNamespace(route=Route(kind="direct", key=key), report=[],
                                   lines=lines, close=close)

        def communicator(label):
            request = AsyncRequestFactory().post(
                "/v1/chat/completions",
                data=json.dumps({"model": "m/test", "stream": True,
                                 "messages": [{"role": "user", "content": label}]}),
                content_type="application/json", headers={"Authorization": f"Bearer {raw}"},
            )
            return ApplicationCommunicator(application, request.scope), request.body

        async def wait_queued(count):
            async with asyncio.timeout(2):
                while queue.stats()["queued_requests"] != count:
                    await asyncio.sleep(0.005)

        async def finish(comm):
            while True:
                event = await comm.receive_output(timeout=2)
                if event["type"] == "http.response.body" and not event.get("more_body", False):
                    break
            await comm.wait(timeout=2)

        async def check():
            clients = [communicator(label) for label in ("first", "cancelled", "third")]
            try:
                first, body = clients[0]
                await first.send_input({"type": "http.request", "body": body})
                self.assertEqual((await first.receive_output(timeout=2))["status"], 200)
                await first.receive_output(timeout=2)
                self.assertEqual(queue.stats()["active_requests"], 1)
                for index in (1, 2):
                    comm, body = clients[index]
                    await comm.send_input({"type": "http.request", "body": body})
                    await wait_queued(index)
                self.assertEqual(calls, ["first"])
                count = await sync_to_async(lambda: UserApiKey.objects.get(pk=user.pk).total_requests)()
                self.assertEqual(count, 1)
                await clients[1][0].send_input({"type": "http.disconnect"})
                await clients[1][0].wait(timeout=2)
                await wait_queued(1)
                release.set_result(None)
                await finish(first)
                self.assertEqual((await clients[2][0].receive_output(timeout=2))["status"], 200)
                await finish(clients[2][0])
                self.assertEqual(calls, ["first", "third"])
                self.assertEqual(queue.stats()["active_requests"], 0)
            finally:
                if not release.done():
                    release.set_result(None)
                for comm, _ in clients:
                    comm.stop()

        with patch("api.openai_views.request_queue", queue), \
             patch("services.race_engine.race_stream", side_effect=race):
            async_to_sync(check)()
        user.refresh_from_db()
        self.assertEqual(user.total_requests, 2)
