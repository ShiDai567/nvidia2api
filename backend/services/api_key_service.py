"""User API keys: generate, hash, verify, per-key user rate limiting."""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.db.models import Case, F, Q, Value, When
from django.utils import timezone

from apps.core.models import UserApiKey


def generate_key() -> str:
    return "sk-nvidia2api-" + secrets.token_hex(18)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_key(name: str, rate_limit: int = 0) -> tuple[UserApiKey, str]:
    raw = generate_key()
    rec = UserApiKey.objects.create(
        name=name, key_hash=hash_key(raw), key_prefix=raw[:22], rate_limit=rate_limit
    )
    return rec, raw


def authenticate(raw: str | None) -> UserApiKey | None:
    if not raw:
        return None
    try:
        rec = UserApiKey.objects.get(key_hash=hash_key(raw.strip()))
    except UserApiKey.DoesNotExist:
        return None
    return rec


def check_and_count(rec: UserApiKey) -> tuple[bool, str]:
    """用一条条件 UPDATE 同时校验配额、滚动窗口并递增，避免读锁升级。"""
    now = timezone.now()
    stale = Q(minute_window_start__isnull=True) | Q(
        minute_window_start__lte=now - timedelta(seconds=60)
    )
    claimed = UserApiKey.objects.filter(pk=rec.pk, enabled=True).filter(
        stale | Q(rate_limit__lte=0) | Q(minute_request_count__lt=F("rate_limit"))
    ).update(
        minute_window_start=Case(When(stale, then=Value(now)), default=F("minute_window_start")),
        minute_request_count=Case(When(stale, then=Value(1)), default=F("minute_request_count") + 1),
        total_requests=F("total_requests") + 1,
        last_used_at=now,
    )
    if claimed:
        return True, ""
    # 失败后只读以区分禁用与超限，不再持有事务或进行写入。
    if not UserApiKey.objects.filter(pk=rec.pk, enabled=True).exists():
        return False, "disabled"
    return False, "rate_limited"


def record_result(rec: UserApiKey | None, success: bool):
    if rec is None:
        return
    field = "success_requests" if success else "failed_requests"
    UserApiKey.objects.filter(pk=rec.pk).update(**{field: F(field) + 1})
