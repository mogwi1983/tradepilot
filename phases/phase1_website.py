"""Phase 1 — Website Detection."""

from __future__ import annotations

import pandas as pd

from core.browser import BrowserSession
from core.config import RunConfig
from core.csv_io import ensure_columns, phase_complete, update_record, write_csv
from core.llm import get_llm_client
from core.logger import RunLogger
from core.utils import display_name, fuzzy_prefilter, is_blank, is_probable_website, now_iso


def _search_bundle(row: pd.Series) -> list[str]:
    county = str(row.get("county", "")).title()
    return [
        f"{row.get('business_name_raw', '')} {county} TX",
        f"{row.get('biz_var_1', '')} {county} TX",
        f"{row.get('biz_var_2', '')} HVAC TX",
        f"{row.get('combo_var_1', '')} {county} TX",
        f"{row.get('owner_var_1', '')} HVAC {county} TX",
    ]


def run(df: pd.DataFrame, config: RunConfig, logger: RunLogger) -> pd.DataFrame:
    logger.set_phase("phase1")
    df = ensure_columns(
        df,
        [
            "website_y/n",
            "website_url",
            "website_confidence_%",
            "website_search_notes",
            "phase1_timestamp",
        ],
    )

    browser = BrowserSession(logger)
    llm = get_llm_client(logger)
    target = display_name

    try:
        for idx, row in df.iterrows():
            lic = str(row["license_number"])
            if phase_complete(row, 1) or not is_blank(row.get("website_y/n")):
                continue
            if config.resume_from_record and lic != str(config.resume_from_record):
                continue

            notes: list[str] = []
            best_url = ""
            best_conf = 0
            name = target(row)

            for q in _search_bundle(row):
                q = " ".join(str(q).split())
                if len(q) < 4:
                    continue
                logger.debug(f"website search: {q}", license_number=lic)
                try:
                    results = browser.search(q)
                except Exception as exc:
                    notes.append(f"query={q}|error={exc}")
                    continue

                # Fuzzy pre-filter: only score the top 2-3 plausible matches
                filtered = fuzzy_prefilter(
                    name, results,
                    title_attr="title", url_attr="url", snippet_attr="snippet",
                    max_results=3, min_score=40,
                )
                notes.append(f"query={q}|prefilter={len(filtered)}/{len(results)}")
                for r, fuzz_score in filtered:
                    if not is_probable_website(r.url):
                        notes.append(f"query={q}|skip_directory={r.url}")
                        continue
                    ctx = f"Title: {r.title}\nSnippet: {r.snippet}\nURL: {r.url}"
                    conf = llm.score_match(r.url, name, ctx)
                    notes.append(f"query={q}|url={r.url}|conf={conf}")
                    if conf > best_conf:
                        best_conf = conf
                        best_url = r.url

            if best_conf >= 85:
                yn, url, conf = "Y", best_url, best_conf
            elif best_conf >= 60:
                yn, url, conf = "UNCERTAIN", best_url, best_conf
            else:
                yn, url, conf = "N", "", best_conf

            df = update_record(
                df,
                lic,
                {
                    "website_y/n": yn,
                    "website_url": url,
                    "website_confidence_%": str(conf),
                    "website_search_notes": "|".join(notes),
                    "phase1_timestamp": now_iso(),
                },
                phase=1,
            )
            write_csv(df, config.output_path)
            logger.info(f"website={yn} conf={conf}", license_number=lic)
    finally:
        browser.close()

    return df
