"""Phase 7 — Batch Classification."""

from __future__ import annotations

import pandas as pd

from core.config import RunConfig
from core.csv_io import ensure_columns, phase_complete, update_record, write_csv
from core.logger import RunLogger
from core.utils import is_blank, normalize_county, now_iso


def _score(row: pd.Series) -> int:
    score = 0
    src_count = int(row.get("address_source_count") or 0) if str(row.get("address_source_count", "")).isdigit() else 0
    if src_count == 1:
        score += 15
    elif src_count == 2:
        score += 25
    elif src_count >= 3:
        score += 35

    if str(row.get("address_conflict_detected", "")).lower() != "true" and src_count >= 2:
        score += 5
    if row.get("address_raw") and row.get("address_source"):
        score += 5
    if str(row.get("address_type_guess", "")).lower() == "residential":
        score -= 5

    lob_del = str(row.get("lob_deliverability", ""))
    if lob_del == "deliverable":
        score += 25
    elif lob_del == "deliverable_missing_unit":
        score += 10
    if str(row.get("lob_vacancy", "")) == "vacant":
        score -= 15

    batch = str(row.get("batch_assignment", ""))
    assignment_preview = _classify(row)
    if assignment_preview in ("batch_1", "batch_2"):
        score += 20
    elif assignment_preview == "unresolved":
        score += 5

    if str(row.get("address_conflict_detected", "")).lower() == "true" and assignment_preview == "unresolved":
        score -= 10
    if str(row.get("website_y/n", "")).upper() == "Y":
        score -= 20
    fb_conf = int(row.get("fb_confidence_%") or 0) if str(row.get("fb_confidence_%", "")).isdigit() else 0
    if str(row.get("fb_y/n", "")).upper() == "Y" and fb_conf < 60:
        score -= 5

    return max(0, min(100, score))


def _tier(score: int) -> str:
    if score >= 75:
        return "A"
    if score >= 50:
        return "B"
    return "C"


def _classify(row: pd.Series, target_counties: set[str] | None = None) -> tuple[str, str, str]:
    """Return (batch_assignment, exclusion_reason, unresolved_reason)."""
    county = normalize_county(row.get("county", ""))
    if target_counties and county not in target_counties:
        return "excluded", "out_of_geography", ""

    web = str(row.get("website_y/n", "")).upper()
    fb = str(row.get("fb_y/n", "")).upper()

    if web == "Y":
        return "excluded", "has_website", ""
    if web == "UNCERTAIN" or fb == "UNCERTAIN":
        return "unresolved", "", "uncertain_presence_detection"
    if web == "N" and fb == "N":
        return "batch_1", "", ""
    if web == "N" and fb == "Y":
        return "batch_2", "", ""
    return "unresolved", "", "incomplete_presence_data"


def _lob_ready(row: pd.Series) -> bool:
    return (
        str(row.get("lob_deliverability", "")) == "deliverable"
        and str(row.get("lob_vacancy", "")) != "vacant"
    )


def run(df: pd.DataFrame, config: RunConfig, logger: RunLogger) -> pd.DataFrame:
    logger.set_phase("phase7")
    df = ensure_columns(
        df,
        [
            "batch_assignment",
            "lob_ready",
            "exclusion_reason",
            "unresolved_reason",
            "confidence_score",
            "confidence_tier",
            "phase7_timestamp",
        ],
    )

    target = {normalize_county(c) for c in config.target_counties}
    ts = now_iso()

    for _, row in df.iterrows():
        lic = str(row["license_number"])
        if phase_complete(row, 7):
            continue
        if config.resume_from_record and lic != str(config.resume_from_record):
            continue

        assignment, excl, unres = _classify(row, target)
        # Recompute score with assignment context
        row_copy = row.copy()
        row_copy["batch_assignment"] = assignment
        score = _score(row_copy)
        tier = _tier(score)

        df = update_record(
            df,
            lic,
            {
                "batch_assignment": assignment,
                "lob_ready": str(_lob_ready(row)).lower(),
                "exclusion_reason": excl,
                "unresolved_reason": unres,
                "confidence_score": str(score),
                "confidence_tier": tier,
                "phase7_timestamp": ts,
            },
            phase=7,
        )
        write_csv(df, config.output_path)
        logger.info(f"batch={assignment} tier={tier} score={score}", license_number=lic)

    return df
