from django.conf import settings
from django.test import TestCase

from apps.core.models import ContentReviewRule
from services.content_review import review_payload, review_text
from api.openai_views import _review_sse_chunks


class ContentReviewTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Token {settings.ADMIN_TOKEN}"

    def test_rules_are_applied_in_order(self):
        ContentReviewRule.objects.create(forbidden_text="secret", replacement_text="safe")
        ContentReviewRule.objects.create(forbidden_text="safe", replacement_text="public")
        self.assertEqual(review_text("secret"), "public")

    def test_disabled_and_empty_rules_are_ignored(self):
        ContentReviewRule.objects.create(forbidden_text="secret", replacement_text="x", enabled=False)
        ContentReviewRule.objects.create(forbidden_text="", replacement_text="x")
        self.assertEqual(review_text("secret"), "secret")

    def test_payload_message_and_delta_content_are_reviewed(self):
        ContentReviewRule.objects.create(forbidden_text="bad", replacement_text="good")
        payload = {"choices": [
            {"message": {"content": "bad"}}, {"delta": {"content": "bad"}},
        ]}
        self.assertEqual(review_payload(payload)["choices"][0]["message"]["content"], "good")
        self.assertEqual(payload["choices"][1]["delta"]["content"], "good")

    def test_stream_review_catches_word_split_across_chunks(self):
        ContentReviewRule.objects.create(forbidden_text="badword", replacement_text="clean")
        chunks = [
            'data: {"choices":[{"delta":{"content":"bad"}}]}\n\n',
            'data: {"choices":[{"delta":{"content":"word"}}]}\n\n',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
            'data: [DONE]\n\n',
        ]
        result = _review_sse_chunks(chunks)
        self.assertIn('"content": "clean"', result[-3])
        self.assertIn('"finish_reason":"stop"', result[-2])
        self.assertEqual(result[-1], "data: [DONE]\n\n")

    def test_admin_can_manage_multiple_rules(self):
        response = self.client.post("/api/admin/content-review-rules", {
            "forbidden_text": "bad", "replacement_text": "ok",
        }, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        rule_id = response.json()["id"]
        self.assertEqual(len(self.client.get("/api/admin/content-review-rules").json()), 1)
        self.assertEqual(self.client.patch(
            f"/api/admin/content-review-rules/{rule_id}", {"enabled": False},
            content_type="application/json",
        ).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/admin/content-review-rules/{rule_id}").status_code, 204)
