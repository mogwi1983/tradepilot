"""Phase 6 — Escalation Queue Export."""

from __future__ import annotations

import pandas as pd

from core.config import RunConfig
from core.csv_io import write_csv
from core.logger import RunLogger


def _recommended_source(row: pd.Series) -> str:
    if str(row.get("fb_y/n", "")).upper() == "Y":
        return "facebook_enrichment"
    if str(row.get("website_y/n", "")).upper() == "Y":
        return "website_enrichment"
    return "paid_data_vendor"


def run(df: pd.DataFrame, config: RunConfig, logger: RunLogger) -> pd.DataFrame:
    logger.set_phase("phase6")
    rows = []
    for _, row in df.iterrows():
        addr_found = str(row.get("address_found", "")).upper()
        lob_del = str(row.get("lob_deliverability", ""))
        conf = int(row.get("address_confidence_%") or 0) if str(row.get("address_confidence_%", "")).isdigit() else 0

        reason = None
        if addr_found == "N":
            reason = "address_not_found_after_free_ladder"
        elif lob_del == "undeliverable":
            reason = "lob_undeliverable"
        elif addr_found == "UNCERTAIN" and conf < 50:
            reason = "address_uncertain_low_confidence"

        if not reason:
            continue

        rows.append(
            {
                "license_number": row.get("license_number"),
                "owner_name_raw": row.get("owner_name_raw"),
                "business_name_raw": row.get("business_name_raw"),
                "county": row.get("county"),
                "fb_url": row.get("fb_url", ""),
                "website_url": row.get("website_url", ""),
                "address_attempt_log": row.get("address_attempt_log", ""),
                "lob_result": lob_del,
                "recommended_paid_source": _recommended_source(row),
                "escalation_reason": reason,
            }
        )

    out_path = config.output_path.parent / f"escalation_queue_{config.run_id}.csv"
    if rows:
        out_df = pd.DataFrame(rows)
        write_csv(out_df, out_path)
        logger.info(f"Escalation queue: {len(rows)} records -> {out_path}")
    else:
        logger.info("Escalation queue: 0 records")

    return df
