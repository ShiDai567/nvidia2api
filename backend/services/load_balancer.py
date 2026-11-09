"""线路构建：NVIDIA Key 与代理线路、可配置数量的直连线路配对。

Rules:
- One request uses at most N routes, N = number of schedulable keys.
- 启用代理上限为 Key 数减去配置的直连数，调度时优先预留直连名额。
- One NVIDIA key is never used by two routes within the same request.
- RPM slots are claimed atomically so concurrent requests share the budget safely.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings

from apps.core.models import NvidiaApiKey, Proxy
from services import key_service, proxy_service, sysconfig

logger = logging.getLogger("nvidia2api.balancer")


@dataclass
class Route:
    kind: str                          # "proxy" | "direct"
    key: NvidiaApiKey
    proxy: Proxy | None = None
    claimed: bool = False

    @property
    def name(self) -> str:
        if self.kind == "direct":
            return f"direct:{self.key.name}"
        return f"{self.proxy.name}+{self.key.name}"


def build_routes(max_routes: int | None = None) -> list[Route]:
    """Build race routes.

    线路数 = min(可调度代理数 + 配置直连数, 可用 Key 数, 总线路上限)。
    优先为直连预留名额，每条线路分配不同的 Key，多余 Key 留给后续请求轮换。
    """
    cfg_max = sysconfig.get("max_routes_per_request")
    max_routes = min(max_routes or cfg_max, cfg_max)

    proxies = proxy_service.schedulable_proxies()
    keys = key_service.available_keys()

    direct_count = min(max(1, sysconfig.get("direct_routes_per_request")), len(keys), max_routes)
    route_count = min(len(proxies) + direct_count, len(keys), max_routes)
    if route_count <= 0:
        return []
    proxies = proxies[: route_count - direct_count]

    routes: list[Route] = []
    # 先领取直连名额；并发请求抢走 RPM 配额时尝试后续 Key，避免丢失直连线路。
    for key in keys:
        if len(routes) >= route_count:
            break
        if not key_service.claim_rpm_slot(key.id):
            continue
        proxy_index = len(routes) - direct_count
        proxy = proxies[proxy_index] if proxy_index >= 0 else None
        routes.append(Route(kind="proxy" if proxy else "direct", key=key, proxy=proxy))

    return routes
