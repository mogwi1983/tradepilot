"""Phase 0 — Universe Filter."""

from __future__ import annotations

import pandas as pd

from core.config import RunConfig
from core.csv_io import ensure_columns, update_record, write_csv
from core.logger import RunLogger
from core.utils import is_blank, normalize_county, now_iso


def run(df: pd.DataFrame | None, config: RunConfig, logger: RunLogger) -> pd.DataFrame:
    logger.set_phase("phase0")
    from core.csv_io import read_csv

    if config.output_path.exists():
        df = read_csv(config.output_path)
        logger.info(f"Resuming from existing output ({len(df)} rows)")
    else:
        df = read_csv(config.input_path)
        logger.info(f"Loaded input ({len(df)} rows)")

    df = ensure_columns(df, ["run_id", "batch1_excluded", "phase0_timestamp"])

    target_counties = {normalize_county(c) for c in config.target_counties}
    subtypes = {s.upper() for s in config.license_subtypes}
    priority = {normalize_county(c): i for i, c in enumerate(config.county_priority)}

    filtered_rows = []
    for _, row in df.iterrows():
        if not is_blank(row.get("phase0_timestamp")):
            filtered_rows.append(row)
            continue

        county = normalize_county(row.get("county", ""))
        subtype = str(row.get("license_subtype", "")).upper().strip()

        if county not in target_counties:
            continue
        if subtype and subtype not in subtypes:
            continue
        if "license_status" in row.index:
            status = str(row.get("license_status", "")).upper()
            if status and status != "ACTIVE":
                continue

        filtered_rows.append(row)

    if not filtered_rows:
        out = df.iloc[0:0].copy()
    else:
        out = pd.DataFrame(filtered_rows)
        out["_county_rank"] = out["county"].map(lambda c: priority.get(normalize_county(c), 999))
        out = out.sort_values("_county_rank").drop(columns="_county_rank")
        if config.max_records > 0:
            out = out.head(config.max_records)

    out = out.reset_index(drop=True)
    ts = now_iso()
    for i in range(len(out)):
        lic = str(out.at[i, "license_number"])
        if is_blank(out.at[i, "phase0_timestamp"]):
            out = update_record(
                out,
                lic,
                {
                    "run_id": config.run_id,
                    "batch1_excluded": "false",
                    "phase0_timestamp": ts,
                },
                phase=0,
            )
            logger.info("Phase 0 processed", license_number=lic)

    write_csv(out, config.output_path)
    logger.info(f"Phase 0 complete: {len(out)} records in working file")
    return out
