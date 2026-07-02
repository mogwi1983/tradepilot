"""
browser-use wrapper for search and page fetch.

Spec: CURSOR-BOOTSTRAP.md Step 2 — core/browser.py
Env: BROWSER_USE_HEADLESS in .env.local
"""

from __future__ import annotations

from dataclasses import dataclass


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
    links: list[str]


class BrowserSession:
    """Open once per phase run; close on completion. Retry searches up to 3x."""

    def search(self, query: str) -> list[SearchResult]:
        raise NotImplementedError

    def fetch_page(self, url: str) -> PageContent:
        raise NotImplementedError

    def close(self) -> None:
        pass
