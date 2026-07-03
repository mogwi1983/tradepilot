"""Shared helpers for pipeline phases."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import pandas as pd
from rapidfuzz import fuzz

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


# ── Fuzzy pre-filter ───────────────────────────────────────────────────


def fuzzy_prefilter(
    name: str,
    results: list[Any],
    *,
    title_attr: str = "title",
    url_attr: str | None = None,
    snippet_attr: str | None = None,
    max_results: int = 3,
    min_score: int = 40,
) -> list[tuple[Any, int]]:
    """Rank search results by fuzzy name similarity against the target name.

    Returns the top ``max_results`` (result, score) tuples with score >= min_score.
    The score is the highest of token_sort_ratio against title, URL path, and snippet.
    """
    scored: list[tuple[Any, int]] = []
    for r in results:
        title = str(getattr(r, title_attr, r.get(title_attr, "") if isinstance(r, dict) else ""))
        # Build candidates from title, URL path, and snippet
        candidates = [title]
        if url_attr:
            url = str(getattr(r, url_attr, r.get(url_attr, "") if isinstance(r, dict) else ""))
            path = urlparse(url).path.replace("/", " ").replace("-", " ").replace("_", " ")
            if path.strip():
                candidates.append(path)
        if snippet_attr:
            snippet = str(
                getattr(r, snippet_attr, r.get(snippet_attr, "") if isinstance(r, dict) else "")
            )
            if len(snippet) > 10:
                candidates.append(snippet[:200])

        best = max(fuzz.token_sort_ratio(name.lower(), c.lower()) for c in candidates if c.strip())
        if best >= min_score:
            scored.append((r, best))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:max_results]
