"""Phase 2 — Facebook Detection."""

from __future__ import annotations

import pandas as pd

from core.browser import BrowserSession
from core.config import RunConfig
from core.csv_io import ensure_columns, phase_complete, update_record, write_csv
from core.llm import get_llm_client
from core.logger import RunLogger
from core.utils import display_name, is_blank, now_iso


def _search_bundle(row: pd.Series) -> list[str]:
    county = str(row.get("county", "")).title()
    return [
        f"{row.get('business_name_raw', '')} site:facebook.com",
        f"{row.get('biz_var_1', '')} site:facebook.com",
        f"{row.get('biz_var_2', '')} {county} Facebook",
        f"{row.get('combo_var_1', '')} site:facebook.com",
        f"{row.get('owner_var_1', '')} HVAC Facebook {county} TX",
    ]


def _is_fb_url(url: str) -> bool:
    return "facebook.com" in url.lower()


def run(df: pd.DataFrame, config: RunConfig, logger: RunLogger) -> pd.DataFrame:
    logger.set_phase("phase2")
    df = ensure_columns(
        df,
        [
            "fb_y/n",
            "fb_url",
            "fb_page_name",
            "fb_last_post_date",
            "fb_confidence_%",
            "fb_search_notes",
            "phase2_timestamp",
        ],
    )

    browser = BrowserSession(logger)
    llm = get_llm_client(logger)

    try:
        for _, row in df.iterrows():
            lic = str(row["license_number"])
            if phase_complete(row, 2) or not is_blank(row.get("fb_y/n")):
                continue
            if config.resume_from_record and lic != str(config.resume_from_record):
                continue

            notes: list[str] = []
            best_url = ""
            best_name = ""
            best_conf = 0
            name = display_name(row)

            for q in _search_bundle(row):
                q = " ".join(str(q).split())
                if len(q) < 4:
                    continue
                logger.debug(f"facebook search: {q}", license_number=lic)
                try:
                    results = browser.search(q)
                except Exception as exc:
                    notes.append(f"query={q}|error={exc}")
                    continue

                for r in results:
                    if not _is_fb_url(r.url):
                        continue
                    ctx = f"Title: {r.title}\nSnippet: {r.snippet}"
                    conf = llm.score_match(r.title, name, ctx)
                    notes.append(f"query={q}|url={r.url}|conf={conf}")
                    if conf > best_conf:
                        best_conf = conf
                        best_url = r.url
                        best_name = r.title

            if best_conf >= 85 and best_url:
                try:
                    page = browser.fetch_page(best_url)
                    yn, conf = llm.classify_fb_page(page.text, name)
                    if conf < best_conf:
                        conf = best_conf
                except Exception as exc:
                    yn, conf = "UNCERTAIN", best_conf
                    notes.append(f"fetch_error={exc}")
            elif 60 <= best_conf < 85:
                yn, conf = "UNCERTAIN", best_conf
            else:
                yn, conf = "N", best_conf

            df = update_record(
                df,
                lic,
                {
                    "fb_y/n": yn,
                    "fb_url": best_url if yn in ("Y", "UNCERTAIN") else "",
                    "fb_page_name": best_name,
                    "fb_last_post_date": "",
                    "fb_confidence_%": str(conf),
                    "fb_search_notes": "|".join(notes),
                    "phase2_timestamp": now_iso(),
                },
                phase=2,
            )
            write_csv(df, config.output_path)
            logger.info(f"facebook={yn} conf={conf}", license_number=lic)
    finally:
        browser.close()

    return df
