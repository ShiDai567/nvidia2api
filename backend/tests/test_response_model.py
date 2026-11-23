"""响应模型名遵循本服务收到的下游请求，覆盖 JSON 和两种 SSE 迭代器。"""

import json
import time
from types import SimpleNamespace
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.test import RequestFactory, TestCase, TransactionTestCase

from api.openai_views import _stream_response, _with_stream_model, chat_completions
from apps.core.models import AIModel, ContentReviewRule, NvidiaApiKey, RequestLog
from services import api_key_service
from services.load_balancer import Route
from services.race_engine import RaceResult


REQUEST_MODEL = "google/gemini-4-carbon"
UPSTREAM_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"


class ResponseModelTests(TestCase):
    def test_newapi_original_model_header_only_changes_response(self):
        user, raw = api_key_service.create_key("New API")
        user.allowed_models = [UPSTREAM_MODEL]
        user.save(update_fields=["allowed_models"])
        AIModel.objects.create(model_name=UPSTREAM_MODEL, enabled=True)
        key = NvidiaApiKey.objects.create(name="上游", api_key="local-newapi")
        payload = {"model": UPSTREAM_MODEL, "choices": [{"message": {"content": "你好"}}]}
        result = RaceResult(ok=True, route=Route(kind="direct", key=key),
                            payload=payload, http_status=200)
        for header, expected in ((REQUEST_MODEL, REQUEST_MODEL), ("", UPSTREAM_MODEL)):
            with self.subTest(header=header), patch("api.openai_views.race_chat", return_value=result) as race:
                response = self.client.post(
                    "/v1/chat/completions",
                    {"model": UPSTREAM_MODEL, "messages": [{"role": "user", "content": "hi"}]},
                    content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {raw}",
                    HTTP_X_ORIGINAL_MODEL=header,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["model"], expected)
                self.assertEqual(race.call_args.args[1]["model"], UPSTREAM_MODEL)
        self.assertTrue(all(log.model == UPSTREAM_MODEL for log in RequestLog.objects.all()))
        self.assertEqual(payload["model"], UPSTREAM_MODEL)

    def test_json_uses_request_model_without_mutating_upstream_payload(self):
        _, raw = api_key_service.create_key("调用方")
        AIModel.objects.create(model_name=REQUEST_MODEL, enabled=True)
        key = NvidiaApiKey.objects.create(name="上游", api_key="local-response-model")
        payload = {
            "model": UPSTREAM_MODEL,
            "choices": [{"message": {"role": "assistant", "content": "你好"}}],
            "usage": {"total_tokens": 3},
        }
        result = RaceResult(ok=True, route=Route(kind="direct", key=key),
                            payload=payload, http_status=200)
        with patch("api.openai_views.race_chat", return_value=result) as race:
            response = self.client.post(
                "/v1/chat/completions",
                {"model": REQUEST_MODEL, "messages": [{"role": "user", "content": "hi"}]},
                content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {raw}",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {**payload, "model": REQUEST_MODEL})
        self.assertEqual(payload["model"], UPSTREAM_MODEL)
        self.assertEqual(race.call_args.args[1]["model"], REQUEST_MODEL)
        self.assertEqual(RequestLog.objects.get().model, REQUEST_MODEL)

    def test_non_completion_events_are_unchanged(self):
        chunks = [": heartbeat\n\n", "data: [DONE]\n\n", "data: broken\n\n",
                  'data: {"error":{"message":"failed"}}\n\n', "data: []\n\n"]
        for chunk in chunks:
            with self.subTest(chunk=chunk):
                self.assertEqual(_with_stream_model(chunk, REQUEST_MODEL), chunk)


class StreamingResponseModelTests(TransactionTestCase):
    def test_newapi_header_reaches_wsgi_and_asgi_streams(self):
        key = NvidiaApiKey.objects.create(name="上游", api_key="local-newapi-stream")
        _, raw = api_key_service.create_key("New API")
        AIModel.objects.create(model_name=UPSTREAM_MODEL, enabled=True)
        seen = []

        async def lines():
            yield 'data: ' + json.dumps({"model": UPSTREAM_MODEL, "choices": [
                {"delta": {"content": "你好"}}
            ]}) + '\n\n'
            yield 'data: ' + json.dumps({"model": UPSTREAM_MODEL, "choices": [],
                                        "usage": {"total_tokens": 3}}) + '\n\n'
            yield 'data: [DONE]\n\n'

        async def close():
            pass

        async def race(routes, body, base_url):
            seen.append(body)
            return SimpleNamespace(route=Route(kind="direct", key=key), report=[],
                                   lines=lines, close=close)

        async def collect(response):
            return b"".join([chunk async for chunk in response.streaming_content]).decode()

        for is_asgi in (False, True):
            with self.subTest(is_asgi=is_asgi):
                request = RequestFactory().post(
                    "/v1/chat/completions",
                    {"model": UPSTREAM_MODEL, "stream": True,
                     "messages": [{"role": "user", "content": "hi"}]},
                    content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {raw}",
                    HTTP_X_ORIGINAL_MODEL=REQUEST_MODEL,
                )
                if is_asgi:
                    request.scope = {}
                with patch("services.race_engine.race_stream", side_effect=race):
                    response = chat_completions(request)
                    self.assertEqual(response.status_code, 200)
                    body = (async_to_sync(collect)(response) if is_asgi else
                            b"".join(response.streaming_content).decode())
                chunks = [json.loads(line[5:]) for line in body.splitlines()
                          if line.startswith("data:") and line != "data: [DONE]"]
                self.assertEqual([chunk["model"] for chunk in chunks], [REQUEST_MODEL] * 2)
                self.assertEqual(seen[-1]["model"], UPSTREAM_MODEL)
                self.assertNotIn("X-Original-Model", seen[-1])
                self.assertTrue(body.endswith("data: [DONE]\n\n"))

    def test_wsgi_and_asgi_rewrite_content_usage_tools_and_review_flush(self):
        key = NvidiaApiKey.objects.create(name="上游", api_key="local-stream-model")
        user, _ = api_key_service.create_key("调用方")
        # “尾”会被审查器暂存，在结束标记之前补发新分片。
        ContentReviewRule.objects.create(forbidden_text="尾巴", replacement_text="替换")
        events = [
            {"model": UPSTREAM_MODEL, "choices": [{"delta": {"content": "你好尾"}}]},
            {"model": UPSTREAM_MODEL, "choices": [{"delta": {
                "tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]
            }}]},
            {"model": UPSTREAM_MODEL, "choices": [], "usage": {"total_tokens": 3}},
        ]

        async def lines():
            for event in events:
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            yield "data: [DONE]\n\n"

        async def close():
            pass

        async def race(*args):
            return SimpleNamespace(route=Route(kind="direct", key=key),
                                   report=[], lines=lines, close=close)

        async def collect(response):
            return b"".join([chunk async for chunk in response.streaming_content]).decode()

        for is_asgi in (False, True):
            with self.subTest(is_asgi=is_asgi):
                log = RequestLog.objects.create(request_id=f"req_model_{is_asgi}", model=REQUEST_MODEL)
                with patch("services.race_engine.race_stream", side_effect=race):
                    response = _stream_response(
                        [], {"model": REQUEST_MODEL}, log, time.monotonic(),
                        log.request_id, user, is_asgi=is_asgi,
                    )
                    body = (async_to_sync(collect)(response) if is_asgi else
                            b"".join(response.streaming_content).decode())
                self.assertEqual(response.status_code, 200)
                chunks = [json.loads(line[5:]) for line in body.splitlines()
                          if line.startswith("data:") and line != "data: [DONE]"]
                self.assertEqual(len(chunks), 4)
                self.assertTrue(all(chunk["model"] == REQUEST_MODEL for chunk in chunks))
                self.assertNotIn(UPSTREAM_MODEL, body)
                self.assertEqual(chunks[1]["choices"], events[1]["choices"])
                self.assertEqual(chunks[-1]["usage"], {"total_tokens": 3})
                self.assertEqual(chunks[2]["choices"][0]["delta"]["content"], "尾")
                self.assertTrue(body.endswith("data: [DONE]\n\n"))
                log.refresh_from_db()
                self.assertEqual(log.total_tokens, 3)
