"""模型返回文本审查与替换。"""

from apps.core.models import ContentReviewRule


def review_text(text: str, rules=None) -> str:
    """按管理端规则顺序替换文本中的违禁词。"""
    if rules is None:
        rules = ContentReviewRule.objects.filter(enabled=True).order_by("id").values_list(
            "forbidden_text", "replacement_text"
        )
    for forbidden, replacement in rules:
        if forbidden:
            text = text.replace(forbidden, replacement)
    return text


def review_payload(payload: dict) -> dict:
    """审查 OpenAI chat completion 中可见的文本字段，不改动工具调用等结构。"""
    for choice in payload.get("choices", []):
        for field in ("message", "delta"):
            message = choice.get(field) or {}
            for text_field in ("content", "reasoning_content"):
                content = message.get(text_field)
                if isinstance(content, str):
                    message[text_field] = review_text(content)
    return payload
