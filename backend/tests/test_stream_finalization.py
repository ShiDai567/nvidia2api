"""下游在结束标记或传输中途关闭时，流式请求统计仍应落库。"""

import asyncio
import time
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.test import AsyncRequestFactory, TransactionTestCase

from api.openai_views import _stream_response
from apps.core.models import AIModel, NvidiaApiKey, RequestLog
from services import api_key_service
from services.load_balancer import Route


class StreamFinalizationTests(TransactionTestCase):
    def test_real_asgi_disconnect_finalizes_log(self):
        import json

        from asgiref.testing import ApplicationCommunicator
        from config.asgi import application

        key = NvidiaApiKey.objects.create(name="上游", api_key="local-asgi-disconnect")
        _, raw = api_key_service.create_key("调用方")
        AIModel.objects.create(model_name="m/test", enabled=True)
        closed = Future()

        async def lines():
            yield 'data: {"choices":[],"usage":{"total_tokens":5}}\n\n'
            yield 'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
            await asyncio.Future()

        async def close():
            if not closed.done():
                closed.set_result(None)

        async def race(*args):
            return SimpleNamespace(route=Route(kind="direct", key=key), report=[],
                                   lines=lines, close=close)

        request = AsyncRequestFactory().post(
            "/v1/chat/completions",
            data=json.dumps({"model": "m/test", "stream": True,
                             "messages": [{"role": "user", "content": "hi"}]}),
            content_type="application/json", headers={"Authorization": f"Bearer {raw}"},
        )

        async def check():
            communicator = ApplicationCommunicator(application, request.scope)
            try:
                await communicator.send_input({"type": "http.request", "body": request.body})
                start = await communicator.receive_output(timeout=2)
                self.assertEqual(start["status"], 200)
                body = b""
                while "你好".encode() not in body:
                    event = await communicator.receive_output(timeout=2)
                    body += event.get("body", b"")
                await communicator.send_input({"type": "http.disconnect"})
                await communicator.wait(timeout=2)
                await asyncio.wait_for(asyncio.wrap_future(closed), timeout=2)
            finally:
                communicator.stop()

        with patch("services.race_engine.race_stream", side_effect=race):
            async_to_sync(check)()
        log = RequestLog.objects.get()
        self.assertGreater(log.duration_ms, 0)
        self.assertEqual(log.total_tokens, 5)
        self.assertEqual(log.error_type, "client_disconnected")

    def test_disconnect_and_error_preserve_received_usage(self):
        key = NvidiaApiKey.objects.create(name="上游", api_key="local-disconnect")
        user, _ = api_key_service.create_key("调用方")
        for is_asgi in (False, True):
            for outcome in ("client_disconnected", "stream_error", "eof_without_usage"):
                with self.subTest(is_asgi=is_asgi, outcome=outcome):
                    closed = Future()

                    async def lines():
                        if outcome != "eof_without_usage":
                            yield 'data: {"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}\n\n'
                        yield 'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
                        if outcome == "client_disconnected":
                            await asyncio.Future()
                        if outcome == "stream_error":
                            raise RuntimeError("上游中途失败")

                    async def close():
                        if not closed.done():
                            closed.set_result(None)

                    async def race(*args):
                        return SimpleNamespace(route=Route(kind="direct", key=key), report=[],
                                               lines=lines, close=close)

                    log = RequestLog.objects.create(
                        request_id=f"req_{outcome}_{is_asgi}", model="m/test"
                    )
                    with patch("services.race_engine.race_stream", side_effect=race):
                        response = _stream_response([], {"model": "m/test"}, log,
                                                    time.monotonic() - 1, log.request_id,
                                                    user, is_asgi=is_asgi)

                    async def consume():
                        iterator = response._iterator
                        try:
                            async for chunk in iterator:
                                if outcome == "client_disconnected" and "你好" in chunk:
                                    break
                        finally:
                            await iterator.aclose()
                            await asyncio.wait_for(asyncio.wrap_future(closed), timeout=2)

                    if is_asgi:
                        async_to_sync(consume)()
                    else:
                        iterator = response._iterator
                        try:
                            for chunk in iterator:
                                if outcome == "client_disconnected" and "你好" in chunk:
                                    break
                        finally:
                            iterator.close()
                    log.refresh_from_db()
                    self.assertGreaterEqual(log.duration_ms, 1000)
                    self.assertEqual(log.total_tokens, 0 if outcome == "eof_without_usage" else 5)
                    if outcome == "eof_without_usage":
                        self.assertEqual(log.status, "success")
                    else:
                        self.assertEqual(log.status, "error")
                        self.assertEqual(log.error_type, outcome)
                        self.assertEqual(log.http_status, 499 if outcome == "client_disconnected" else 502)

    def test_done_is_persisted_before_client_stops_reading(self):
        key = NvidiaApiKey.objects.create(name="上游", api_key="local-finalization")
        user, _ = api_key_service.create_key("调用方")

        for is_asgi in (False, True):
            with self.subTest(is_asgi=is_asgi):
                closed = Future()

                async def lines():
                    yield 'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
                    yield 'data: {"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}\n\n'
                    yield 'data: [DONE]\n\n'
                    # 模拟上游已发结束标记，但尚未关闭 HTTP 连接。
                    await asyncio.Future()

                async def close():
                    if not closed.done():
                        closed.set_result(None)

                async def race(*args):
                    return SimpleNamespace(route=Route(kind="direct", key=key), report=[],
                                           lines=lines, close=close)

                log = RequestLog.objects.create(request_id=f"req_done_{is_asgi}", model="m/test")
                with patch("services.race_engine.race_stream", side_effect=race):
                    response = _stream_response([], {"model": "m/test"}, log,
                                                time.monotonic() - 1, log.request_id,
                                                user, is_asgi=is_asgi)

                async def consume_until_done():
                    iterator = response._iterator
                    try:
                        async for chunk in iterator:
                            if "[DONE]" in chunk:
                                return
                    finally:
                        await iterator.aclose()
                        await asyncio.wait_for(asyncio.wrap_future(closed), timeout=2)

                if is_asgi:
                    async_to_sync(consume_until_done)()
                else:
                    iterator = response._iterator
                    try:
                        for chunk in iterator:
                            if "[DONE]" in chunk:
                                break
                    finally:
                        iterator.close()
                log.refresh_from_db()
                self.assertGreaterEqual(log.duration_ms, 1000)
                self.assertEqual((log.prompt_tokens, log.completion_tokens, log.total_tokens),
                                 (2, 3, 5))
                self.assertEqual(log.status, "success")
