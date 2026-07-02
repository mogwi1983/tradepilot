"""
HTTP search + page fetch for pipeline phases.

Uses DuckDuckGo HTML search and httpx page fetch. browser-use Agent is not invoked
per-query (too slow/costly); swap this module if full browser automation is required.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from core.env import load_env
from core.logger import RunLogger

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
DDG_URL = "https://html.duckduckgo.com/html/"


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


class BrowserSession:
    def __init__(self, logger: RunLogger | None = None) -> None:
        load_env()
        self.logger = logger
        self._client = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )

    def _retry(self, fn, query: str, attempts: int = 3):
        delay = 1.0
        last_err: Exception | None = None
        for i in range(attempts):
            try:
                return fn()
            except Exception as exc:
                last_err = exc
                if self.logger:
                    self.logger.debug(f"search retry {i + 1}/{attempts} for {query!r}: {exc}")
                time.sleep(delay)
                delay *= 2
        raise last_err  # type: ignore[misc]

    def search(self, query: str, *, max_results: int = 8) -> list[SearchResult]:
        def _do() -> list[SearchResult]:
            resp = self._client.post(DDG_URL, data={"q": query})
            resp.raise_for_status()
            return _parse_ddg(resp.text, max_results=max_results)

        results = self._retry(_do, query)
        if self.logger:
            self.logger.debug(f"search {query!r} -> {len(results)} results")
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

        page = self._retry(_do, url)
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


def _parse_ddg(html: str, *, max_results: int) -> list[SearchResult]:
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
