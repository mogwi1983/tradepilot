"""Shared helpers for pipeline phases."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import pandas as pd

DIRECTORY_DOMAINS = {
    "facebook.com",
    "yelp.com",
    "angi.com",
    "homeadvisor.com",
    "thumbtack.com",
    "linkedin.com",
    "instagram.com",
    "google.com",
    "maps.google.com",
    "bbb.org",
    "yellowpages.com",
    "manta.com",
    "buildzoom.com",
    "nextdoor.com",
}

POBOX_RE = re.compile(r"\bP\.?\s*O\.?\s*BOX\b|\bPMB\b|\bMAILBOX\b", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return str(value).strip() == ""


def normalize_county(county: str) -> str:
    return str(county).strip().title()


def display_name(row: pd.Series) -> str:
    biz = str(row.get("business_name_raw", "")).strip()
    if biz:
        return biz
    return str(row.get("owner_name_raw", "")).strip()


def domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def is_directory_url(url: str) -> bool:
    domain = domain_of(url)
    return any(d in domain for d in DIRECTORY_DOMAINS)


def is_probable_website(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    return not is_directory_url(url)


def is_pobox(address: str) -> bool:
    return bool(POBOX_RE.search(address or ""))


def yn_from_bool(value: bool) -> str:
    return "Y" if value else "N"


def append_note(existing: str, note: str) -> str:
    note = note.strip()
    if not note:
        return existing
    if not existing:
        return note
    return f"{existing}|{note}"
