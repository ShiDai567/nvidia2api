"""请求日志的聊天快照与按天清理。"""
import threading
import time
from datetime import timedelta

from django.utils import timezone

from apps.core.models import RequestLog
from services import sysconfig


def delete_expired(days):
    now = timezone.now()
    if days == 0 or days >= now.date().toordinal():
        return 0
    expired = RequestLog.objects.filter(created_at__lt=now - timedelta(days=days))
    deleted, _ = expired.delete()
    return deleted


_sweep_lock = threading.Lock()
_next_sweep = 0.0


def sweep_if_due():
    global _next_sweep
    if time.monotonic() < _next_sweep or not _sweep_lock.acquire(blocking=False):
        return
    try:
        if time.monotonic() >= _next_sweep:
            delete_expired(sysconfig.get("log_retention_days"))
            _next_sweep = time.monotonic() + 3600
    finally:
        _sweep_lock.release()


def create_log(messages, **fields):
    sweep_if_due()
    limit = sysconfig.get("log_message_limit")
    snapshot = {"total": len(messages), "messages": messages[:limit] if limit else messages}
    return RequestLog.objects.create(chat_snapshot=snapshot, **fields)
