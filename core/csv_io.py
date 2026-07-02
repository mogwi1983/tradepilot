"""Safe CSV I/O with column ownership and resumability."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

# Source + name-variation columns — read-only for phases 1+
READONLY_COLUMNS = {
    "license_number",
    "license_subtype",
    "county",
    "owner_name_raw",
    "business_name_raw",
    "owner_var_1",
    "owner_var_2",
    "biz_var_1",
    "biz_var_2",
    "biz_var_3",
    "biz_var_4",
    "combo_var_1",
    "combo_var_2",
    "combo_var_3",
    "combo_var_4",
}

PHASE_COLUMNS: dict[int, list[str]] = {
    0: ["run_id", "batch1_excluded", "phase0_timestamp"],
    1: [
        "website_y/n",
        "website_url",
        "website_confidence_%",
        "website_search_notes",
        "phase1_timestamp",
    ],
    2: [
        "fb_y/n",
        "fb_url",
        "fb_page_name",
        "fb_last_post_date",
        "fb_confidence_%",
        "fb_search_notes",
        "phase2_timestamp",
    ],
    3: [
        "gbp_found",
        "gbp_claimed",
        "gbp_review_count",
        "yelp_found",
        "angi_found",
        "other_presence_types",
        "other_presence_notes",
        "phase3_timestamp",
    ],
    4: [
        "address_found",
        "address_raw",
        "address_source",
        "address_source_url",
        "address_confidence_%",
        "address_type_guess",
        "address_is_pobox",
        "address_attempt_log",
        "address_source_count",
        "address_conflict_detected",
        "phase4_timestamp",
    ],
    5: [
        "lob_verified",
        "lob_deliverability",
        "lob_standardized_address",
        "lob_address_type",
        "lob_vacancy",
        "lob_verification_timestamp",
    ],
    7: [
        "batch_assignment",
        "lob_ready",
        "exclusion_reason",
        "unresolved_reason",
        "confidence_score",
        "confidence_tier",
        "phase7_timestamp",
    ],
}

PHASE_TIMESTAMP: dict[int, str] = {
    0: "phase0_timestamp",
    1: "phase1_timestamp",
    2: "phase2_timestamp",
    3: "phase3_timestamp",
    4: "phase4_timestamp",
    5: "lob_verification_timestamp",
    7: "phase7_timestamp",
}


class ColumnOwnershipError(Exception):
    """Raised when a phase writes to columns it does not own."""


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return str(value).strip() == ""


def read_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if "license_number" in df.columns:
        df["license_number"] = df["license_number"].astype(str).str.strip()
    return df


def write_csv(df: pd.DataFrame, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".csv", dir=path.parent)
    os.close(fd)
    try:
        df.to_csv(tmp, index=False)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def update_record(
    df: pd.DataFrame,
    license_number: str,
    updates: dict[str, Any],
    *,
    phase: int,
    force: bool = False,
) -> pd.DataFrame:
    owned = set(PHASE_COLUMNS.get(phase, []))
    for col in updates:
        if col in READONLY_COLUMNS:
            raise ColumnOwnershipError(f"Phase {phase} cannot write read-only column: {col}")
        if owned and col not in owned:
            raise ColumnOwnershipError(f"Phase {phase} cannot write column: {col}")

    lic = str(license_number).strip()
    mask = df["license_number"].astype(str).str.strip() == lic
    if not mask.any():
        raise KeyError(f"license_number not found: {lic}")

    idx = df.index[mask][0]
    for col, value in updates.items():
        if col not in df.columns:
            df[col] = ""
        current = df.at[idx, col]
        if not force and not _is_blank(current):
            continue
        df.at[idx, col] = "" if value is None else str(value)
    return df


def phase_complete(row: pd.Series, phase: int) -> bool:
    ts_col = PHASE_TIMESTAMP.get(phase)
    if ts_col and ts_col in row.index:
        return not _is_blank(row.get(ts_col))
    return False


def ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df
