"""Phase 0 — Universe Filter (incremental batches)."""

from __future__ import annotations

import pandas as pd

from core.batch import eligible_candidates, select_batch, slots_available
from core.config import RunConfig
from core.csv_io import ensure_columns, read_csv, update_record, write_csv
from core.logger import RunLogger
from core.utils import is_blank, now_iso


def run(df: pd.DataFrame | None, config: RunConfig, logger: RunLogger) -> pd.DataFrame:
    logger.set_phase("phase0")

    input_df = read_csv(config.input_path)
    if config.output_path.exists():
        out_df = read_csv(config.output_path)
        logger.info(f"Resuming from existing output ({len(out_df)} rows)")
    else:
        out_df = pd.DataFrame()
        logger.info(f"Starting fresh from input ({len(input_df)} rows)")

    slots = slots_available(config, current_output_count=len(out_df))
    candidates = eligible_candidates(config)

    if slots > 0 and not candidates.empty:
        new_rows = select_batch(candidates, slots, config).copy()
        if out_df.empty:
            out_df = new_rows.reset_index(drop=True)
        else:
            out_df = ensure_columns(out_df, list(new_rows.columns))
            new_rows = ensure_columns(new_rows, list(out_df.columns))
            out_df = pd.concat([out_df, new_rows], ignore_index=True)
        logger.info(f"Admitted {len(new_rows)} new record(s) this batch")
        if not new_rows.empty and "license_subtype" in new_rows.columns:
            counts = new_rows["license_subtype"].astype(str).str.upper().value_counts().to_dict()
            logger.info(f"License subtype mix: {counts}")
    elif slots <= 0:
        logger.info("max_records cap reached — no new records admitted")
    else:
        logger.info("No new eligible candidates in input")

    out_df = ensure_columns(out_df, ["run_id", "batch1_excluded", "phase0_timestamp"])
    ts = now_iso()
    for i in range(len(out_df)):
        lic = str(out_df.at[i, "license_number"])
        if is_blank(out_df.at[i, "phase0_timestamp"]):
            out_df = update_record(
                out_df,
                lic,
                {
                    "run_id": config.run_id,
                    "batch1_excluded": "false",
                    "phase0_timestamp": ts,
                },
                phase=0,
            )
            logger.info("Phase 0 processed", license_number=lic)

    write_csv(out_df, config.output_path)
    logger.info(f"Phase 0 complete: {len(out_df)} records in working file")
    return out_df
