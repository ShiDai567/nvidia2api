import threading
from datetime import timedelta

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.core.models import NvidiaApiKey, NvidiaApiKeyStatus
from services import key_service


class KeyImportTests(TestCase):
    def test_named_and_bare_formats(self):
        text = "主账号01---nvapi-aaa\n主账号02---nvapi-bbb\nnvapi-ccc\n\n  nvapi-ddd  \n"
        res = key_service.bulk_import_keys(text)
        self.assertEqual(res["success"], 4)
        self.assertEqual(NvidiaApiKey.objects.count(), 4)
        auto = NvidiaApiKey.objects.get(api_key="nvapi-ccc")
        self.assertTrue(auto.name.startswith("NVIDIA Key"))
        self.assertEqual(NvidiaApiKey.objects.get(api_key="nvapi-aaa").name, "主账号01")

    def test_dedup_and_invalid(self):
        NvidiaApiKey.objects.create(name="x", api_key="nvapi-dup")
        res = key_service.bulk_import_keys("nvapi-dup\nnvapi-dup\n   \nbad key\nnvapi-new")
        self.assertEqual(res["duplicate"], 2)
        self.assertEqual(res["invalid"], 1)
        self.assertEqual(res["success"], 1)

    def test_mask(self):
        masked = key_service.mask_key("nvapi-0123456789abcdef")
        self.assertNotIn("23456789", masked)


class RateLimitTests(TestCase):
    def setUp(self):
        self.key = NvidiaApiKey.objects.create(name="k1", api_key="nvapi-x", rpm_limit=5)

    def test_rpm_enforced(self):
        self.assertTrue(all(key_service.claim_rpm_slot(self.key.id) for _ in range(5)))
        self.assertFalse(key_service.claim_rpm_slot(self.key.id))
        self.key.refresh_from_db()
        self.assertEqual(self.key.status, NvidiaApiKeyStatus.RATE_LIMITED)

        # window rolls over
        NvidiaApiKey.objects.filter(pk=self.key.id).update(
            minute_window_start=timezone.now() - timedelta(seconds=61))
        self.assertTrue(key_service.claim_rpm_slot(self.key.id))

    def test_cooldown_blocks(self):
        NvidiaApiKey.objects.filter(pk=self.key.id).update(
            cooldown_until=timezone.now() + timedelta(seconds=30))
        self.assertFalse(key_service.claim_rpm_slot(self.key.id))

    def test_concurrent_claims_do_not_exceed_rpm(self):
        pass


class ConcurrentRateLimitTests(TransactionTestCase):
    def test_concurrent_claims_do_not_exceed_rpm(self):
        key = NvidiaApiKey.objects.create(name="k1", api_key="nvapi-x", rpm_limit=5)
        results = []

        def worker():
            results.append(key_service.claim_rpm_slot(key.id))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(results), 5)
        key.refresh_from_db()
        self.assertEqual(key.minute_request_count, 5)


class FailureStatusTests(TestCase):
    def setUp(self):
        self.key = NvidiaApiKey.objects.create(name="k", api_key="nvapi-y", rpm_limit=40)

    def test_401_marks_invalid(self):
        key_service.report_failure(self.key.id, "http_error", 401)
        self.key.refresh_from_db()
        self.assertEqual(self.key.status, NvidiaApiKeyStatus.INVALID)

    def test_429_marks_rate_limited_with_cooldown(self):
        key_service.report_failure(self.key.id, "http_error", 429)
        self.key.refresh_from_db()
        self.assertEqual(self.key.status, NvidiaApiKeyStatus.RATE_LIMITED)
        self.assertIsNotNone(self.key.cooldown_until)

    def test_success_resets(self):
        key_service.report_failure(self.key.id, "http_error", 429)
        key_service.report_success(self.key.id)
        self.key.refresh_from_db()
        self.assertEqual(self.key.status, NvidiaApiKeyStatus.AVAILABLE)
        self.assertIsNone(self.key.cooldown_until)

    def test_missing_local_file_is_not_counted_as_key_failure(self):
        from unittest.mock import patch

        with patch(
            "services.nvidia_service.list_models_raw",
            side_effect=FileNotFoundError(2, "No such file or directory"),
        ):
            result = key_service.test_key(self.key)

        self.key.refresh_from_db()
        self.assertFalse(result["ok"])
        self.assertIn("SSL_CERT_FILE", result["error"])
        self.assertEqual(self.key.failure_count, 0)
        self.assertEqual(self.key.status, NvidiaApiKeyStatus.AVAILABLE)
