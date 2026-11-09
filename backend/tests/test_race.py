import asyncio
from unittest.mock import patch

from django.test import TestCase

from apps.core.models import NvidiaApiKey, Proxy
from services.load_balancer import Route
from services import race_engine
from services.race_engine import (
    AllRoutesFailed, RaceResult, is_valid_response, is_valid_stream_chunk,
)


def make_route(name, key_suffix):
    key = NvidiaApiKey(name=f"key-{key_suffix}", api_key=f"nvapi-{key_suffix}")
    return Route(kind="direct", key=key)


def resp(obj):
    data = {
        "id": "chatcmpl-x",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    return RaceResult(ok=True, route=obj, payload=data, http_status=200)


class ValidationTests(TestCase):
    def test_valid_response(self):
        self.assertTrue(is_valid_response(200, {"choices": [{"message": {"content": "hi"}}]}))
        self.assertFalse(is_valid_response(200, {"choices": []}))
        self.assertFalse(is_valid_response(200, {"error": {"message": "x"}}))
        self.assertFalse(is_valid_response(500, {"choices": [{"message": {"content": "hi"}}]}))

    def test_stream_chunk(self):
        self.assertIsNone(is_valid_stream_chunk("data: garbage"))
        self.assertIsNotNone(is_valid_stream_chunk(
            'data: {"choices":[{"delta":{"content":"h"}}]}'))
        self.assertEqual(is_valid_stream_chunk("data: [DONE]"), {"done": True})
        self.assertIsNone(is_valid_stream_chunk('data: {"error":{"message":"x"}}'))


class RaceTests(TestCase):
    def _race(self, behaviors):
        """behaviors: list of (delay, ok). Returns (winner_index, cancelled_flags)."""
        cancelled = [False] * len(behaviors)
        delay_slow = 60.0

        async def fake_do_request(route, body, base_url, started=None):
            idx = int(route.key.name.split("-")[-1])
            delay, ok = behaviors[idx]
            try:
                await asyncio.sleep(delay)
                if ok:
                    r = resp(route)
                    return r
                return RaceResult(ok=False, route=route, error_type="boom", http_status=500)
            except asyncio.CancelledError:
                cancelled[idx] = True
                raise

        with patch.object(race_engine, "_do_request", fake_do_request), \
             patch.object(race_engine, "_mark_success"), \
             patch.object(race_engine, "_mark_failure"):
            routes = [make_route(f"r{i}", i) for i in range(len(behaviors))]
            try:
                result = asyncio.run(race_engine._race(routes, {}, "http://upstream"))
                winner_idx = int(result.route.key.name.split("-")[-1])
                return winner_idx, cancelled, result
            except AllRoutesFailed:
                return -1, cancelled, None

    def test_fast_wins_slow_cancelled(self):
        # A slow (1.5s), B fast (0.05s), C fails
        winner, cancelled, result = self._race([(1.5, True), (0.05, True), (0.01, False)])
        self.assertEqual(winner, 1)
        self.assertTrue(cancelled[0])

    def test_failures_skipped_until_success(self):
        winner, cancelled, result = self._race([(0.01, False), (0.02, False), (0.05, True)])
        self.assertEqual(winner, 2)

    def test_all_failed_raises(self):
        winner, cancelled, result = self._race([(0.01, False), (0.01, False)])
        self.assertEqual(winner, -1)

    def test_missing_local_file_is_classified_as_configuration_error(self):
        route = make_route("r0", 0)
        error, status = race_engine._classify_error(
            FileNotFoundError(2, "No such file or directory")
        )
        self.assertEqual((error, status), ("local_file_error", 0))

        with patch("services.race_engine.report_failure") as report_failure, \
             patch("services.race_engine.report_proxy_result") as report_proxy_result:
            race_engine._mark_failure(route, error, status)

        report_failure.assert_not_called()
        report_proxy_result.assert_not_called()

    def test_non_stream_request_handles_file_error_while_creating_client(self):
        route = make_route("r0", 0)

        with patch("services.race_engine._client_timeout"), \
             patch("services.loop.acquire_client",
                   side_effect=FileNotFoundError(2, "No such file or directory")), \
             patch("services.race_engine.report_failure") as report_failure:
            result = asyncio.run(race_engine._do_request(
                route, {}, "https://upstream"
            ))

        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "local_file_error")
        self.assertIn("No such file or directory", result.error_message)
        report_failure.assert_not_called()

    def test_stream_request_handles_file_error_while_creating_client(self):
        route = make_route("r0", 0)

        with patch("services.race_engine._client_timeout"), \
             patch("services.loop.acquire_client",
                   side_effect=FileNotFoundError(2, "No such file or directory")), \
             patch("services.race_engine.report_failure") as report_failure:
            result, failure = asyncio.run(race_engine._stream_first_valid(
                route, {}, "https://upstream"
            ))

        self.assertIsNone(result)
        self.assertEqual(failure["error"].split(" ", 1)[0], "local_file_error")
        self.assertIn("SSL_CERT_FILE", failure["error"])
        report_failure.assert_not_called()

    def test_all_failed_error_includes_upstream_http_status(self):
        route = make_route("r0", 0)

        async def failed_request(route, body, base_url, started=None):
            return RaceResult(
                ok=False, route=route, http_status=401, error_type="invalid_key"
            )

        with patch.object(race_engine, "_do_request", failed_request), \
             self.assertRaises(AllRoutesFailed) as raised:
            asyncio.run(race_engine._race([route], {}, "http://upstream"))

        self.assertIn("HTTP 401", str(raised.exception))


class StreamRaceTests(TestCase):
    def test_first_valid_stream_wins_rest_cancelled(self):
        from services import race_engine

        cancelled = [False, False, False]

        async def fake_stream(route, body, base_url):
            idx = int(route.key.name.split("-")[-1])
            delay = [0.5, 0.05, 0.3][idx]
            ok = [True, True, False][idx]
            try:
                await asyncio.sleep(delay)
                if not ok:
                    return None, {"name": route.name, "error": "boom"}
                # cm, req_cm, resp, aiter, first_line
                return (None, None, None, None, 'data: {"choices":[{"delta":{"content":"h"}}]}'), None
            except asyncio.CancelledError:
                cancelled[idx] = True
                raise

        with patch.object(race_engine, "_stream_first_valid", fake_stream):
            routes = [make_route(f"r{i}", i) for i in range(3)]
            route, *_ = asyncio.run(
                race_engine.race_stream_winner(routes, {}, "http://upstream"))
            self.assertEqual(route.key.name, "key-1")
        self.assertTrue(cancelled[0])
        self.assertTrue(cancelled[2])

    def test_stream_all_invalid_raises(self):
        from services import race_engine

        async def fake_stream(route, body, base_url):
            return None, {"name": route.name, "error": "boom"}

        with patch.object(race_engine, "_stream_first_valid", fake_stream):
            routes = [make_route("r0", 0)]
            with self.assertRaises(AllRoutesFailed):
                asyncio.run(race_engine.race_stream_winner(routes, {}, "http://x"))

    def test_stream_all_failed_error_includes_upstream_http_status(self):
        async def failed_stream(route, body, base_url):
            return None, {
                "name": route.name,
                "error": "invalid_key",
                "http_status": 401,
            }

        with patch.object(race_engine, "_stream_first_valid", failed_stream), \
             self.assertRaises(AllRoutesFailed) as raised:
            asyncio.run(race_engine.race_stream_winner(
                [make_route("r0", 0)], {}, "http://upstream"
            ))

        self.assertIn("HTTP 401", str(raised.exception))
