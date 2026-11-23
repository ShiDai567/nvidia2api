from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.core.models import AIModel, RequestLog
from services import api_key_service, sysconfig


class RequestLogSettingsTests(TestCase):
    def test_message_prefix_and_admin_detail(self):
        AIModel.objects.create(model_name="test", enabled=True)
        _, raw = api_key_service.create_key("调用方")
        admin = {"HTTP_AUTHORIZATION": f"Token {settings.ADMIN_TOKEN}"}
        messages = [{"role": "user", "content": str(i)} for i in range(55)]
        body = {"model": "test", "messages": messages}
        for expected in (50, 55):
            if expected == 55:
                sysconfig.set_params({"log_message_limit": 0})
            response = self.client.post("/v1/chat/completions", body, content_type="application/json",
                                        HTTP_AUTHORIZATION=f"Bearer {raw}")
            self.assertEqual(response.status_code, 503)
            row = self.client.get("/api/admin/logs", **admin).json()["results"][0]
            self.assertNotIn("chat_snapshot", row)
            url = f"/api/admin/logs/{row['id']}/messages"
            self.assertEqual(self.client.get(url).status_code, 401)
            self.assertEqual(self.client.get(url, **admin).json()["snapshot"],
                             {"total": 55, "messages": messages[:expected]})

    def test_retention_zero_and_default(self):
        old = RequestLog.objects.create(model="test", request_id="old")
        RequestLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=31))
        new = RequestLog.objects.create(model="test", request_id="recent")
        sysconfig.set_params({"log_retention_days": 0})
        call_command("clean_logs")
        self.assertTrue(RequestLog.objects.filter(pk=old.pk).exists())
        sysconfig.set_params({"log_retention_days": None})
        with patch("services.request_logs._next_sweep", 0):
            self.client.get("/api/admin/logs", HTTP_AUTHORIZATION=f"Token {settings.ADMIN_TOKEN}")
        self.assertEqual(list(RequestLog.objects.values_list("pk", flat=True)), [new.pk])
