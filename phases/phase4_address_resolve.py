"""Phase 4 — Address Resolution module.

Uses a multi-source free ladder and strict 100% code-based validation (Zero AI).
"""

from __future__ import annotations

import pandas as pd

from core.address_validator import extract_candidate_addresses, validate_and_parse_address
from core.browser import BrowserSession
from core.config import RunConfig
from core.csv_io import ensure_columns, update_record
from core.system_logger import get_system_logger
from core.utils import is_blank, now_iso

CAD_URLS = {
    "tarrant": "tad.org",
    "dallas": "dallascad.org",
    "denton": "dentoncad.com",
    "collin": "collincad.org",
    "johnson": "johnsoncad.org",
    "ellis": "elliscad.com",
    "harris": "hcad.org",
    "travis": "traviscad.org",
    "bexar": "bcad.org",
}


def _try_validate_text(text: str, source_name: str, logger: any, lic: str) -> tuple[dict[str, str] | None, str]:
    """Extract and validate address candidates from raw text. Returns (parsed_dict, source_name)."""
    if not text:
        return None, ""

    # Test direct text first
    parsed = validate_and_parse_address(text)
    if parsed:
        return parsed, source_name

    # Scan text for candidates
    candidates = extract_candidate_addresses(text)
    for cand in candidates:
        parsed = validate_and_parse_address(cand)
        if parsed:
            logger.info("Phase4", f"Address candidate validated via {source_name}: {parsed}", license_number=lic)
            return parsed, source_name

    return None, ""


def run(df: pd.DataFrame, config: RunConfig) -> pd.DataFrame:
    logger = get_system_logger()
    df = ensure_columns(
        df,
        [
            "address_line1",
            "address_city",
            "address_state",
            "address_zip",
            "address_source",
            "phase4_timestamp",
        ],
    )

    browser = BrowserSession()

    try:
        for idx, row in df.iterrows():
            lic = str(row["license_number"]).strip()
            if not is_blank(row.get("address_line1")):
                continue

            biz_name = str(row.get("business_name", "")).strip()
            owner_name = str(row.get("owner_name", "")).strip()
            county = str(row.get("county", "")).strip().lower()

            parsed_addr: dict[str, str] | None = None
            found_source: str = ""

            # Ladder Priority 1 — Contractor Website
            if not parsed_addr and str(row.get("website_yn", "")).upper() == "Y" and row.get("website_url"):
                web_url = str(row["website_url"])
                try:
                    for suffix in ("", "/contact", "/about"):
                        target_url = web_url.rstrip("/") + suffix if suffix else web_url
                        page = browser.fetch_page(target_url)
                        parsed_addr, found_source = _try_validate_text(page.text, "website", logger, lic)
                        if parsed_addr:
                            break
                except Exception as exc:
                    logger.warning("Phase4", f"Website fetch failed '{web_url}': {exc}", license_number=lic)

            # Ladder Priority 2 — Facebook Page
            if not parsed_addr and str(row.get("fb_y/n", "")).upper() == "Y" and row.get("fb_url"):
                fb_url = str(row["fb_url"])
                try:
                    page = browser.fetch_page(fb_url)
                    parsed_addr, found_source = _try_validate_text(page.text, "facebook", logger, lic)
                except Exception as exc:
                    logger.warning("Phase4", f"Facebook fetch failed '{fb_url}': {exc}", license_number=lic)

            # Ladder Priority 3 — Google Search Snippets
            if not parsed_addr:
                q_list = []
                if biz_name:
                    q_list.append(f"{biz_name} {county} TX address")
                if owner_name:
                    q_list.append(f"{owner_name} HVAC {county} TX address")

                for q in q_list:
                    try:
                        results = browser.search(q)
                        for r in results:
                            snippet_text = f"{r.title} {r.snippet}"
                            parsed_addr, found_source = _try_validate_text(snippet_text, "gsearch", logger, lic)
                            if parsed_addr:
                                break
                    except Exception as exc:
                        logger.warning("Phase4", f"Search failed '{q}': {exc}", license_number=lic)
                    if parsed_addr:
                        break

            # Ladder Priority 4 — OpenCorporates
            if not parsed_addr and biz_name:
                q = f"site:opencorporates.com {biz_name} Texas"
                try:
                    results = browser.search(q)
                    for r in results:
                        if "opencorporates.com" in r.url.lower():
                            page = browser.fetch_page(r.url)
                            parsed_addr, found_source = _try_validate_text(page.text, "opencorporates", logger, lic)
                            if parsed_addr:
                                break
                except Exception as exc:
                    logger.warning("Phase4", f"OpenCorporates search failed '{q}': {exc}", license_number=lic)

            # Ladder Priority 5 — County Appraisal District (CAD)
            if not parsed_addr and county in CAD_URLS:
                cad_domain = CAD_URLS[county]
                q = f"site:{cad_domain} {owner_name or biz_name}"
                try:
                    results = browser.search(q)
                    for r in results:
                        if cad_domain in r.url.lower():
                            page = browser.fetch_page(r.url)
                            parsed_addr, found_source = _try_validate_text(page.text, "county_cad", logger, lic)
                            if parsed_addr:
                                break
                except Exception as exc:
                    logger.warning("Phase4", f"County CAD search failed '{q}': {exc}", license_number=lic)

            # Save results
            if parsed_addr:
                updates = {
                    "address_line1": parsed_addr["address_line1"],
                    "address_city": parsed_addr["address_city"],
                    "address_state": parsed_addr["address_state"],
                    "address_zip": parsed_addr["address_zip"],
                    "address_source": found_source,
                    "phase4_timestamp": now_iso(),
                }
                logger.info(
                    "Phase4",
                    f"Address resolved via {found_source}: {parsed_addr['address_line1']}, {parsed_addr['address_city']}, TX {parsed_addr['address_zip']}",
                    license_number=lic,
                )
            else:
                updates = {
                    "address_line1": "",
                    "address_city": "",
                    "address_state": "",
                    "address_zip": "",
                    "address_source": "",
                    "phase4_timestamp": now_iso(),
                }
                logger.info("Phase4", "No valid address found across ladder", license_number=lic)

            df = update_record(df, lic, updates, phase=4)

    finally:
        browser.close()

    return df
