"""Phase 3 — Other Presence Detection."""

from __future__ import annotations

import pandas as pd

from core.browser import BrowserSession
from core.config import RunConfig
from core.csv_io import ensure_columns, phase_complete, update_record, write_csv
from core.logger import RunLogger
from core.utils import display_name, is_blank, now_iso


PLATFORMS = [
    ("gbp", "Google Business"),
    ("yelp", "Yelp"),
    ("angi", "Angi"),
    ("homeadvisor", "HomeAdvisor"),
    ("thumbtack", "Thumbtack"),
    ("instagram", "Instagram"),
    ("linkedin", "LinkedIn"),
]


def _queries(row: pd.Series) -> list[str]:
    county = str(row.get("county", "")).title()
    name = display_name(row)
    return [
        f"{name} {county} TX",
        f"{row.get('biz_var_1', '')} {county}",
        f"{row.get('biz_var_2', '')} HVAC {county}",
        f"{row.get('combo_var_1', '')} TX reviews",
    ]


def run(df: pd.DataFrame, config: RunConfig, logger: RunLogger) -> pd.DataFrame:
    logger.set_phase("phase3")
    df = ensure_columns(
        df,
        [
            "gbp_found",
            "gbp_claimed",
            "gbp_review_count",
            "yelp_found",
            "angi_found",
            "other_presence_types",
            "other_presence_notes",
            "phase3_timestamp",
        ],
    )

    browser = BrowserSession(logger)
    try:
        for _, row in df.iterrows():
            lic = str(row["license_number"])
            if phase_complete(row, 3):
                continue
            if config.resume_from_record and lic != str(config.resume_from_record):
                continue

            found_types: list[str] = []
            notes: list[str] = []
            gbp = yelp = angi = "N"

            for q in _queries(row):
                q = " ".join(str(q).split())
                logger.debug(f"presence search: {q}", license_number=lic)
                try:
                    results = browser.search(q)
                except Exception as exc:
                    notes.append(f"error={exc}")
                    continue
                for r in results:
                    url = r.url.lower()
                    if "google.com/maps" in url or "business.google" in url:
                        gbp = "Y"
                        if "Google Business Profile" not in found_types:
                            found_types.append("Google Business Profile")
                    if "yelp.com" in url:
                        yelp = "Y"
                        if "Yelp" not in found_types:
                            found_types.append("Yelp")
                    if "angi.com" in url:
                        angi = "Y"
                        if "Angi" not in found_types:
                            found_types.append("Angi")
                    for key, label in PLATFORMS:
                        if key in url and label not in found_types:
                            found_types.append(label)

            df = update_record(
                df,
                lic,
                {
                    "gbp_found": gbp,
                    "gbp_claimed": "UNKNOWN" if gbp == "Y" else "",
                    "gbp_review_count": "",
                    "yelp_found": yelp,
                    "angi_found": angi,
                    "other_presence_types": "|".join(found_types),
                    "other_presence_notes": "|".join(notes) if notes else "",
                    "phase3_timestamp": now_iso(),
                },
                phase=3,
            )
            write_csv(df, config.output_path)
            logger.info(f"other_presence={len(found_types)}", license_number=lic)
    finally:
        browser.close()

    return df
