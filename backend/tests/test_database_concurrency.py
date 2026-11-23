"""使用独立数据库连接验证热点计数、限流和 SQLite 锁竞争。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.db import connection, connections
from django.db.models.query import QuerySet
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.core.models import NvidiaApiKey, NvidiaApiKeyStatus, Proxy, ProxyStatus, RequestLog, UserApiKey
from services import api_key_service, key_service, proxy_service


class UserCounterTests(TestCase):
    def test_results_accumulate_with_stale_authenticated_objects(self):
        key, _ = api_key_service.create_key("调用方")
        other = UserApiKey.objects.get(pk=key.pk)
        for rec in (key, other, key):
            api_key_service.record_result(rec, True)
            api_key_service.record_result(rec, False)
        key.refresh_from_db()
        self.assertEqual((key.success_requests, key.failed_requests), (3, 3))

    def test_window_reset_disabled_and_runtime_limit(self):
        key, _ = api_key_service.create_key("调用方", rate_limit=2)
        for _ in range(2):
            self.assertEqual(api_key_service.check_and_count(key), (True, ""))
        self.assertEqual(api_key_service.check_and_count(key), (False, "rate_limited"))
        UserApiKey.objects.filter(pk=key.pk).update(
            minute_window_start=timezone.now() - timedelta(seconds=61)
        )
        self.assertEqual(api_key_service.check_and_count(key), (True, ""))
        UserApiKey.objects.filter(pk=key.pk).update(enabled=False)
        self.assertEqual(api_key_service.check_and_count(key), (False, "disabled"))
        UserApiKey.objects.filter(pk=key.pk).update(enabled=True, rate_limit=0)
        for _ in range(3):
            self.assertEqual(api_key_service.check_and_count(key), (True, ""))
        key.refresh_from_db()
        self.assertEqual(key.total_requests, 6)

    def test_zero_nvidia_rpm_does_not_claim_a_new_window(self):
        key = NvidiaApiKey.objects.create(name="无配额", api_key="local-zero", rpm_limit=0)
        self.assertFalse(key_service.claim_rpm_slot(key.pk))
        key.refresh_from_db()
        self.assertEqual(key.minute_request_count, 0)


class DatabaseConcurrencyTests(TransactionTestCase):
    def test_sqlite_uses_wal_and_immediate_transactions(self):
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode")
            self.assertEqual(cursor.fetchone()[0], "wal")
        self.assertEqual(connection.transaction_mode, "IMMEDIATE")

    def parallel(self, operation, count=32, workers=8):
        start = Barrier(workers)

        def run(index):
            try:
                if index < workers:
                    start.wait(timeout=10)
                return operation(index)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            # 显式取回每个结果，任何线程异常均使测试失败。
            return list(pool.map(run, range(count)))

    def test_user_claim_does_not_upgrade_a_read_lock(self):
        key, _ = api_key_service.create_key("调用方")
        reads = Barrier(2)
        original_get = QuerySet.get

        def simultaneous_read(qs, *args, **kwargs):
            result = original_get(qs, *args, **kwargs)
            if qs.model is UserApiKey:
                reads.wait(timeout=5)
            return result

        def claim(_):
            # 即使连接仍使用旧的 DEFERRED 模式，热点也应避免事务读后写。
            connection.settings_dict = deepcopy(connection.settings_dict)
            connection.settings_dict["OPTIONS"]["transaction_mode"] = "DEFERRED"
            return api_key_service.check_and_count(key)

        with patch.object(QuerySet, "get", simultaneous_read):
            self.assertEqual(self.parallel(claim, count=2, workers=2), [(True, "")] * 2)
        key.refresh_from_db()
        self.assertEqual(key.total_requests, 2)

    def test_user_limit_is_shared_across_connections(self):
        key, _ = api_key_service.create_key("调用方", rate_limit=7)
        results = self.parallel(lambda _: api_key_service.check_and_count(key))
        self.assertEqual(results.count((True, "")), 7)
        self.assertEqual(results.count((False, "rate_limited")), 25)
        key.refresh_from_db()
        self.assertEqual((key.total_requests, key.minute_request_count), (7, 7))
        UserApiKey.objects.filter(pk=key.pk).update(
            minute_window_start=timezone.now() - timedelta(seconds=61)
        )
        results = self.parallel(lambda _: api_key_service.check_and_count(key))
        self.assertEqual(results.count((True, "")), 7)
        key.refresh_from_db()
        self.assertEqual((key.total_requests, key.minute_request_count), (14, 7))

    def test_nvidia_limit_survives_concurrent_window_rollover(self):
        key = NvidiaApiKey.objects.create(
            name="上游", api_key="local-rollover", rpm_limit=7,
            minute_window_start=timezone.now() - timedelta(seconds=61),
            minute_request_count=7, status=NvidiaApiKeyStatus.RATE_LIMITED,
        )
        results = self.parallel(lambda _: key_service.claim_rpm_slot(key.pk))
        self.assertEqual(sum(results), 7)
        key.refresh_from_db()
        self.assertEqual(key.minute_request_count, 7)

    def test_unlimited_user_and_results_do_not_lose_counts(self):
        key, _ = api_key_service.create_key("调用方")

        def request(index):
            self.assertEqual(api_key_service.check_and_count(key), (True, ""))
            api_key_service.record_result(key, index % 2 == 0)

        self.parallel(request)
        key.refresh_from_db()
        self.assertEqual((key.total_requests, key.success_requests, key.failed_requests), (32, 16, 16))

    def test_key_reports_do_not_lose_counts(self):
        key = NvidiaApiKey.objects.create(name="上游", api_key="local-key")

        def report(index):
            if index % 2:
                key_service.report_failure(key.pk, "timeout")
            else:
                key_service.report_success(key.pk)

        self.parallel(report)
        key.refresh_from_db()
        self.assertEqual((key.success_count, key.failure_count), (16, 16))

    def test_proxy_failures_share_threshold_and_recover(self):
        proxy = Proxy.objects.create(name="代理", host="127.0.0.1", port=1080)
        self.parallel(lambda _: proxy_service.report_proxy_result(proxy.pk, False))
        proxy.refresh_from_db()
        self.assertEqual((proxy.failure_count, proxy.consecutive_failures), (32, 32))
        self.assertEqual(proxy.status, ProxyStatus.UNHEALTHY)
        self.assertIsNotNone(proxy.cooldown_until)
        self.parallel(lambda _: proxy_service.report_proxy_result(proxy.pk, True))
        proxy.refresh_from_db()
        self.assertEqual((proxy.success_count, proxy.consecutive_failures), (32, 0))
        self.assertEqual(proxy.status, ProxyStatus.HEALTHY)
        self.assertIsNone(proxy.cooldown_until)

    def test_success_preserves_disabled_and_invalid_key_status(self):
        for status in (NvidiaApiKeyStatus.DISABLED, NvidiaApiKeyStatus.INVALID):
            key = NvidiaApiKey.objects.create(name=status, api_key=status, status=status)
            key_service.report_success(key.pk)
            key.refresh_from_db()
            self.assertEqual(key.status, status)

    def test_mixed_request_writes_with_300_requests(self):
        user, _ = api_key_service.create_key("调用方")
        key = NvidiaApiKey.objects.create(name="上游", api_key="local-mixed", rpm_limit=300)
        proxy = Proxy.objects.create(name="代理", host="127.0.0.1", port=1080)

        def request(index):
            self.assertEqual(api_key_service.check_and_count(user), (True, ""))
            self.assertTrue(key_service.claim_rpm_slot(key.pk))
            log = RequestLog.objects.create(
                request_id=f"req_concurrent_{index}", user_api_key=user, model="local-model"
            )
            key_service.report_success(key.pk)
            proxy_service.report_proxy_result(proxy.pk, True)
            api_key_service.record_result(user, True)
            log.status = "success"
            log.http_status = 200
            log.save(update_fields=["status", "http_status"])

        self.parallel(request, count=300, workers=32)
        user.refresh_from_db()
        key.refresh_from_db()
        proxy.refresh_from_db()
        self.assertEqual((user.total_requests, user.success_requests), (300, 300))
        self.assertEqual((key.minute_request_count, key.success_count), (300, 300))
        self.assertEqual(proxy.success_count, 300)
        self.assertEqual(RequestLog.objects.filter(status="success", http_status=200).count(), 300)
