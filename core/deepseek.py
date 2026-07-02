"""
DeepSeek API client (OpenAI-compatible).

Spec: CURSOR-BOOTSTRAP.md Step 2 — core/deepseek.py
Env: DEEPSEEK_API_KEY in .env.local
Base URL: https://api.deepseek.com
"""

from __future__ import annotations


def reason(prompt: str, context: str) -> str:
    raise NotImplementedError


def score_match(candidate: str, target: str, context: str) -> int:
    """Return 0–100 confidence that candidate matches target contractor."""
    raise NotImplementedError


def extract_address(page_text: str, business_name: str) -> dict[str, str]:
    """Return address fields dict or empty dict if none found."""
    raise NotImplementedError
