"""Incremental batch helpers — admit next N records from input into output."""

from __future__ import annotations

import pandas as pd

from core.config import RunConfig
from core.csv_io import read_csv
from core.utils import is_blank, normalize_county


def row_eligible(
    row: pd.Series,
    *,
    target_counties: set[str],
    subtypes: set[str],
) -> bool:
    county = normalize_county(row.get("county", ""))
    subtype = str(row.get("license_subtype", "")).upper().strip()

    if county not in target_counties:
        return False
    if subtype and subtype not in subtypes:
        return False
    if "license_status" in row.index:
        status = str(row.get("license_status", "")).upper()
        if status and status != "ACTIVE":
            return False
    return True


def filter_settings(config: RunConfig) -> tuple[set[str], set[str], dict[str, int]]:
    target_counties = {normalize_county(c) for c in config.target_counties}
    subtypes = {s.upper() for s in config.license_subtypes}
    priority = {normalize_county(c): i for i, c in enumerate(config.county_priority)}
    return target_counties, subtypes, priority


def admitted_license_numbers(config: RunConfig) -> set[str]:
    if not config.output_path.exists():
        return set()
    df = read_csv(config.output_path)
    if df.empty or "license_number" not in df.columns:
        return set()
    return set(df["license_number"].astype(str).str.strip())


def eligible_candidates(config: RunConfig) -> pd.DataFrame:
    """Input rows matching filters that are not yet in the working output file."""
    target_counties, subtypes, priority = filter_settings(config)
    admitted = admitted_license_numbers(config)
    input_df = read_csv(config.input_path)

    rows: list[pd.Series] = []
    for _, row in input_df.iterrows():
        lic = str(row["license_number"]).strip()
        if lic in admitted:
            continue
        if not row_eligible(row, target_counties=target_counties, subtypes=subtypes):
            continue
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    out["_county_rank"] = out["county"].map(lambda c: priority.get(normalize_county(c), 999))
    return out.sort_values("_county_rank").drop(columns="_county_rank")


def slots_available(config: RunConfig, *, current_output_count: int | None = None) -> int:
    batch_size = config.batch_size if config.batch_size > 0 else 100
    if current_output_count is None:
        current_output_count = len(admitted_license_numbers(config))
    if config.max_records > 0:
        return max(0, min(batch_size, config.max_records - current_output_count))
    return batch_size


def batch_meta(config: RunConfig) -> dict:
    output_count = len(admitted_license_numbers(config))
    candidates = eligible_candidates(config)
    remaining_eligible = len(candidates)
    slots = slots_available(config, current_output_count=output_count)
    batch_size = config.batch_size if config.batch_size > 0 else 100

    next_batch_count = min(slots, remaining_eligible) if slots > 0 else 0

    return {
        "batch_size": batch_size,
        "total_in_output": output_count,
        "remaining_eligible": remaining_eligible,
        "max_records": config.max_records,
        "next_batch_count": next_batch_count,
        "can_run_more": next_batch_count > 0,
        "at_cap": config.max_records > 0 and output_count >= config.max_records,
    }
