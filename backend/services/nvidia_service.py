"""Thin wrapper around the NVIDIA upstream API (sync + async)."""
from __future__ import annotations

import httpx
from django.conf import settings

NVIDIA_BASE = settings.NVIDIA_BASE_URL


def list_models_raw(api_key: str, timeout: float = 30) -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(f"{NVIDIA_BASE}/models", headers=headers)
        try:
            return resp.status_code, resp.json()
        except Exception:  # noqa: BLE001
            return resp.status_code, {}


def _list_models_anonymous(timeout: float = 30) -> tuple[int, dict]:
    """Fetch the public model list without any API key."""
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(f"{NVIDIA_BASE}/models")
        try:
            return resp.status_code, resp.json()
        except Exception:  # noqa: BLE001
            return resp.status_code, {}


def sync_models(api_key: str | None = None) -> dict:
    """Pull model list from NVIDIA and upsert into AIModel.

    NVIDIA 的 /v1/models 是公开端点（实测无 key/假 key 均返回 200），
    因此默认不再消耗/依赖任何 NVIDIA Key；显式传入 api_key 时仍会带上。

    与上游对齐：库中 provider="nvidia" 且上游已不存在的模型会被标记
    status="retired" 并禁用（软下架，不删记录；手动添加的非 nvidia
    模型不受影响）。若上游恢复，再次同步会自动重新启用。
    """
    from apps.core.models import AIModel

    if api_key:
        status_code, body = list_models_raw(api_key)
    else:
        status_code, body = _list_models_anonymous()
    if status_code != 200 or "data" not in body:
        raise ValueError(f"upstream_error:{status_code}")
    upstream_names: set[str] = set()
    created, existing = 0, 0
    for item in body.get("data", []):
        name = item.get("id")
        if not name:
            continue
        upstream_names.add(name)
        rec, was_created = AIModel.objects.get_or_create(
            model_name=name, defaults={"provider": "nvidia"}
        )
        if was_created:
            created += 1
        else:
            existing += 1
    # 软下架：库里有、上游没有的 nvidia 模型
    local = AIModel.objects.filter(provider="nvidia")
    gone_ids = [m.id for m in local if m.model_name not in upstream_names]
    retired = 0
    if gone_ids:
        retired = AIModel.objects.filter(pk__in=gone_ids).exclude(
            status="retired"
        ).update(status="retired", enabled=False)
    # 已 retired 且上游恢复的模型：清除 retired 标记（enabled 仍由用户决定）。
    # 注意：这一步必须在任何 gone_ids 下都执行，否则"只恢复、无下架"的同步
    # 永远不会复活模型。
    AIModel.objects.filter(provider="nvidia", status="retired").exclude(
        pk__in=gone_ids
    ).update(status="active")
    return {
        "created": created, "existing": existing, "total": len(upstream_names),
        "retired": retired,
    }
