"""Batch address metrics and gate for sequential pipeline."""

from __future__ import annotations

import pandas as pd

from core.utils import is_blank


def mailing_address_found(row: pd.Series) -> bool:
    """Count Y only — includes PO boxes. UNCERTAIN and N do not count."""
    return str(row.get("address_found", "")).upper().strip() == "Y"


def batch_address_stats(df: pd.DataFrame) -> dict[str, float | int]:
    total = len(df)
    if total == 0:
        return {"batch_size": 0, "addresses_found": 0, "address_rate_pct": 0.0}
    found = sum(1 for _, row in df.iterrows() if mailing_address_found(row))
    rate = round(100.0 * found / total, 1)
    return {
        "batch_size": total,
        "addresses_found": found,
        "address_rate_pct": rate,
    }


def batch_address_summary_for_tuning(df: pd.DataFrame) -> dict:
    stats = batch_address_stats(df)
    website_y = sum(1 for _, r in df.iterrows() if str(r.get("website_y/n", "")).upper() == "Y")
    fb_y = sum(1 for _, r in df.iterrows() if str(r.get("fb_y/n", "")).upper() == "Y")
    addr_n = sum(1 for _, r in df.iterrows() if str(r.get("address_found", "")).upper() == "N")
    cohort_counts: dict[str, int] = {}
    for _, r in df.iterrows():
        c = str(r.get("cohort", "")).strip()
        if c:
            cohort_counts[c] = cohort_counts.get(c, 0) + 1
    samples = []
    for _, r in df.iterrows():
        if mailing_address_found(r):
            continue
        samples.append(
            {
                "license_number": str(r.get("license_number", "")),
                "website_y/n": str(r.get("website_y/n", "")),
                "fb_y/n": str(r.get("fb_y/n", "")),
                "address_found": str(r.get("address_found", "")),
                "address_attempt_log": str(r.get("address_attempt_log", ""))[:200],
            }
        )
        if len(samples) >= 8:
            break
    return {
        **stats,
        "website_y_count": website_y,
        "fb_y_count": fb_y,
        "address_n_count": addr_n,
        "cohort_counts": cohort_counts,
        "miss_samples": samples,
    }
