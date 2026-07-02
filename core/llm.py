"""
Unified LLM client — MiniMax M2.7 (default) and DeepSeek.

Env (.env.local):
  LLM_PROVIDER=minimax          # minimax | deepseek
  MINIMAX_API_KEY=...
  MINIMAX_BASE_URL=https://api.minimax.io/v1
  MINIMAX_MODEL=MiniMax-M2.7
  DEEPSEEK_API_KEY=...
"""

from __future__ import annotations

import json
import os
import re
from typing import Literal

from openai import OpenAI

from core.env import load_env
from core.logger import RunLogger

Provider = Literal["minimax", "deepseek"]

PROVIDERS: dict[Provider, dict[str, str]] = {
    "minimax": {
        "base_url": "https://api.minimax.io/v1",
        "model": "MiniMax-M2.7",
        "api_key_env": "MINIMAX_API_KEY",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
}


class LLMClient:
    def __init__(
        self,
        provider: Provider,
        model: str,
        client: OpenAI,
        logger: RunLogger | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self._client = client
        self.logger = logger
        self.total_tokens = 0
        self.call_count = 0

    @classmethod
    def from_provider(cls, provider: Provider, logger: RunLogger | None = None) -> LLMClient:
        load_env()
        cfg = PROVIDERS[provider]
        api_key = os.getenv(cfg["api_key_env"], "").strip()
        if not api_key:
            raise RuntimeError(f"{cfg['api_key_env']} not set in .env.local")

        base_url = os.getenv(
            "MINIMAX_BASE_URL" if provider == "minimax" else "DEEPSEEK_BASE_URL",
            cfg["base_url"],
        ).strip()
        model = os.getenv(
            "MINIMAX_MODEL" if provider == "minimax" else "DEEPSEEK_MODEL",
            cfg["model"],
        ).strip()

        client = OpenAI(api_key=api_key, base_url=base_url)
        return cls(provider=provider, model=model, client=client, logger=logger)

    def _chat(self, system: str, user: str) -> str:
        kwargs: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
        }
        if self.provider == "minimax":
            kwargs["extra_body"] = {"reasoning_split": True}

        resp = self._client.chat.completions.create(**kwargs)
        self.call_count += 1

        usage = resp.usage
        if usage:
            tokens = (usage.prompt_tokens or 0) + (usage.completion_tokens or 0)
            self.total_tokens += tokens
            if self.logger:
                self.logger.debug(
                    f"{self.provider} tokens={tokens} total={self.total_tokens} calls={self.call_count}"
                )

        msg = resp.choices[0].message
        content = (msg.content or "").strip()
        reasoning = getattr(msg, "reasoning_content", None) or ""
        if reasoning and self.logger:
            self.logger.debug(f"{self.provider} reasoning_chars={len(reasoning)}")
        return _strip_thinking(content)

    def reason(self, prompt: str, context: str) -> str:
        return self._chat(prompt, context)

    def score_match(self, candidate: str, target: str, context: str) -> int:
        system = (
            "You score whether a web result belongs to a specific HVAC/trade contractor. "
            'Reply with JSON only: {"confidence": <integer 0-100>, "reason": "..."}'
        )
        user = (
            f"Target contractor: {target}\n"
            f"Candidate: {candidate}\n"
            f"Context:\n{context}\n"
            "Score confidence this candidate is the same business (not a directory listing)."
        )
        raw = self._chat(system, user)
        return _parse_confidence(raw)

    def classify_fb_page(self, page_text: str, business_name: str) -> tuple[str, int]:
        system = (
            "Classify if a Facebook page is a business page for the target contractor. "
            'Reply JSON: {"is_business_page": true/false, "confidence": 0-100, "reason": "..."}'
        )
        user = f"Business: {business_name}\nPage text:\n{page_text[:4000]}"
        raw = self._chat(system, user)
        try:
            data = json.loads(_extract_json(raw))
            conf = max(0, min(100, int(data.get("confidence", 0))))
            is_biz = bool(data.get("is_business_page", False))
            if conf >= 85 and is_biz:
                return "Y", conf
            if conf >= 60:
                return "UNCERTAIN", conf
            return "N", conf
        except (json.JSONDecodeError, ValueError, TypeError):
            return "UNCERTAIN", 50

    def extract_address(self, page_text: str, business_name: str) -> dict[str, str]:
        system = (
            "Extract a US mailing address for the business from page text. "
            'Reply JSON: {"found": true/false, "street": "", "city": "", "state": "", '
            '"zip": "", "full": "", "confidence": 0-100, "address_type": "residential|commercial|unknown"}'
        )
        user = f"Business: {business_name}\nPage:\n{page_text[:6000]}"
        raw = self._chat(system, user)
        try:
            data = json.loads(_extract_json(raw))
            if not data.get("found"):
                return {}
            return {
                "street": str(data.get("street", "")).strip(),
                "city": str(data.get("city", "")).strip(),
                "state": str(data.get("state", "")).strip(),
                "zip": str(data.get("zip", "")).strip(),
                "full": str(data.get("full", "")).strip(),
                "confidence": str(max(0, min(100, int(data.get("confidence", 0))))),
                "address_type": str(data.get("address_type", "unknown")).strip(),
            }
        except (json.JSONDecodeError, ValueError, TypeError):
            return {}


def get_default_provider() -> Provider:
    load_env()
    raw = os.getenv("LLM_PROVIDER", "minimax").strip().lower()
    if raw not in PROVIDERS:
        raise ValueError(f"Invalid LLM_PROVIDER={raw!r}; use minimax or deepseek")
    return raw  # type: ignore[return-value]


def get_llm_client(logger: RunLogger | None = None, provider: Provider | None = None) -> LLMClient:
    return LLMClient.from_provider(provider or get_default_provider(), logger)


def _strip_thinking(text: str) -> str:
    text = re.sub(r".*?", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _extract_json(text: str) -> str:
    text = _strip_thinking(text.strip())
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _parse_confidence(raw: str) -> int:
    try:
        data = json.loads(_extract_json(raw))
        return max(0, min(100, int(data.get("confidence", 0))))
    except (json.JSONDecodeError, ValueError, TypeError):
        m = re.search(r"\b(\d{1,3})\b", raw)
        return max(0, min(100, int(m.group(1)))) if m else 0
