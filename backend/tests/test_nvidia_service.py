from unittest.mock import patch

from django.test import TestCase

from apps.core.models import AIModel
from services import nvidia_service


def _upstream(names: list[str]):
    """构造上游 /v1/models 响应体。"""
    return (200, {"data": [{"id": n} for n in names]})


class SyncModelsTests(TestCase):
    def test_creates_models_from_upstream(self):
        with patch.object(nvidia_service, "_list_models_anonymous",
                          return_value=_upstream(["a/m1", "a/m2"])):
            res = nvidia_service.sync_models()
        self.assertEqual(res, {
            "created": 2, "existing": 0, "total": 2, "retired": 0,
            "retired_models": [], "conflicts": [], "restored": 0,
            "restored_models": [],
        })
        self.assertEqual(AIModel.objects.count(), 2)

    def test_retires_missing_models_and_disables_them(self):
        """库里有、上游没有的 nvidia 模型被软下架（status=retired + enabled=False）。"""
        AIModel.objects.create(model_name="a/gone", enabled=True)
        AIModel.objects.create(model_name="a/kept", enabled=True)
        with patch.object(nvidia_service, "_list_models_anonymous",
                          return_value=_upstream(["a/kept"])):
            res = nvidia_service.sync_models()
        self.assertEqual(res["retired"], 1)
        self.assertEqual(res["conflicts"], [{
            "id": AIModel.objects.get(model_name="a/gone").id,
            "model_name": "a/gone", "was_enabled": True,
        }])
        self.assertEqual(res["retired_models"], res["conflicts"])
        gone = AIModel.objects.get(model_name="a/gone")
        self.assertEqual(gone.status, "retired")
        self.assertFalse(gone.enabled)
        kept = AIModel.objects.get(model_name="a/kept")
        self.assertEqual(kept.status, "active")
        self.assertTrue(kept.enabled)

    def test_retire_is_idempotent(self):
        AIModel.objects.create(model_name="a/gone", enabled=True)
        with patch.object(nvidia_service, "_list_models_anonymous",
                          return_value=_upstream(["a/other"])):
            first = nvidia_service.sync_models()
            second = nvidia_service.sync_models()
        self.assertEqual(first["retired"], 1)
        self.assertEqual(second["retired"], 0)  # 已 retired 的不重复计数

    def test_revived_model_clears_retired_flag(self):
        """上游恢复的模型清除 retired 标记；enabled 由用户重新决定。"""
        AIModel.objects.create(model_name="a/back", enabled=False, status="retired")
        with patch.object(nvidia_service, "_list_models_anonymous",
                          return_value=_upstream(["a/back"])):
            res = nvidia_service.sync_models()
        rec = AIModel.objects.get(model_name="a/back")
        self.assertEqual(rec.status, "active")
        self.assertFalse(rec.enabled)  # 不自动启用
        self.assertEqual(res["restored"], 1)
        self.assertEqual(res["restored_models"], [{"id": rec.id, "model_name": "a/back"}])

    def test_already_retired_enabled_model_is_reported_and_disabled_again(self):
        rec = AIModel.objects.create(model_name="a/gone", enabled=True, status="retired")
        with patch.object(nvidia_service, "_list_models_anonymous",
                          return_value=_upstream(["a/other"])):
            res = nvidia_service.sync_models()
        rec.refresh_from_db()
        self.assertFalse(rec.enabled)
        self.assertEqual(res["conflicts"], [{
            "id": rec.id, "model_name": "a/gone", "was_enabled": True,
        }])

    def test_malformed_upstream_does_not_modify_local_models(self):
        rec = AIModel.objects.create(model_name="a/local", enabled=True)
        with patch.object(nvidia_service, "_list_models_anonymous",
                          return_value=(200, {"data": [{"name": "missing id"}]})):
            with self.assertRaises(ValueError):
                nvidia_service.sync_models()
        rec.refresh_from_db()
        self.assertEqual(rec.status, "active")
        self.assertTrue(rec.enabled)

    def test_empty_upstream_does_not_retire_all_local_models(self):
        rec = AIModel.objects.create(model_name="a/local", enabled=True)
        with patch.object(nvidia_service, "_list_models_anonymous",
                          return_value=_upstream([])):
            with self.assertRaisesRegex(ValueError, "返回空模型列表"):
                nvidia_service.sync_models()
        rec.refresh_from_db()
        self.assertEqual(rec.status, "active")
        self.assertTrue(rec.enabled)

    def test_custom_provider_models_untouched(self):
        """手动添加的非 nvidia 模型不受同步对齐影响。"""
        AIModel.objects.create(model_name="my/custom", enabled=True, provider="custom")
        with patch.object(nvidia_service, "_list_models_anonymous",
                          return_value=_upstream([])):
            nvidia_service.sync_models()
        rec = AIModel.objects.get(model_name="my/custom")
        self.assertEqual(rec.status, "active")
        self.assertTrue(rec.enabled)

    def test_upstream_error_raises(self):
        with patch.object(nvidia_service, "_list_models_anonymous",
                          return_value=(502, {})):
            with self.assertRaises(ValueError):
                nvidia_service.sync_models()

    def test_explicit_api_key_uses_auth_header(self):
        with patch.object(nvidia_service, "list_models_raw",
                          return_value=_upstream(["a/k"])) as mocked:
            nvidia_service.sync_models(api_key="nvapi-xyz")
        mocked.assert_called_once_with("nvapi-xyz")
