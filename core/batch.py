"""Incremental batch helpers — admit next N records from input into output."""

from __future__ import annotations

import pandas as pd

from core.config import RunConfig
from core.csv_io import read_csv
from core.utils import normalize_county


def row_eligible(
    row: pd.Series,
    *,
    target_counties: set[str],
    subtypes: set[str],
    skip_county_validation: bool = False,
) -> bool:
    county = normalize_county(row.get("county", ""))
    subtype = str(row.get("license_subtype", "")).upper().strip()

    if not skip_county_validation and county not in target_counties:
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


def _with_county_rank(df: pd.DataFrame, priority: dict[str, int]) -> pd.DataFrame:
    out = df.copy()
    out["_county_rank"] = out["county"].map(lambda c: priority.get(normalize_county(c), 999))
    return out.sort_values("_county_rank")


def _subtype_quotas(
    candidates: pd.DataFrame,
    subtypes: list[str],
    n: int,
) -> dict[str, int]:
    """Allocate n slots across license subtypes proportional to the candidate pool."""
    if candidates.empty or n <= 0:
        return {}

    pool = candidates.copy()
    pool["_subtype"] = pool["license_subtype"].astype(str).str.upper().str.strip()
    ordered_subtypes = [s.upper() for s in subtypes]
    counts = {st: int((pool["_subtype"] == st).sum()) for st in ordered_subtypes if (pool["_subtype"] == st).any()}
    if not counts:
        return {}

    total = sum(counts.values())
    raw = {st: n * counts[st] / total for st in counts}
    quotas = {st: int(raw[st]) for st in counts}
    remainder = n - sum(quotas.values())
    for st in sorted(counts, key=lambda s: raw[s] - quotas[s], reverse=True):
        if remainder <= 0:
            break
        quotas[st] += 1
        remainder -= 1

    # Cap by availability; redistribute any shortfall to strata with spare rows.
    shortfall = 0
    for st in ordered_subtypes:
        if st not in quotas:
            continue
        if quotas[st] > counts[st]:
            shortfall += quotas[st] - counts[st]
            quotas[st] = counts[st]

    if shortfall > 0:
        spare = [
            st
            for st in ordered_subtypes
            if st in quotas and quotas[st] < counts[st]
        ]
        idx = 0
        while shortfall > 0 and spare:
            st = spare[idx % len(spare)]
            if quotas[st] < counts[st]:
                quotas[st] += 1
                shortfall -= 1
            idx += 1
            if idx > len(spare) * (n + 1):
                break

    return quotas


def stratified_select(
    candidates: pd.DataFrame,
    n: int,
    *,
    subtypes: list[str],
    priority: dict[str, int],
) -> pd.DataFrame:
    """Pick up to n rows with proportional license_subtype representation."""
    if candidates.empty or n <= 0:
        return pd.DataFrame()

    ranked = _with_county_rank(candidates, priority)
    ranked["_subtype"] = ranked["license_subtype"].astype(str).str.upper().str.strip()
    quotas = _subtype_quotas(ranked, subtypes, n)

    picked: list[pd.DataFrame] = []
    for st, quota in quotas.items():
        if quota <= 0:
            continue
        stratum = ranked[ranked["_subtype"] == st].head(quota)
        picked.append(stratum)

    if not picked:
        return pd.DataFrame()

    out = pd.concat(picked, ignore_index=True).head(n)
    return out.drop(columns=["_county_rank", "_subtype"], errors="ignore")


def select_batch(candidates: pd.DataFrame, slots: int, config: RunConfig) -> pd.DataFrame:
    """Select the next batch from eligible candidates."""
    if candidates.empty or slots <= 0:
        return pd.DataFrame()

    _, _, priority = filter_settings(config)
    if config.stratify_by_license_subtype:
        return stratified_select(
            candidates,
            slots,
            subtypes=config.license_subtypes,
            priority=priority,
        )

    ranked = _with_county_rank(candidates, priority)
    return ranked.head(slots).drop(columns=["_county_rank"], errors="ignore")


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
        if not row_eligible(
            row,
            target_counties=target_counties,
            subtypes=subtypes,
            skip_county_validation=config.skip_county_validation,
        ):
            continue
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    return _with_county_rank(out, priority).drop(columns="_county_rank")


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
