"""Thin wrapper around the NVIDIA upstream API (sync + async)."""
from __future__ import annotations

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

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
    """同步官方模型，返回下架明细、原启用模型冲突及恢复明细。

    NVIDIA 的 /v1/models 是公开端点（实测无 key/假 key 均返回 200），
    因此默认不再消耗/依赖任何 NVIDIA Key；显式传入 api_key 时仍会带上。

    与上游对齐：库中 provider="nvidia" 且上游已不存在的模型会被标记
    status="retired" 并禁用（软下架，不删记录；手动添加的非 nvidia
    模型不受影响）。若上游恢复，再次同步只清除下架标记，不自动启用。
    """
    from apps.core.models import AIModel

    if api_key:
        status_code, body = list_models_raw(api_key)
    else:
        status_code, body = _list_models_anonymous()
    if status_code != 200:
        raise ValueError(f"NVIDIA 模型列表获取失败（HTTP {status_code}），本地模型未修改")
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ValueError("NVIDIA 模型列表格式异常，本地模型未修改")
    upstream_names: set[str] = set()
    for item in body["data"]:
        if not isinstance(item, dict):
            raise ValueError("NVIDIA 模型列表格式异常，本地模型未修改")
        name = item.get("id")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("NVIDIA 模型列表缺少有效模型名称，本地模型未修改")
        upstream_names.add(name)
    if not upstream_names and AIModel.objects.filter(provider="nvidia").exists():
        raise ValueError("NVIDIA 返回空模型列表，为避免误下架本地模型，本次同步已取消")

    created, existing = 0, 0
    with transaction.atomic():
        for name in sorted(upstream_names):
            _, was_created = AIModel.objects.get_or_create(
                model_name=name, defaults={"provider": "nvidia"}
            )
            if was_created:
                created += 1
            else:
                existing += 1
        local = AIModel.objects.filter(provider="nvidia").order_by("model_name")
        # 已下架却被旧客户端重新开启的记录，也要重新禁用并报告冲突。
        gone = list(local.exclude(model_name__in=upstream_names).exclude(
            status="retired", enabled=False
        ))
        retired_models = [
            {"id": m.id, "model_name": m.model_name, "was_enabled": m.enabled}
            for m in gone
        ]
        restored_models = list(local.filter(
            status="retired", model_name__in=upstream_names
        ).values("id", "model_name"))
        now = timezone.now()
        AIModel.objects.filter(pk__in=[m.id for m in gone]).update(
            status="retired", enabled=False, updated_at=now
        )
        AIModel.objects.filter(pk__in=[m["id"] for m in restored_models]).update(
            status="active", enabled=False, updated_at=now
        )
    return {
        "created": created, "existing": existing, "total": len(upstream_names),
        "retired": len(retired_models), "retired_models": retired_models,
        "conflicts": [m for m in retired_models if m["was_enabled"]],
        "restored": len(restored_models), "restored_models": restored_models,
    }
