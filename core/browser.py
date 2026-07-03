"""HTTP search + page fetch for pipeline phases.

Primary search: ddgs package (DuckDuckGo API). HTML scrape fallback if ddgs fails.
All searches are cached in data/search_cache.sqlite to reduce duplicate DDG queries.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS

from core.env import load_env
from core.logger import RunLogger

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
DDG_URL = "https://html.duckduckgo.com/html/"
SEARCH_DELAY_SEC = float(os.getenv("SEARCH_DELAY_SEC", "2.0"))
CACHE_TTL_DAYS = int(os.getenv("SEARCH_CACHE_TTL_DAYS", "7"))
_CACHE_PATH: Path | None = None


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass
class PageContent:
    url: str
    title: str
    text: str
    links: list[str] = field(default_factory=list)


def _cache_path() -> Path:
    global _CACHE_PATH
    if _CACHE_PATH is None:
        root = Path(__file__).resolve().parent.parent
        _CACHE_PATH = root / "data" / "search_cache.sqlite"
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _CACHE_PATH


def _init_cache() -> None:
    db = _cache_path()
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS search_cache (
                query_hash TEXT PRIMARY KEY,
                query_text TEXT NOT NULL,
                results_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        conn.commit()
    finally:
        conn.close()


def _cache_key(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()


def _cache_get(query: str) -> list[dict[str, Any]] | None:
    conn = sqlite3.connect(str(_cache_path()))
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=CACHE_TTL_DAYS)).isoformat()
        row = conn.execute(
            "SELECT results_json, created_at FROM search_cache WHERE query_hash = ?",
            (_cache_key(query),),
        ).fetchone()
        if row and row[1] >= cutoff:
            return json.loads(row[0])
    finally:
        conn.close()
    return None


def _cache_set(query: str, results: list[dict[str, Any]]) -> None:
    conn = sqlite3.connect(str(_cache_path()))
    try:
        conn.execute(
            """INSERT OR REPLACE INTO search_cache (query_hash, query_text, results_json, created_at)
               VALUES (?, ?, ?, ?)""",
            (
                _cache_key(query),
                query.strip(),
                json.dumps(results, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _cache_stats() -> dict[str, int]:
    conn = sqlite3.connect(str(_cache_path()))
    try:
        row = conn.execute(
            "SELECT COUNT(*), SUM(LENGTH(results_json)) FROM search_cache"
        ).fetchone()
        return {"entries": row[0] or 0, "bytes": row[1] or 0}
    finally:
        conn.close()


class BrowserSession:
    def __init__(self, logger: RunLogger | None = None) -> None:
        load_env()
        self.logger = logger
        self._client = httpx.Client(
            timeout=60.0,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        self._ddgs = DDGS()
        _init_cache()

    def _retry(self, fn, label: str, attempts: int = 3):
        delay = 2.0
        last_err: Exception | None = None
        for i in range(attempts):
            try:
                return fn()
            except Exception as exc:
                last_err = exc
                if self.logger:
                    self.logger.debug(f"{label} retry {i + 1}/{attempts}: {exc}")
                time.sleep(delay)
                delay *= 2
        raise last_err  # type: ignore[misc]

    def _search_ddgs(self, query: str, *, max_results: int) -> list[SearchResult]:
        raw = list(self._ddgs.text(query, max_results=max_results))
        results: list[SearchResult] = []
        for item in raw:
            url = item.get("href") or item.get("link") or ""
            if not url.startswith("http"):
                continue
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=url,
                    snippet=item.get("body", item.get("snippet", "")),
                )
            )
        return results

    def _search_html(self, query: str, *, max_results: int) -> list[SearchResult]:
        resp = self._client.post(DDG_URL, data={"q": query})
        resp.raise_for_status()
        return _parse_ddg_html(resp.text, max_results=max_results)

    def search(self, query: str, *, max_results: int = 8) -> list[SearchResult]:
        # Check cache first
        cached = _cache_get(query)
        if cached is not None:
            results = [
                SearchResult(title=r.get("title", ""), url=r.get("url", ""), snippet=r.get("snippet", ""))
                for r in cached
            ][:max_results]
            if self.logger:
                self.logger.debug(f"search cache HIT {query!r} -> {len(results)} results")
            return results

        def _do() -> list[SearchResult]:
            try:
                results = self._search_ddgs(query, max_results=max_results)
                if results:
                    return results
            except Exception as exc:
                if self.logger:
                    self.logger.debug(f"ddgs failed for {query!r}: {exc}")
            return self._search_html(query, max_results=max_results)

        results = self._retry(_do, f"search {query!r}")
        time.sleep(SEARCH_DELAY_SEC)
        if self.logger:
            self.logger.debug(f"search {query!r} -> {len(results)} results")

        # Save to cache
        serializable = [
            {"title": r.title, "url": r.url, "snippet": r.snippet}
            for r in results
        ]
        _cache_set(query, serializable)
        return results

    def fetch_page(self, url: str) -> PageContent:
        def _do() -> PageContent:
            resp = self._client.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            title = soup.title.get_text(strip=True) if soup.title else ""
            text = soup.get_text("\n", strip=True)
            links = []
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith("http"):
                    links.append(href)
            return PageContent(url=url, title=title, text=text[:50000], links=links[:200])

        page = self._retry(_do, f"fetch {url}")
        if self.logger:
            self.logger.debug(f"fetch {url} -> {len(page.text)} chars")
        return page

    def close(self) -> None:
        self._client.close()


def _unwrap_ddg_href(href: str) -> str:
    if "uddg=" in href:
        qs = parse_qs(urlparse(href).query)
        if "uddg" in qs:
            return unquote(qs["uddg"][0])
    return href


def _parse_ddg_html(html: str, *, max_results: int) -> list[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []
    for block in soup.select(".result"):
        a = block.select_one("a.result__a")
        if not a:
            continue
        href = _unwrap_ddg_href(a.get("href", ""))
        if not href.startswith("http"):
            continue
        title = a.get_text(" ", strip=True)
        snippet_el = block.select_one(".result__snippet")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
        results.append(SearchResult(title=title, url=href, snippet=snippet))
        if len(results) >= max_results:
            break
    return results
