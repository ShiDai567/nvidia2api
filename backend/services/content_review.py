"""模型返回文本审查与替换。"""

import json

from apps.core.models import ContentReviewRule


class IncrementalTextReviewer:
    """分块审查文本，仅暂存可能与后续 chunk 拼成违禁词的尾部。"""

    def __init__(self, rules):
        self.rules = [(a, b) for a, b in rules if a]
        self.buffers: dict[str, list[str]] = {}

    def push(self, field: str, text: str = "", *, final: bool = False) -> str:
        buffers = self.buffers.setdefault(field, [""] * len(self.rules))
        value = text
        for index, (forbidden, replacement) in enumerate(self.rules):
            pending = buffers[index] + value
            if final:
                cut = len(pending)
            else:
                carry = max((size for size in range(1, len(forbidden))
                             if pending.endswith(forbidden[:size])), default=0)
                cut = len(pending) - carry
            stable, buffers[index] = pending[:cut], pending[cut:]
            value = stable.replace(forbidden, replacement)
        return value

    def flush(self, field: str) -> str:
        return self.push(field, final=True)


class StreamContentReviewer:
    """逐个 SSE chunk 审查输出文本，保留最短必要的跨 chunk 缓冲。"""

    TEXT_FIELDS = ("content", "reasoning_content")

    def __init__(self, rules):
        self.reviewer = IncrementalTextReviewer(rules)
        self.seen_fields: set[str] = set()

    def _flush(self) -> list[str]:
        data = {field: self.reviewer.flush(field) for field in self.seen_fields}
        data = {field: text for field, text in data.items() if text}
        if not data:
            return []
        return ["data: " + json.dumps({"choices": [{"delta": data}]},
                                      ensure_ascii=False) + "\n\n"]

    def process(self, chunk: str) -> list[str]:
        if not chunk.startswith("data:"):
            return [chunk]
        raw = chunk[5:].strip()
        if raw == "[DONE]":
            return [*self._flush(), chunk]
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            return [chunk]
        choices = payload.get("choices") if isinstance(payload, dict) else None
        choice = choices[0] if choices else None
        delta = choice.get("delta") if isinstance(choice, dict) else None
        if not isinstance(delta, dict):
            if isinstance(payload, dict) and (payload.get("usage") or (
                choice and choice.get("finish_reason")
            )):
                return [*self._flush(), chunk]
            return [chunk]

        text_fields = [field for field in self.TEXT_FIELDS if isinstance(delta.get(field), str)]
        if not text_fields:
            if choice.get("finish_reason"):
                return [*self._flush(), chunk]
            return [chunk]

        self.seen_fields.update(text_fields)
        emitted = {}
        for field in text_fields:
            text = self.reviewer.push(field, delta[field])
            if text:
                emitted[field] = text
        if not emitted:
            return []
        delta.update(emitted)
        return ["data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"]


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
