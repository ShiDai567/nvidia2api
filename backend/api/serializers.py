from rest_framework import serializers

from apps.core.models import (
    AIModel, NvidiaApiKey, Proxy, ProxyGroup, RequestLog, SystemSetting, UserApiKey,
)
from services.key_service import mask_key


class NvidiaKeySerializer(serializers.ModelSerializer):
    api_key = serializers.SerializerMethodField()
    remaining_rpm = serializers.SerializerMethodField()

    class Meta:
        model = NvidiaApiKey
        fields = [
            "id", "name", "api_key", "status", "rpm_limit", "minute_request_count",
            "remaining_rpm", "success_count", "failure_count", "last_used_at",
            "last_error", "created_at", "updated_at",
        ]

    def get_api_key(self, obj):
        return mask_key(obj.api_key)

    def get_remaining_rpm(self, obj):
        from django.utils import timezone
        now = timezone.now()
        if obj.minute_window_start is None or (now - obj.minute_window_start).total_seconds() >= 60:
            return obj.rpm_limit
        return max(obj.rpm_limit - obj.minute_request_count, 0)


class ProxyGroupSerializer(serializers.ModelSerializer):
    proxy_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = ProxyGroup
        fields = ["id", "name", "description", "country", "enabled", "proxy_count",
                  "created_at", "updated_at"]


class ProxySerializer(serializers.ModelSerializer):
    password = serializers.SerializerMethodField()
    group_name = serializers.CharField(source="group.name", read_only=True, default="")
    url = serializers.SerializerMethodField()

    class Meta:
        model = Proxy
        fields = [
            "id", "name", "protocol", "host", "port", "username", "password",
            "group", "group_name", "country", "region", "city", "isp", "enabled",
            "status", "latency_ms", "public_ip", "last_check_at", "success_count",
            "failure_count", "consecutive_failures", "url", "created_at", "updated_at",
        ]

    def get_password(self, obj):
        return "••••••" if obj.password else ""

    def get_url(self, obj):
        return f"{obj.protocol}://{obj.host}:{obj.port}"


class ProxyWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Proxy
        fields = ["name", "protocol", "host", "port", "username", "password", "group"]


class ModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIModel
        fields = ["id", "model_name", "display_name", "description", "provider",
                  "status", "enabled", "created_at", "updated_at"]


class UserApiKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = UserApiKey
        fields = ["id", "name", "key_prefix", "enabled", "rate_limit", "allowed_models",
                  "total_requests", "success_requests", "failed_requests", "last_used_at",
                  "created_at", "updated_at"]


class RequestLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = RequestLog
        fields = ["id", "request_id", "model", "created_at", "duration_ms", "status",
                  "http_status", "error_type", "winner_route_type", "winner_key_name",
                  "winner_proxy_name", "proxy_public_ip", "is_stream", "routes_count",
                  "prompt_tokens", "completion_tokens", "total_tokens",
                  "cached_tokens", "first_token_ms", "routes"]


class SettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemSetting
        fields = ["id", "key", "value", "description", "updated_at"]
