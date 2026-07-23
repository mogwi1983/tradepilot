"""TradePilot v2 main pipeline runner."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from core.config import load_run_config
from core.csv_io import read_csv, write_csv
from core.env import load_env
from core.supabase_client import upsert_contractor
from core.system_logger import get_system_logger
from phases import (
    phase1_website,
    phase2_facebook,
    phase4_address_resolve,
    phase7_classify,
)

PHASE_MODULES = {
    1: phase1_website,
    2: phase2_facebook,
    4: phase4_address_resolve,
    7: phase7_classify,
}


def prepare_working_df(source_csv: Path, output_csv: Path, limit: int | None = None) -> pd.DataFrame:
    logger = get_system_logger()

    if output_csv.exists():
        logger.info("Main", f"Loading existing working CSV: {output_csv}")
        df = read_csv(output_csv)
    else:
        logger.info("Main", f"Initializing working CSV from source: {source_csv}")
        from scripts.seed_supabase import parse_owner_name
        src_df = pd.read_csv(source_csv, dtype=str).fillna("")

        rows = []
        for _, r in src_df.iterrows():
            lic = str(r.get("LICENSE NUMBER", "")).strip()
            if not lic:
                continue
            rows.append({
                "license_number": lic,
                "license_type": str(r.get("LICENSE TYPE", "")).strip(),
                "license_subtype": str(r.get("LICENSE SUBTYPE", "")).strip(),
                "license_expiration_date": str(r.get("LICENSE EXPIRATION DATE", "")).strip(),
                "county": str(r.get("COUNTY", "")).strip(),
                "business_county": str(r.get("BUSINESS COUNTY", "")).strip(),
                "owner_name": parse_owner_name(r.get("NAME", "")),
                "business_name": str(r.get("BUSINESS NAME", "")).strip(),
            })

        df = pd.DataFrame(rows)
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        write_csv(df, output_csv)

    if limit and limit > 0:
        logger.info("Main", f"Limiting processing run to first {limit} records")
        df = df.head(limit).copy()

    return df


def sync_row_to_supabase(row: pd.Series) -> None:
    """Upsert current record state to Supabase contractors_v2 table."""
    data = row.to_dict()
    # Mark status
    data["pipeline_status"] = "complete" if data.get("cohort") and data.get("cohort") != "unresolved" else "pending"
    upsert_contractor(data)


def main(argv: list[str] | None = None) -> int:
    load_env()
    logger = get_system_logger()

    parser = argparse.ArgumentParser(description="TradePilot v2 lead intelligence pipeline")
    parser.add_argument("--config", default="run_config.json", help="Path to run config JSON")
    parser.add_argument("--limit", type=int, default=None, help="Limit processing to first N records")
    args = parser.parse_args(argv)

    try:
        config = load_run_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Main", f"Config error: {exc}")
        return 1

    limit_count = args.limit or config.batch_size
    df = prepare_working_df(config.input_path, config.output_path, limit=limit_count)

    logger.info("Main", f"=== Starting TradePilot v2 run: {config.run_id} ({len(df)} records) ===")

    phases = config.phases_to_run

    for phase_num in phases:
        module = PHASE_MODULES.get(phase_num)
        if not module:
            logger.warning("Main", f"Unknown phase module: {phase_num}")
            continue

        logger.info("Main", f"--- Running Phase {phase_num} ---")
        try:
            df = module.run(df, config)
            write_csv(df, config.output_path)

            # Sync progress to Supabase after phase completion
            for _, r in df.iterrows():
                sync_row_to_supabase(r)

        except KeyboardInterrupt:
            logger.warning("Main", "Run interrupted — state saved to working CSV")
            return 130
        except Exception as exc:
            logger.error("Main", f"Phase {phase_num} failed with error: {exc}")
            return 1

    logger.info("Main", "=== TradePilot v2 pipeline run complete ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
