"""Backward-compatible alias — prefer core.llm.get_llm_client()."""

from __future__ import annotations

from core.llm import LLMClient


class DeepSeekClient:
    """DeepSeek provider wrapper for legacy imports."""

    def __init__(self, logger=None) -> None:
        self._client = LLMClient.from_provider("deepseek", logger)
        self.logger = logger

    def reason(self, prompt: str, context: str) -> str:
        return self._client.reason(prompt, context)

    def score_match(self, candidate: str, target: str, context: str) -> int:
        return self._client.score_match(candidate, target, context)

    def classify_fb_page(self, page_text: str, business_name: str) -> tuple[str, int]:
        return self._client.classify_fb_page(page_text, business_name)

    def extract_address(self, page_text: str, business_name: str) -> dict[str, str]:
        return self._client.extract_address(page_text, business_name)
