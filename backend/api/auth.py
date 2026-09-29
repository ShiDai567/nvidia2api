import functools
import threading
import time

from django.conf import settings
from django.http import JsonResponse


def openai_error(message, code, status, type_="api_error"):
    return JsonResponse(
        {"error": {"message": message, "type": type_, "param": None, "code": code}},
        status=status,
    )


# --- login brute-force protection (per-IP, in-process; good enough for the
# single-process deployments this project targets) ---
_LOGIN_FAILS: dict[str, list[float]] = {}
_LOGIN_LOCK = threading.Lock()
_LOGIN_WINDOW = 300  # seconds
_LOGIN_MAX_FAILS = 10


def _client_ip(request) -> str:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "?")


def _register_login_fail(ip: str) -> None:
    now = time.monotonic()
    with _LOGIN_LOCK:
        fails = [t for t in _LOGIN_FAILS.get(ip, []) if now - t < _LOGIN_WINDOW]
        fails.append(now)
        _LOGIN_FAILS[ip] = fails


def _login_blocked(ip: str) -> bool:
    now = time.monotonic()
    with _LOGIN_LOCK:
        fails = [t for t in _LOGIN_FAILS.get(ip, []) if now - t < _LOGIN_WINDOW]
        _LOGIN_FAILS[ip] = fails
        return len(fails) >= _LOGIN_MAX_FAILS


def check_login_allowed(request) -> bool:
    return not _login_blocked(_client_ip(request))


def note_login_failure(request) -> None:
    _register_login_fail(_client_ip(request))


def _constant_eq(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _extract_admin_token(request) -> str:
    """Accept both `Authorization: Token <t>` and `Bearer <t>` for the admin API."""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("token "):
        return auth[6:].strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def admin_required(view):
    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        token = _extract_admin_token(request)
        if not token or not _constant_eq(token, settings.ADMIN_TOKEN):
            return JsonResponse({"detail": "Authentication credentials were not provided."}, status=401)
        return view(request, *args, **kwargs)
    return wrapper


class AdminRequiredMixin:
    @classmethod
    def as_view(cls, **initkwargs):
        return admin_required(super().as_view(**initkwargs))
