"""Async proxy check: public-IP + geo lookup with anti rate-limit handling.

代理检测会访问公共 IP 查询服务（ipinfo.io 等），这些服务都有风控
（429 / 403 挑战页）。风控响应不代表代理不可用，因此单独判定为
"rate_limited"，不计入代理失败；只有真正的网络错误才算失败。
"""
from __future__ import annotations

import asyncio
import time

import httpx
from django.utils import timezone

from apps.core.models import Proxy
from services.proxy_service import report_proxy_result

# 多个探测源，前一个被风控时回退下一个。每个返回 {url, parser}
IP_INFO_SOURCES = (
    {"url": "https://ipinfo.io/json", "kind": "ipinfo"},
    {"url": "http://ip-api.com/json", "kind": "ip-api"},
    {"url": "https://api.ip.sb/geoip", "kind": "ipsb"},
)

# 常见风控 / 反爬 HTTP 状态码：429 限流，403 挑战页
RATE_LIMIT_STATUSES = {403, 429, 503}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _parse_payload(kind: str, data: dict) -> dict:
    if kind == "ipinfo":
        return {
            "ip": data.get("ip", ""),
            "country": data.get("country", ""),
            "region": data.get("region", ""),
            "city": data.get("city", ""),
            "org": data.get("org", ""),
        }
    if kind == "ip-api":
        return {
            "ip": data.get("query", ""),
            "country": data.get("countryCode", ""),
            "region": data.get("regionName", ""),
            "city": data.get("city", ""),
            "org": data.get("isp", "") or data.get("org", ""),
        }
    return {  # api.ip.sb
        "ip": data.get("ip", ""),
        "country": data.get("country_code", ""),
        "region": data.get("region", ""),
        "city": data.get("city", ""),
        "org": data.get("isp", "") or data.get("organization", ""),
    }


async def check_proxy(proxy: Proxy, timeout: float | None = None) -> dict:
    from services import sysconfig
    timeout = timeout or sysconfig.get("proxy_timeout")
    start = time.monotonic()
    rate_limited = False
    try:
        async with httpx.AsyncClient(
            proxy=proxy.url, timeout=timeout, headers=_HEADERS,
        ) as client:
            for i, src in enumerate(IP_INFO_SOURCES):
                resp = await client.get(src["url"])
                if resp.status_code in RATE_LIMIT_STATUSES:
                    # 探测源风控：换下一个源，不判代理失败
                    rate_limited = True
                    if i < len(IP_INFO_SOURCES) - 1:
                        await asyncio.sleep(0.5)
                        continue
                    Proxy.objects.filter(pk=proxy.id).update(last_check_at=timezone.now())
                    return {
                        "ok": False,
                        "rate_limited": True,
                        "error": "探测源风控",
                        "http_status": resp.status_code,
                    }
                if resp.status_code != 200:
                    report_proxy_result(proxy.id, False)
                    Proxy.objects.filter(pk=proxy.id).update(last_check_at=timezone.now())
                    return {"ok": False, "http_status": resp.status_code}
                latency_ms = (time.monotonic() - start) * 1000
                try:
                    payload = _parse_payload(src["kind"], resp.json())
                except Exception:  # noqa: BLE001
                    payload = {"ip": ""}
                if not payload.get("ip"):
                    # 响应体被风控/网关替换，判作风控而非代理故障
                    Proxy.objects.filter(pk=proxy.id).update(last_check_at=timezone.now())
                    return {"ok": False, "rate_limited": True, "error": "响应被风控"}
                report_proxy_result(proxy.id, True, latency_ms=round(latency_ms, 1))
                update = {
                    "last_check_at": timezone.now(),
                    "public_ip": payload["ip"],
                }
                for src_key, field in (("country", "country"), ("region", "region"),
                                       ("city", "city"), ("org", "isp")):
                    if payload.get(src_key):
                        update[field] = payload[src_key]
                Proxy.objects.filter(pk=proxy.id).update(**update)
                return {
                    "ok": True,
                    "latency_ms": round(latency_ms, 1),
                    "ip": payload["ip"],
                    "country": payload["country"],
                    "region": payload["region"],
                    "city": payload["city"],
                    "via": src["kind"],
                }
    except Exception as exc:  # noqa: BLE001
        # 真正的网络层错误（连接失败/超时）才算代理失败
        latency_ms = (time.monotonic() - start) * 1000
        report_proxy_result(proxy.id, False)
        Proxy.objects.filter(pk=proxy.id).update(last_check_at=timezone.now())
        return {"ok": False, "error": type(exc).__name__, "latency_ms": round(latency_ms, 1)}
    return {"ok": False, "rate_limited": rate_limited, "error": "unknown"}


async def check_proxy_retry(proxy: Proxy, attempts: int = 2, timeout: float | None = None) -> dict:
    """带重试的探测：风控结果会换源重试，避免误判。"""
    result: dict = {}
    for attempt in range(attempts):
        result = await check_proxy(proxy, timeout)
        if result.get("ok") or not result.get("rate_limited"):
            return result
        await asyncio.sleep(1.0 + attempt)
    return result


async def check_all(timeout: float | None = None) -> dict:
    """一键检测全部代理：低并发 + 错峰启动，降低触发探测源风控的概率。

    风控（rate_limited）结果单独计数，不计入失败——代理状态保持不变。
    """
    proxies = list(Proxy.objects.filter(enabled=True))
    sem = asyncio.Semaphore(5)
    total = len(proxies)

    async def one(index: int, p: Proxy) -> tuple[int, dict]:
        await asyncio.sleep(index * 0.3)  # 错峰，避免同时打满探测源
        async with sem:
            return index, await check_proxy_retry(p, timeout=timeout)

    results = await asyncio.gather(*(one(i, p) for i, p in enumerate(proxies)))
    ok = sum(1 for _, r in results if r.get("ok"))
    rate_limited = sum(1 for _, r in results if not r.get("ok") and r.get("rate_limited"))
    failed = total - ok - rate_limited
    return {
        "total": total,
        "ok": ok,
        "failed": failed,
        "rate_limited": rate_limited,
    }
