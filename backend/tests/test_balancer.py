from django.test import TestCase

from apps.core.models import NvidiaApiKey, Proxy
from services import key_service, proxy_service, sysconfig
from services.load_balancer import build_routes


class BalancerTests(TestCase):
    def _setup(self, n_keys, n_proxies):
        keys = [NvidiaApiKey.objects.create(name=f"k{i}", api_key=f"nvapi-{i}") for i in range(n_keys)]
        proxies = []
        for i in range(n_proxies):
            p = Proxy.objects.create(name=f"px{i}", protocol="socks5",
                                     host=f"10.0.0.{i}", port=1000 + i)
            proxies.append(p)
        return keys, proxies

    def test_5_keys_4_proxies_5_routes(self):
        keys, proxies = self._setup(5, 20)
        enabled = 0
        for p in proxies:
            ok, _ = proxy_service.set_enabled(p, True)
            enabled += ok
        self.assertEqual(enabled, 4)

        routes = build_routes()
        self.assertEqual(len(routes), 5)
        proxy_routes = [r for r in routes if r.proxy]
        direct = [r for r in routes if r.proxy is None]
        self.assertEqual(len(proxy_routes), 4)
        self.assertEqual(len(direct), 1)
        # one key per route
        key_ids = [r.key.id for r in routes]
        self.assertEqual(len(set(key_ids)), 5)

    def test_10_keys_20_proxies_max_9(self):
        keys, proxies = self._setup(10, 20)
        enabled = 0
        for p in proxies:
            ok, _ = proxy_service.set_enabled(p, True)
            enabled += ok
        self.assertEqual(enabled, 9)
        routes = build_routes()
        self.assertEqual(len(routes), 10)
        self.assertEqual(len([r for r in routes if r.proxy is None]), 1)

    def test_rpm_slots_claimed_by_balancer(self):
        # 2 keys, 0 enabled proxies -> 1 direct route only; exactly one key claimed
        keys, _ = self._setup(2, 0)
        routes1 = build_routes()
        self.assertEqual(len(routes1), 1)
        claimed = sum(1 for k in [NvidiaApiKey.objects.get(pk=x.pk) for x in keys]
                      if k.minute_request_count == 1)
        self.assertEqual(claimed, 1)


class RouteCountSemanticsTests(TestCase):
    def test_configured_direct_routes_race_concurrently(self):
        import asyncio
        from unittest.mock import patch

        from services import race_engine
        from services.race_engine import RaceResult

        for i in range(3):
            NvidiaApiKey.objects.create(name=f"k{i}", api_key=f"nvapi-{i}")
        sysconfig.set_params({"direct_routes_per_request": 3})
        routes = build_routes()
        started = set()
        cancelled = set()

        async def check():
            all_started = asyncio.Event()
            pending = asyncio.Event()

            async def request(route, *args):
                started.add(route.key.id)
                if len(started) == 3:
                    all_started.set()
                try:
                    await all_started.wait()
                    if route is routes[0]:
                        return RaceResult(ok=True, route=route, payload={
                            "choices": [{"message": {"content": "回复"}}],
                        }, http_status=200)
                    await pending.wait()
                except asyncio.CancelledError:
                    cancelled.add(route.key.id)
                    raise

            with patch.object(race_engine, "_do_request", side_effect=request):
                return await asyncio.wait_for(race_engine._race(routes, {}, "http://test"), 1)

        winner = asyncio.run(check())
        self.assertEqual(started, {r.key.id for r in routes})
        self.assertEqual(winner.route, routes[0])
        self.assertEqual(cancelled, {r.key.id for r in routes[1:]})

    def test_multiple_direct_routes_use_distinct_keys(self):
        for i in range(5):
            NvidiaApiKey.objects.create(name=f"k{i}", api_key=f"nvapi-{i}")
        sysconfig.set_params({"direct_routes_per_request": 3})
        routes = build_routes()
        self.assertEqual(len(routes), 3)
        self.assertTrue(all(r.kind == "direct" for r in routes))
        self.assertEqual(len({r.key.id for r in routes}), 3)
        self.assertEqual(sum(NvidiaApiKey.objects.values_list("minute_request_count", flat=True)), 3)

    def test_direct_routes_reserve_capacity_with_existing_proxies(self):
        for i in range(5):
            NvidiaApiKey.objects.create(name=f"k{i}", api_key=f"nvapi-{i}")
        for i in range(4):
            Proxy.objects.create(name=f"p{i}", host=f"10.0.0.{i}", port=1080, enabled=True)
        sysconfig.set_params({"direct_routes_per_request": 3})
        routes = build_routes()
        self.assertEqual(len(routes), 5)
        self.assertEqual(sum(r.kind == "direct" for r in routes), 3)
        self.assertEqual(sum(r.kind == "proxy" for r in routes), 2)
        self.assertEqual(len({r.key.id for r in routes}), 5)
        self.assertEqual(Proxy.objects.filter(enabled=True).count(), 4)

    def test_direct_routes_limited_by_keys_and_route_cap(self):
        for i in range(3):
            NvidiaApiKey.objects.create(name=f"k{i}", api_key=f"nvapi-{i}")
        sysconfig.set_params({"direct_routes_per_request": 10})
        self.assertEqual(len(build_routes()), 3)
        self.assertEqual(len(build_routes(max_routes=2)), 2)
        sysconfig.set_params({"max_routes_per_request": 1})
        self.assertEqual(len(build_routes()), 1)
        NvidiaApiKey.objects.all().delete()
        self.assertEqual(build_routes(), [])

    def test_direct_routes_retry_key_after_atomic_rpm_claim_fails(self):
        from unittest.mock import patch

        for i in range(4):
            NvidiaApiKey.objects.create(name=f"k{i}", api_key=f"nvapi-{i}")
        sysconfig.set_params({"direct_routes_per_request": 2})
        claim = key_service.claim_rpm_slot
        calls = []

        def claim_after_conflict(key_id):
            calls.append(key_id)
            return False if len(calls) == 1 else claim(key_id)

        with patch("services.key_service.claim_rpm_slot", side_effect=claim_after_conflict):
            routes = build_routes()
        self.assertEqual(len(routes), 2)
        self.assertTrue(all(r.kind == "direct" for r in routes))
        self.assertEqual(len(calls), 3)

    def test_routes_equal_proxies_plus_one(self):
        # 30 keys, only 6 proxies enabled -> exactly 6 proxy routes + 1 direct = 7
        for i in range(30):
            NvidiaApiKey.objects.create(name=f"k{i}", api_key=f"nvapi-x{i}")
        proxies = [
            Proxy.objects.create(name=f"p{i}", protocol="socks5",
                                 host=f"10.1.0.{i}", port=1000)
            for i in range(10)
        ]
        for p in proxies[:6]:
            ok, _ = __import__("services.proxy_service", fromlist=["set_enabled"]).set_enabled(p, True)
            assert ok
        routes = build_routes()
        self.assertEqual(len(routes), 7)
        self.assertEqual(len([r for r in routes if r.proxy]), 6)
        self.assertEqual(len([r for r in routes if r.proxy is None]), 1)
        key_ids = [r.key.id for r in routes]
        self.assertEqual(len(set(key_ids)), 7)

    def test_no_proxies_single_direct_route(self):
        for i in range(5):
            NvidiaApiKey.objects.create(name=f"k{i}", api_key=f"nvapi-z{i}")
        routes = build_routes()
        self.assertEqual(len(routes), 1)
        self.assertIsNone(routes[0].proxy)
