"""Load .env.local once at pipeline startup."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_LOADED = False


def load_env() -> None:
    global _LOADED
    if _LOADED:
        return
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env.local")
    load_dotenv(root / ".env")
    _LOADED = True


def get_lob_api_key() -> str:
    import os

    load_env()
    for key in ("LOB_API_KEY", "LOB_SECRET_API_KEY_TEST", "LOB_SECRET_API_KEY_LIVE"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    raise RuntimeError("No Lob API key in .env.local (LOB_API_KEY or LOB_SECRET_API_KEY_*)")
