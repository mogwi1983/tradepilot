"""Phase 7 — Cohort Classification module.

Pure Python logic (Zero AI):
  cohort_3: website_yn == 'Y'
  cohort_2: website_yn == 'N' and fb_yn == 'Y'
  cohort_1: website_yn == 'N' and fb_yn == 'N'
"""

from __future__ import annotations

import pandas as pd

from core.config import RunConfig
from core.csv_io import ensure_columns, update_record
from core.system_logger import get_system_logger
from core.utils import is_blank, now_iso


def assign_cohort(row: pd.Series) -> str:
    web = str(row.get("website_yn", "")).strip().upper()
    fb = str(row.get("fb_yn", "")).strip().upper()

    if web == "Y":
        return "cohort_3"
    if web == "N" and fb == "Y":
        return "cohort_2"
    if web == "N" and fb == "N":
        return "cohort_1"

    return "unresolved"


def run(df: pd.DataFrame, config: RunConfig) -> pd.DataFrame:
    logger = get_system_logger()
    df = ensure_columns(
        df,
        [
            "cohort",
            "phase7_timestamp",
        ],
    )

    for idx, row in df.iterrows():
        lic = str(row["license_number"]).strip()
        if not is_blank(row.get("cohort")):
            continue

        cohort = assign_cohort(row)
        df = update_record(
            df,
            lic,
            {
                "cohort": cohort,
                "phase7_timestamp": now_iso(),
            },
            phase=7,
        )
        logger.info("Phase7", f"Cohort assigned: {cohort}", license_number=lic)

    return df
