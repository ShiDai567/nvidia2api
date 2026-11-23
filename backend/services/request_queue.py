"""单进程聊天准入：按到达时间排队，动态限制正在执行的完整对话数。"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import threading
import time


class QueueFull(Exception):
    pass


class QueueTimeout(Exception):
    pass


class Lease:
    def __init__(self, queue):
        self.queue = queue
        self.released = False
        self.stream_owned = False

    def release(self):
        with self.queue.lock:
            if not self.released:
                self.released = True
                self.queue.active -= 1


class RequestQueue:
    def __init__(self, poll_interval=0.2):
        self.lock = threading.Lock()
        self.waiters = []
        self.sequence = itertools.count()
        self.active = 0
        self.limit = 0
        self.poll_interval = poll_interval

    def stats(self):
        with self.lock:
            return {"active_requests": self.active, "queued_requests": len(self.waiters),
                    "concurrent_limit": self.limit}

    async def acquire(self, arrived_at, snapshot):
        """snapshot 异步返回（当前容量、等待上限、最大等待秒数）。"""
        ticket = (arrived_at, next(self.sequence))
        with self.lock:
            heapq.heappush(self.waiters, ticket)
        enqueued = True
        checked_limit = False
        try:
            while True:
                capacity, max_waiters, timeout = await snapshot()
                with self.lock:
                    self.limit = max(0, capacity)
                    if time.monotonic() - arrived_at >= timeout:
                        raise QueueTimeout
                    if self.waiters[0] == ticket and self.active < self.limit:
                        heapq.heappop(self.waiters)
                        enqueued = False
                        self.active += 1
                        return Lease(self)
                    if not checked_limit:
                        # 先登记到达顺序再读容量，较慢的数据库查询不会让后来者插队。
                        position = sum(other < ticket for other in self.waiters)
                        if position >= max_waiters:
                            raise QueueFull
                        checked_limit = True
                await asyncio.sleep(self.poll_interval)
        finally:
            if enqueued:
                with self.lock:
                    self.waiters.remove(ticket)
                    heapq.heapify(self.waiters)


request_queue = RequestQueue()
_snapshot_lock = threading.Lock()
_snapshot_at = 0.0
_snapshot_value = None


def cached_capacity_snapshot():
    """所有等待者共享短缓存，避免每个排队请求重复扫描 Key/代理。"""
    global _snapshot_at, _snapshot_value

    with _snapshot_lock:
        now = time.monotonic()
        if _snapshot_value is None or now - _snapshot_at >= 0.2:
            _snapshot_value = capacity_snapshot()
            _snapshot_at = now
        return _snapshot_value


def capacity_snapshot():
    """与线路构建共用线路数算法，不领取 RPM 名额。"""
    from services import key_service, proxy_service, sysconfig
    from services.load_balancer import planned_route_count

    keys = key_service.available_keys()
    routes = planned_route_count(len(keys), len(proxy_service.schedulable_proxies()))
    limit = min(max(1, sysconfig.get("max_concurrent_requests")), len(keys) // routes) if routes else 0
    return (limit, max(1, sysconfig.get("max_queued_requests")),
            max(0.01, sysconfig.get("request_queue_timeout")))
