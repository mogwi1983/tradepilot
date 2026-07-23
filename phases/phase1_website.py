"""Phase 1 — Website Detection module."""

from __future__ import annotations

import pandas as pd
from rapidfuzz import fuzz

from core.browser import BrowserSession
from core.config import RunConfig
from core.csv_io import ensure_columns, update_record
from core.llm import get_llm_client
from core.system_logger import get_system_logger
from core.utils import is_blank, now_iso

SKIP_DOMAINS = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "yelp.com", "angi.com", "angieslist.com", "homeadvisor.com", "thumbtack.com",
    "yellowpages.com", "bbb.org", "houzz.com", "mapquest.com", "dnb.com",
    "bloomberg.com", "opencorporates.com", "indeed.com", "ziprecruiter.com",
}


def _search_bundle(row: pd.Series) -> list[str]:
    biz = str(row.get("business_name", "")).strip()
    county = str(row.get("county", "")).strip().title()
    owner = str(row.get("owner_name", "")).strip()

    queries = []
    if biz:
        queries.append(f"{biz} {county} TX")
        queries.append(f"{biz} HVAC Texas")
    if owner:
        queries.append(f"{owner} HVAC {county} TX")
    if biz and owner:
        queries.append(f"{biz} {owner} TX")

    return list(dict.fromkeys(q for q in queries if len(q) > 4))


def _is_directory(url: str) -> bool:
    url_lower = url.lower()
    return any(domain in url_lower for domain in SKIP_DOMAINS)


def run(df: pd.DataFrame, config: RunConfig) -> pd.DataFrame:
    logger = get_system_logger()
    df = ensure_columns(
        df,
        [
            "website_yn",
            "website_url",
            "phase1_timestamp",
        ],
    )

    browser = BrowserSession()
    llm = get_llm_client()

    try:
        for idx, row in df.iterrows():
            lic = str(row["license_number"]).strip()
            if not is_blank(row.get("website_yn")):
                continue

            biz_name = str(row.get("business_name", "")).strip() or str(row.get("owner_name", "")).strip()
            best_url = ""
            best_conf = 0

            for q in _search_bundle(row):
                try:
                    results = browser.search(q)
                except Exception as exc:
                    logger.warning("Phase1", f"Search error for query '{q}': {exc}", license_number=lic)
                    continue

                for r in results:
                    if _is_directory(r.url):
                        continue

                    # RapidFuzz title pre-score
                    fuzz_score = fuzz.token_set_ratio(biz_name.lower(), r.title.lower())
                    if fuzz_score < 40:
                        continue

                    ctx = f"Title: {r.title}\nSnippet: {r.snippet}\nURL: {r.url}"
                    conf = llm.score_match(r.url, biz_name, ctx)
                    if conf > best_conf:
                        best_conf = conf
                        best_url = r.url

                    if best_conf >= 85:
                        break

                if best_conf >= 85:
                    break

            yn = "Y" if best_conf >= 85 and best_url else "N"
            final_url = best_url if yn == "Y" else ""

            df = update_record(
                df,
                lic,
                {
                    "website_yn": yn,
                    "website_url": final_url,
                    "phase1_timestamp": now_iso(),
                },
                phase=1,
            )
            logger.info("Phase1", f"Website: website_yn={yn} (conf={best_conf}) url={final_url}", license_number=lic)

    finally:
        browser.close()

    return df
