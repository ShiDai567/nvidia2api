import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import httpx

from services import race_engine
from tests.test_race import make_route


class UpstreamTimeoutTests(IsolatedAsyncioTestCase):
    async def test_stalled_reply_frees_only_pool_slot(self):
        for mode in ("before_first_chunk", "after_first_chunk", "partial_json", "silent"):
            with self.subTest(mode=mode):
                await self.check_pool_slot(mode)

    async def check_pool_slot(self, mode):
        started = asyncio.Event()
        disconnected = asyncio.Event()

        async def upstream(reader, writer):
            headers = b""
            try:
                headers = await reader.readuntil(b"\r\n\r\n")
                if headers.startswith(b"GET /probe "):
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
                    await writer.drain()
                    return
                length = next(line.split(b":")[1] for line in headers.lower().splitlines()
                              if line.startswith(b"content-length:"))
                await reader.readexactly(int(length))
                started.set()
                if mode != "silent":
                    writer.write(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n")
                    if mode == "after_first_chunk":
                        writer.write(b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n')
                while not reader.at_eof():
                    if mode != "silent":
                        writer.write(b" " if mode == "partial_json" else b": keep-alive\n\n")
                        await writer.drain()
                    await asyncio.sleep(0.01)
            except ConnectionError:
                pass
            finally:
                if not headers.startswith(b"GET /probe "):
                    disconnected.set()
                writer.close()

        route = make_route("local", 0)
        server = await asyncio.start_server(upstream, "127.0.0.1", 0)
        url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        async with server, httpx.AsyncClient(limits=httpx.Limits(max_connections=1),
                                             timeout=2, trust_env=False) as client:
            async def chat():
                if mode in ("partial_json", "silent"):
                    return (await race_engine._do_request(route, {}, url)).error_type
                try:
                    winner = await race_engine.race_stream([route], {"stream": True}, url)
                except race_engine.AllRoutesFailed as exc:
                    return exc.report[0]["error"]
                try:
                    async for _ in winner.lines():
                        pass
                except (TimeoutError, httpx.TimeoutException):
                    return "timeout"
                finally:
                    await winner.close()

            with patch("services.loop.acquire_client", return_value=client), \
                 patch.object(race_engine, "_client_timeout", return_value=httpx.Timeout(0.12)), \
                 patch.object(race_engine, "_mark_success"), patch.object(race_engine, "_mark_failure"):
                task = asyncio.create_task(chat())
                try:
                    await asyncio.wait_for(started.wait(), 1)
                    # 第二个请求必须等第一个连接真正释放，才能到达本地上游。
                    probe = await client.get(url + "/probe", timeout=0.7)
                    self.assertEqual(probe.text, "ok")
                    self.assertEqual(await asyncio.wait_for(task, 1), "timeout")
                    await asyncio.wait_for(disconnected.wait(), 1)
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
