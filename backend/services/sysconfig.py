"""Runtime system parameters.

Values live in `SystemSetting` (editable via the admin API) and fall back to
environment-driven Django settings. Read at call time so changes take effect
without a restart.
"""
from __future__ import annotations

import math

from django.conf import settings

from apps.core.models import SystemSetting

# key -> (type, default, description)
RUNTIME_PARAMS: dict[str, tuple[str, object, str]] = {
    "default_nvidia_rpm": ("int", lambda: settings.DEFAULT_NVIDIA_RPM, "NVIDIA Key 默认每分钟请求数"),
    "max_routes_per_request": ("int", lambda: settings.MAX_ROUTES_PER_REQUEST, "单次请求最大并行线路数"),
    "direct_routes_per_request": ("int", lambda: settings.DIRECT_ROUTES_PER_REQUEST, "每次请求并行直连数（至少 1 条，每条使用不同 Key；受可用 Key 数和总线路上限限制）"),
    "proxy_timeout": ("float", lambda: settings.PROXY_TIMEOUT, "代理测速超时（秒）"),
    "upstream_connect_timeout": ("float", lambda: settings.UPSTREAM_CONNECT_TIMEOUT, "上游连接超时（秒）"),
    "upstream_read_timeout": ("float", lambda: settings.UPSTREAM_READ_TIMEOUT, "等待 NVIDIA 完整回复或下一段流式数据的最长时间（秒），超时断开连接。空行与心跳不延长等待。"),
    "max_concurrent_requests": ("int", lambda: settings.MAX_CONCURRENT_REQUESTS, "单进程并发请求上限，流式请求计至选出胜出线路"),
    "proxy_failure_cooldown_seconds": ("int", 60, "代理连续失败后的冷却时间（秒）"),
    "proxy_unhealthy_threshold": ("int", 3, "代理连续失败多少次后标记为 unhealthy"),
    "key_cooldown_seconds": ("int", 60, "NVIDIA Key 失败后冷却时间（秒）"),
    "log_retention_days": ("int", 30, "超过期限的请求日志及聊天内容会自动删除，0 表示永久保存。"),
    "log_message_limit": ("int", 50, "每次请求按原顺序保存的前几条聊天消息，0 表示保存全部。仅管理员可查看。"),
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
    for key in ("log_retention_days", "log_message_limit"):
        value = updates.get(key)
        if value is not None:
            try:
                valid = int(str(value)) >= 0
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(f"{key} 必须为非负整数")
    timeout = updates.get("upstream_read_timeout")
    if timeout is not None:
        try:
            seconds = float(str(timeout))
        except ValueError:
            seconds = 0
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("NVIDIA 回复超时必须为大于 0 的秒数")
    value = updates.get("max_concurrent_requests")
    if value is not None:
        try:
            valid = int(str(value)) > 0
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("max_concurrent_requests 必须为大于 0 的整数")
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
