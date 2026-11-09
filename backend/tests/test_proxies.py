from django.test import TestCase

from apps.core.models import NvidiaApiKey, Proxy, ProxyStatus
from services import proxy_service, sysconfig


def make_key(i):
    return NvidiaApiKey.objects.create(name=f"k{i}", api_key=f"nvapi-{i}")


class ProxyParseTests(TestCase):
    def test_parse_variants(self):
        p = proxy_service.parse_proxy_url("socks5://user:pass@1.2.3.4:1080")
        self.assertEqual((p["protocol"], p["host"], p["port"], p["username"], p["password"]),
                         ("socks5", "1.2.3.4", 1080, "user", "pass"))
        self.assertEqual(proxy_service.parse_proxy_url("http://1.2.3.4:8080")["protocol"], "http")
        self.assertIsNone(proxy_service.parse_proxy_url("ftp://1.2.3.4:21"))
        self.assertIsNone(proxy_service.parse_proxy_url("socks5://nohost"))

    def test_import(self):
        text = "美国01---socks5://1.1.1.1:1001\n日本01---socks5://2.2.2.2:1002\nhttp://3.3.3.3:8080\nbad://x\n"
        res = proxy_service.bulk_import_proxies(text)
        self.assertEqual(res["success"], 3)
        self.assertEqual(res["invalid"], 1)
        auto = Proxy.objects.get(host="3.3.3.3")
        self.assertTrue(auto.name.startswith("代理"))
        # duplicate
        res2 = proxy_service.bulk_import_proxies("socks5://1.1.1.1:1001")
        self.assertEqual(res2["duplicate"], 1)


class EnableLimitTests(TestCase):
    def test_limit_reserves_configured_direct_routes(self):
        for i in range(5):
            make_key(i)
        sysconfig.set_params({"direct_routes_per_request": 3})
        self.assertEqual(proxy_service.max_proxies_for_current_keys(), 2)
        enabled = []
        for i in range(3):
            proxy = Proxy.objects.create(name=f"p{i}", host=f"10.0.0.{i}", port=1080)
            ok, _ = proxy_service.set_enabled(proxy, True)
            enabled.append(ok)
        self.assertEqual(enabled, [True, True, False])
        sysconfig.set_params({"direct_routes_per_request": 10})
        self.assertEqual(proxy_service.max_proxies_for_current_keys(), 0)

    def test_limit_is_n_minus_1(self):
        for i in range(5):
            make_key(i)
        proxies = [
            Proxy.objects.create(name=f"p{i}", protocol="socks5", host=f"10.0.0.{i}", port=1000)
            for i in range(6)
        ]
        ok_count = 0
        last_msg = ""
        for p in proxies:
            ok, msg = proxy_service.set_enabled(p, True)
            ok_count += 1 if ok else 0
            last_msg = msg
        self.assertEqual(ok_count, 4)
        self.assertIn("最多允许启用 4 个代理", last_msg)

    def test_disable_always_allowed(self):
        make_key(1)
        p = Proxy.objects.create(name="p", protocol="socks5", host="1.1.1.1", port=1)
        ok, _ = proxy_service.set_enabled(p, True)
        self.assertFalse(ok)  # 1 key -> 0 proxies allowed
        ok, _ = proxy_service.set_enabled(p, False)
        self.assertTrue(ok)

    def test_failure_cooldown(self):
        p = Proxy.objects.create(name="p", protocol="socks5", host="1.1.1.1", port=1)
        for _ in range(3):
            proxy_service.report_proxy_result(p.id, False)
        p.refresh_from_db()
        self.assertEqual(p.status, ProxyStatus.UNHEALTHY)
        self.assertIsNotNone(p.cooldown_until)
        proxy_service.report_proxy_result(p.id, True, latency_ms=120)
        p.refresh_from_db()
        self.assertEqual(p.status, ProxyStatus.HEALTHY)
        self.assertEqual(p.latency_ms, 120)
