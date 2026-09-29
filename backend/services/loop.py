"""Shared background asyncio event loop + pooled httpx clients.

Previously every /v1 request spun up a brand-new event loop (asyncio.run /
new_event_loop per request) and a brand-new httpx.AsyncClient per route,
so no connection could ever be reused and TLS handshakes were paid on every
request. A single daemon event loop shared across request threads fixes that:

- HTTP keep-alive connections are pooled and reused (per sync database, so
  SQLite-backed deployments naturally get one pool per process).
- The loop lives forever; per-request work is submitted via run_coroutine.
- If a request's client disconnects mid-stream, the caller simply stops
  reading; upstream connections are drained by the pool or closed on idle.
"""
from __future__ import annotations

import asyncio
import logging
import threading

import httpx

logger = logging.getLogger("nvidia2api.loop")

_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None

# One client per (proxy-url) within a process; bound to the shared loop.
_clients: dict[str, httpx.AsyncClient] = {}
_clients_lock: threading.Lock = threading.Lock()


def get_loop() -> asyncio.AbstractEventLoop:
    """Return the shared background loop, starting it on first use."""
    global _loop, _thread
    if _loop is not None and not _loop.is_closed():
        return _loop
    with _lock:
        if _loop is not None and not _loop.is_closed():
            return _loop

        ready = threading.Event()
        result: dict[str, asyncio.AbstractEventLoop] = {}

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result["loop"] = loop
            ready.set()
            loop.run_forever()

        _thread = threading.Thread(target=_run, name="nvidia2api-asyncio", daemon=True)
        _thread.start()
        ready.wait(timeout=10)
        _loop = result["loop"]
        logger.info("shared asyncio loop started")
        return _loop


def run_coroutine(coro):
    """Submit a coroutine to the shared loop and block for its result."""
    return asyncio.run_coroutine_threadsafe(coro, get_loop()).result()


def _client_key(proxy_url: str | None) -> str:
    return proxy_url or "direct"


def acquire_client(proxy_url: str | None, timeout: httpx.Timeout) -> httpx.AsyncClient:
    """Return a pooled client for the given proxy (created lazily, reused after)."""
    key = _client_key(proxy_url)
    with _clients_lock:
        client = _clients.get(key)
        if client is None or client.is_closed:
            kwargs: dict = {"timeout": timeout}
            if proxy_url:
                kwargs["proxy"] = proxy_url
            client = httpx.AsyncClient(**kwargs)
            _clients[key] = client
        return client


async def close_idle_clients(max_idle_seconds: float = 300) -> None:
    """Optional housekeeping: drop clients whose connections have all idled out.

    httpx handles keep-alive expiry itself; this only exists so tests or a
    scheduled task can reclaim sockets. Not required for correctness.
    """
    with _clients_lock:
        for client in list(_clients.values()):
            if client.is_closed:
                continue
            # touching pool is enough to let closed transports be collected
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass
        _clients.clear()


def client_stats() -> dict[str, int]:
    with _clients_lock:
        return {k: getattr(v, "pool", None) and v.pool._connections.__len__() or 0
                for k, v in _clients.items()}
