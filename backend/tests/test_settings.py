"""运行时直连设置及管理界面的线路统计。"""
from django.conf import settings
from django.test import TestCase, override_settings

from apps.core.models import NvidiaApiKey, Proxy
from services import sysconfig
from services.load_balancer import build_routes


class DirectRouteSettingsTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Token {settings.ADMIN_TOKEN}"
        for i in range(5):
            NvidiaApiKey.objects.create(name=f"k{i}", api_key=f"nvapi-{i}")

    def test_save_takes_effect_and_updates_proxy_summary(self):
        response = self.client.patch(
            "/api/admin/settings", {"settings": {"direct_routes_per_request": 3}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        param = next(p for p in response.json() if p["key"] == "direct_routes_per_request")
        self.assertEqual(param["value"], 3)
        self.assertEqual(len(build_routes()), 3)
        Proxy.objects.create(name="p1", host="10.0.0.1", port=1080, enabled=True)
        summary = self.client.get("/api/admin/proxies").json()["summary"]
        self.assertEqual(summary["direct_routes"], 3)
        self.assertEqual(summary["max_enabled_proxies"], 2)
        self.assertEqual(summary["total_routes"], 4)
        dashboard = self.client.get("/api/admin/dashboard").json()
        self.assertEqual(dashboard["max_enabled_proxies"], 2)

    def test_invalid_count_rejected_without_partial_save(self):
        for value in [0, -1, 1.5, "abc", "", True, [], {}]:
            with self.subTest(value=value):
                response = self.client.patch(
                    "/api/admin/settings",
                    {"settings": {"max_routes_per_request": 10,
                                  "direct_routes_per_request": value}},
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(sysconfig.get("direct_routes_per_request"), 1)
                self.assertEqual(sysconfig.get("max_routes_per_request"), settings.MAX_ROUTES_PER_REQUEST)

    @override_settings(DIRECT_ROUTES_PER_REQUEST=2)
    def test_null_restores_environment_default(self):
        sysconfig.set_params({"direct_routes_per_request": 3})
        sysconfig.set_params({"direct_routes_per_request": None})
        self.assertEqual(sysconfig.get("direct_routes_per_request"), 2)

    def test_summary_with_no_keys(self):
        NvidiaApiKey.objects.all().delete()
        summary = self.client.get("/api/admin/proxies").json()["summary"]
        self.assertEqual(summary["direct_routes"], 0)
        self.assertEqual(summary["total_routes"], 0)
        self.assertEqual(summary["max_enabled_proxies"], 0)
