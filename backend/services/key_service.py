"""NVIDIA API Key management: batch import, RPM rate limiting, cooldown."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from django.conf import settings
from datetime import timedelta

from django.db.models import Case, F, Q, Value, When
from django.utils import timezone

from services import sysconfig
from apps.core.models import NvidiaApiKey, NvidiaApiKeyStatus

logger = logging.getLogger("nvidia2api.keys")

MINUTE_SECONDS = 60


def mask_key(key: str) -> str:
    if len(key) <= 10:
        return key[:4] + "****"
    return key[:10] + "*" * 8 + key[-4:]


def parse_import_text(text: str) -> list[tuple[str, str, str | None]]:
    """Parse bulk import lines. Returns list of (name, key, auto_name_or_None)."""
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    parsed: list[tuple[str, str, str | None]] = []
    auto_idx = 0
    for ln in lines:
        if "---" in ln:
            name, key = ln.split("---", 1)
            name, key = name.strip(), key.strip()
            if not name:
                auto_idx += 1
                name = ""
            parsed.append((name, key, None))
        else:
            parsed.append(("", ln, None))
    return parsed


def bulk_import_keys(text: str) -> dict:
    """Import keys from `name---key` or bare `key` lines. Returns counters."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    seen_in_batch: set[str] = set()
    result = {"success": 0, "duplicate": 0, "invalid": 0, "failed": 0, "errors": []}
    auto_idx = NvidiaApiKey.objects.count() + 1
    for ln in lines:
        if "---" in ln:
            name, key = (p.strip() for p in ln.split("---", 1))
            if not name:
                name = f"NVIDIA Key {auto_idx:03d}"
        else:
            key = ln
            name = f"NVIDIA Key {auto_idx:03d}"
        if not key or " " in key:
            result["invalid"] += 1
            result["errors"].append({"line": ln, "reason": "invalid_format"})
            continue
        if key in seen_in_batch or NvidiaApiKey.objects.filter(api_key=key).exists():
            result["duplicate"] += 1
            continue
        try:
            NvidiaApiKey.objects.create(name=name, api_key=key, rpm_limit=sysconfig.get("default_nvidia_rpm"))
            seen_in_batch.add(key)
            auto_idx += 1
            result["success"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("import key failed")
            result["failed"] += 1
            result["errors"].append({"line": ln, "reason": str(exc)})
    return result


def available_keys() -> list[NvidiaApiKey]:
    """Keys eligible for scheduling: enabled status + not in cooldown + under RPM."""
    now = timezone.now()
    qs = NvidiaApiKey.objects.all()
    out = []
    for k in qs:
        if k.status in (NvidiaApiKeyStatus.DISABLED, NvidiaApiKeyStatus.INVALID):
            continue
        if k.cooldown_until and k.cooldown_until > now:
            continue
        if _key_under_rpm(k, now):
            out.append(k)
    out.sort(key=_score)
    return out


def _key_under_rpm(k: NvidiaApiKey, now) -> bool:
    if k.minute_window_start is None:
        return True
    elapsed = (now - k.minute_window_start).total_seconds()
    if elapsed >= MINUTE_SECONDS:
        return True
    return k.minute_request_count < k.rpm_limit


def _score(k: NvidiaApiKey):
    """Lower is better: LRU + fewer failures."""
    lru = k.last_used_at.timestamp() if k.last_used_at else 0
    return (k.failure_count, lru)


def claim_rpm_slot(key_id: int) -> bool:
    """Atomically claim one RPM slot. Uses conditional UPDATEs (no SELECT ... FOR UPDATE)
    so it is safe under SQLite's serialized write locking across threads."""
    now = timezone.now()
    window_cutoff = now - timedelta(seconds=MINUTE_SECONDS)
    ok_states = [NvidiaApiKeyStatus.AVAILABLE, NvidiaApiKeyStatus.RATE_LIMITED,
                 NvidiaApiKeyStatus.ERROR]
    base = NvidiaApiKey.objects.filter(pk=key_id, status__in=ok_states, rpm_limit__gt=0).filter(
        Q(cooldown_until__isnull=True) | Q(cooldown_until__lte=now)
    )
    stale = (
        Q(minute_window_start__isnull=True) | Q(minute_window_start__lte=window_cutoff)
    )
    # 单条条件更新同时处理窗口重置与窗口内递增，减少常态请求的写语句数。
    claimed = base.filter(
        stale | Q(minute_request_count__lt=F("rpm_limit"))
    ).update(
        minute_window_start=Case(When(stale, then=Value(now)), default=F("minute_window_start")),
        minute_request_count=Case(When(stale, then=Value(1)), default=F("minute_request_count") + 1),
        last_used_at=now,
        status=Case(When(stale, then=Value(NvidiaApiKeyStatus.AVAILABLE)), default=F("status")),
    )
    if claimed:
        return True
    # Over limit (or disabled/cooling): mark rate_limited if the limit was actually hit.
    NvidiaApiKey.objects.filter(
        pk=key_id, status=NvidiaApiKeyStatus.AVAILABLE,
        minute_window_start__gt=window_cutoff,
        minute_request_count__gte=F("rpm_limit"),
        rpm_limit__gt=0,
    ).update(status=NvidiaApiKeyStatus.RATE_LIMITED)
    return False


def report_success(key_id: int):
    NvidiaApiKey.objects.filter(pk=key_id).update(
        success_count=F("success_count") + 1,
        cooldown_until=None,
        last_error="",
        status=Case(
            When(status=NvidiaApiKeyStatus.RATE_LIMITED, then=Value(NvidiaApiKeyStatus.AVAILABLE)),
            default=F("status"),
        ),
    )


def report_failure(key_id: int, error_type: str, http_status: int = 0):
    now = timezone.now()
    cooldown_seconds = 0
    new_status = None
    if http_status == 401:
        new_status = NvidiaApiKeyStatus.INVALID
    elif http_status == 403:
        new_status = NvidiaApiKeyStatus.INVALID
    elif http_status == 429:
        new_status = NvidiaApiKeyStatus.RATE_LIMITED
        cooldown_seconds = sysconfig.get("key_cooldown_seconds")
    elif error_type == "invalid_response":
        cooldown_seconds = max(30, int(sysconfig.get("key_cooldown_seconds") / 2))
    else:  # timeout / network / 5xx
        cooldown_seconds = sysconfig.get("key_cooldown_seconds")
    updates = {
        "failure_count": F("failure_count") + 1,
        "last_error": f"{error_type}:{http_status}" if http_status else error_type,
    }
    if new_status:
        updates["status"] = new_status
    if cooldown_seconds:
        updates["cooldown_until"] = now + timedelta(seconds=cooldown_seconds)
    NvidiaApiKey.objects.filter(pk=key_id).update(**updates)
    logger.info("key %s marked failure type=%s http=%s cooldown=%ss",
                key_id, error_type, http_status, cooldown_seconds)


def test_key(key: NvidiaApiKey) -> dict:
    """Lightweight upstream check: GET /models with this key."""
    from services import nvidia_service
    try:
        status_code, _body = nvidia_service.list_models_raw(key.api_key, timeout=15)
        if status_code == 200:
            report_success(key.id)
            return {"ok": True, "http_status": status_code}
        report_failure(key.id, "http_error", status_code)
        return {"ok": False, "http_status": status_code}
    except FileNotFoundError as exc:
        # A missing local certificate/proxy file is an environment issue, not a
        # bad NVIDIA credential; do not penalize or cool down this key.
        logger.error("key test could not access a local file (errno=%s)", exc.errno)
        return {
            "ok": False,
            "error": (
                "后端访问了不存在的本地文件，通常是 SSL_CERT_FILE/SSL_CERT_DIR "
                "或 HTTPS_PROXY 配置的路径无效。请检查后端运行环境并重启服务；"
                "此错误不代表 NVIDIA Key 无效。"
            ),
        }
    except Exception as exc:  # noqa: BLE001
        report_failure(key.id, "network_error")
        return {"ok": False, "error": str(exc)}


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:24]
