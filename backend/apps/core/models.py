from __future__ import annotations

from django.db import models


class Timestamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class NvidiaApiKeyStatus(models.TextChoices):
    AVAILABLE = "available", "Available"
    RATE_LIMITED = "rate_limited", "Rate limited"
    ERROR = "error", "Error"
    DISABLED = "disabled", "Disabled"
    INVALID = "invalid", "Invalid"


class NvidiaApiKey(Timestamped):
    name = models.CharField(max_length=128)
    api_key = models.CharField(max_length=256, unique=True)
    status = models.CharField(
        max_length=16, choices=NvidiaApiKeyStatus.choices,
        default=NvidiaApiKeyStatus.AVAILABLE, db_index=True,
    )
    rpm_limit = models.IntegerField(default=40)
    minute_window_start = models.DateTimeField(null=True, blank=True)
    minute_request_count = models.IntegerField(default=0)
    success_count = models.IntegerField(default=0)
    failure_count = models.IntegerField(default=0)
    cooldown_until = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_error = models.CharField(max_length=256, blank=True, default="")

    class Meta:
        db_table = "nvidia_api_key"
        indexes = [models.Index(fields=["status", "last_used_at"])]

    def __str__(self):
        return self.name


class ProxyGroup(Timestamped):
    name = models.CharField(max_length=64, unique=True)
    description = models.CharField(max_length=256, blank=True, default="")
    country = models.CharField(max_length=64, blank=True, default="")
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "proxy_group"

    def __str__(self):
        return self.name


class ProxyStatus(models.TextChoices):
    UNKNOWN = "unknown", "Unknown"
    HEALTHY = "healthy", "Healthy"
    DEGRADED = "degraded", "Degraded"
    UNHEALTHY = "unhealthy", "Unhealthy"
    DISABLED = "disabled", "Disabled"


class Proxy(Timestamped):
    name = models.CharField(max_length=128)
    protocol = models.CharField(max_length=16, default="socks5")
    host = models.CharField(max_length=255)
    port = models.IntegerField()
    username = models.CharField(max_length=128, blank=True, default="")
    password = models.CharField(max_length=128, blank=True, default="")
    group = models.ForeignKey(
        ProxyGroup, null=True, blank=True, on_delete=models.SET_NULL, related_name="proxies"
    )
    country = models.CharField(max_length=64, blank=True, default="")
    region = models.CharField(max_length=64, blank=True, default="")
    city = models.CharField(max_length=64, blank=True, default="")
    isp = models.CharField(max_length=128, blank=True, default="")
    enabled = models.BooleanField(default=False, db_index=True)
    status = models.CharField(
        max_length=16, choices=ProxyStatus.choices,
        default=ProxyStatus.UNKNOWN, db_index=True,
    )
    latency_ms = models.FloatField(null=True, blank=True)
    public_ip = models.CharField(max_length=64, blank=True, default="")
    last_check_at = models.DateTimeField(null=True, blank=True)
    success_count = models.IntegerField(default=0)
    failure_count = models.IntegerField(default=0)
    consecutive_failures = models.IntegerField(default=0)
    cooldown_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "proxy"
        constraints = [
            models.UniqueConstraint(
                fields=["protocol", "host", "port", "username"], name="unique_proxy_endpoint"
            )
        ]
        indexes = [models.Index(fields=["enabled", "status"])]

    def __str__(self):
        return self.name

    @property
    def url(self) -> str:
        auth = f"{self.username}:{self.password}@" if self.username else ""
        return f"{self.protocol}://{auth}{self.host}:{self.port}"


class AIModel(Timestamped):
    model_name = models.CharField(max_length=256, unique=True)
    display_name = models.CharField(max_length=256, blank=True, default="")
    description = models.TextField(blank=True, default="")
    provider = models.CharField(max_length=64, default="nvidia")
    status = models.CharField(max_length=16, default="active")
    enabled = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "model"
        indexes = [models.Index(fields=["enabled", "model_name"])]

    def __str__(self):
        return self.model_name


class UserApiKey(Timestamped):
    name = models.CharField(max_length=128)
    key_hash = models.CharField(max_length=64, unique=True, db_index=True)
    key_prefix = models.CharField(max_length=32)
    enabled = models.BooleanField(default=True)
    rate_limit = models.IntegerField(default=0, help_text="requests per minute, 0 = unlimited")
    allowed_models = models.JSONField(
        default=list, blank=True,
        help_text="model names this key may call; empty list = all enabled models",
    )
    total_requests = models.IntegerField(default=0)
    success_requests = models.IntegerField(default=0)
    failed_requests = models.IntegerField(default=0)
    minute_window_start = models.DateTimeField(null=True, blank=True)
    minute_request_count = models.IntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "user_api_key"

    def __str__(self):
        return self.name


class RequestLog(models.Model):
    request_id = models.CharField(max_length=40, db_index=True)
    user_api_key = models.ForeignKey(
        UserApiKey, null=True, blank=True, on_delete=models.SET_NULL, related_name="logs"
    )
    model = models.CharField(max_length=256, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    duration_ms = models.FloatField(default=0)
    status = models.CharField(max_length=16, default="pending", db_index=True)  # success / error
    http_status = models.IntegerField(default=0)
    error_type = models.CharField(max_length=64, blank=True, default="")
    winner_route_type = models.CharField(max_length=16, blank=True, default="")  # direct / proxy
    winner_key_name = models.CharField(max_length=128, blank=True, default="")
    winner_proxy_name = models.CharField(max_length=128, blank=True, default="")
    proxy_public_ip = models.CharField(max_length=64, blank=True, default="")
    is_stream = models.BooleanField(default=False)
    routes_count = models.IntegerField(default=0)
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    cached_tokens = models.IntegerField(default=0)          # 缓存读取的输入 token
    first_token_ms = models.FloatField(null=True, blank=True)  # 首 chunk 耗时（TTFT）
    # Full per-route outcome of the race: winner / failed / cancelled
    routes = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "request_log"
        indexes = [models.Index(fields=["created_at", "status"])]

    def __str__(self):
        return self.request_id


class SystemSetting(models.Model):
    key = models.CharField(max_length=64, unique=True)
    value = models.TextField(blank=True, default="")
    description = models.CharField(max_length=256, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "system_setting"

    def __str__(self):
        return self.key
