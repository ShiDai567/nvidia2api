"""请求调度公开接口：FIFO、容量变化和取消后的名额回收。"""

import asyncio
import time
from unittest import IsolatedAsyncioTestCase

from services.request_queue import RequestQueue, QueueFull, QueueTimeout


class RequestQueueTests(IsolatedAsyncioTestCase):
    async def test_slow_capacity_lookup_does_not_allow_later_request_to_overtake(self):
        queue = RequestQueue(poll_interval=0.001)
        release = asyncio.Event()

        async def slow_snapshot():
            await release.wait()
            return 1, 10, 1

        async def snapshot():
            return 1, 10, 1

        first = asyncio.create_task(queue.acquire(time.monotonic(), slow_snapshot))
        await asyncio.sleep(0)
        second = asyncio.create_task(queue.acquire(time.monotonic(), snapshot))
        await asyncio.sleep(0.005)
        self.assertFalse(second.done())
        release.set()
        lease = await asyncio.wait_for(first, 1)
        lease.release()
        lease = await asyncio.wait_for(second, 1)
        lease.release()

    async def test_fifo_and_dynamic_capacity(self):
        queue = RequestQueue(poll_interval=0.001)
        capacity = 1

        async def snapshot():
            return capacity, 10, 1

        arrived = time.monotonic()
        first = await queue.acquire(arrived, snapshot)
        later = asyncio.create_task(queue.acquire(arrived + 0.0003, snapshot))
        earlier = asyncio.create_task(queue.acquire(arrived + 0.0002, snapshot))
        await asyncio.sleep(0.01)
        self.assertEqual(queue.stats(), {"active_requests": 1, "queued_requests": 2,
                                         "concurrent_limit": 1})
        first.release()
        second = await asyncio.wait_for(earlier, 1)
        self.assertFalse(later.done())
        capacity = 2
        third = await asyncio.wait_for(later, 1)
        capacity = 1
        waiting = asyncio.create_task(queue.acquire(time.monotonic(), snapshot))
        await asyncio.sleep(0.01)
        second.release()
        await asyncio.sleep(0.01)
        self.assertFalse(waiting.done())
        third.release()
        fourth = await asyncio.wait_for(waiting, 1)
        fourth.release()
        fourth.release()
        self.assertEqual(queue.stats()["active_requests"], 0)

    async def test_timeout_full_and_cancellation_remove_waiters(self):
        queue = RequestQueue(poll_interval=0.001)

        async def snapshot():
            return 1, 1, 0.02

        first = await queue.acquire(time.monotonic(), snapshot)
        waiting = asyncio.create_task(queue.acquire(time.monotonic(), snapshot))
        await asyncio.sleep(0.005)
        with self.assertRaises(QueueFull):
            await queue.acquire(time.monotonic(), snapshot)
        with self.assertRaises(QueueTimeout):
            await waiting
        waiting = asyncio.create_task(queue.acquire(time.monotonic(), snapshot))
        await asyncio.sleep(0.005)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        self.assertEqual(queue.stats()["queued_requests"], 0)
        first.release()
        lease = await queue.acquire(time.monotonic(), snapshot)
        lease.release()
