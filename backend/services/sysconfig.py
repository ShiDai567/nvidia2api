"""Runtime system parameters.

Values live in `SystemSetting` (editable via the admin API) and fall back to
environment-driven Django settings. Read at call time so changes take effect
without a restart (except MAX_CONCURRENT_REQUESTS, which sizes a semaphore at
process start).
"""
from __future__ import annotations

from django.conf import settings

from apps.core.models import SystemSetting

# key -> (type, default, description)
RUNTIME_PARAMS: dict[str, tuple[str, object, str]] = {
    "default_nvidia_rpm": ("int", lambda: settings.DEFAULT_NVIDIA_RPM, "NVIDIA Key 默认每分钟请求数"),
    "max_routes_per_request": ("int", lambda: settings.MAX_ROUTES_PER_REQUEST, "单次请求最大并行线路数"),
    "direct_routes_per_request": ("int", lambda: settings.DIRECT_ROUTES_PER_REQUEST, "每次请求并行直连数（至少 1 条，每条使用不同 Key；受可用 Key 数和总线路上限限制）"),
    "proxy_timeout": ("float", lambda: settings.PROXY_TIMEOUT, "代理测速超时（秒）"),
    "upstream_connect_timeout": ("float", lambda: settings.UPSTREAM_CONNECT_TIMEOUT, "上游连接超时（秒）"),
    "upstream_read_timeout": ("float", lambda: settings.UPSTREAM_READ_TIMEOUT, "上游读超时（秒）"),
    "max_concurrent_requests": ("int", lambda: settings.MAX_CONCURRENT_REQUESTS, "平台最大并发请求数（需重启生效）"),
    "proxy_failure_cooldown_seconds": ("int", 60, "代理连续失败后的冷却时间（秒）"),
    "proxy_unhealthy_threshold": ("int", 3, "代理连续失败多少次后标记为 unhealthy"),
    "key_cooldown_seconds": ("int", 60, "NVIDIA Key 失败后冷却时间（秒）"),
}


def _cast(raw: str, type_name: str):
    if type_name == "int":
        return int(raw)
    if type_name == "float":
        return float(raw)
    if type_name == "bool":
        return str(raw).lower() in ("1", "true", "yes", "on")
    return raw


def get(key: str):
    """Current effective value for a runtime param."""
    type_name, default, _desc = RUNTIME_PARAMS[key]
    rec = SystemSetting.objects.filter(key=key).first()
    if rec is None or rec.value == "":
        return default() if callable(default) else default
    try:
        return _cast(rec.value, type_name)
    except (TypeError, ValueError):
        return default() if callable(default) else default


def all_params() -> list[dict]:
    return [
        {
            "key": key,
            "type": meta[0],
            "value": get(key),
            "default": meta[1]() if callable(meta[1]) else meta[1],
            "description": meta[2],
        }
        for key, meta in RUNTIME_PARAMS.items()
    ]


def set_params(updates: dict) -> None:
    # 先校验整批更新，避免无效直连数导致同一次请求的其他设置部分保存。
    direct = updates.get("direct_routes_per_request")
    if direct is not None:
        try:
            valid = not isinstance(direct, bool) and int(str(direct)) >= 1
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("每次请求并行直连数必须为大于等于 1 的整数")
    for key, value in updates.items():
        if key not in RUNTIME_PARAMS:
            continue
        rec, _ = SystemSetting.objects.get_or_create(
            key=key, defaults={"description": RUNTIME_PARAMS[key][2]}
        )
        rec.value = "" if value is None else str(value)
        rec.save(update_fields=["value", "updated_at"])
