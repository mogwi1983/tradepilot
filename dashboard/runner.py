"""Subprocess runner for batch phase execution — launched by server.py."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_run_config
from core.csv_io import read_csv, write_csv
from core.env import load_env as _load_env
from core.logger import get_logger
from phases import (
    phase0_filter,
    phase1_website,
    phase2_facebook,
    phase3_other_presence,
    phase4_address_resolve,
    phase5_lob_verify,
    phase6_escalation,
    phase7_classify,
    phase8_qa,
)

PHASE_MODULES = {
    0: phase0_filter,
    1: phase1_website,
    2: phase2_facebook,
    3: phase3_other_presence,
    4: phase4_address_resolve,
    5: phase5_lob_verify,
    6: phase6_escalation,
    7: phase7_classify,
    8: phase8_qa,
}


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="run_config.json")
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--start-record", type=str, default=None)
    parser.add_argument("--batch-size", type=int, default=0,
                        help="Max records to process (0 = unlimited)")
    args = parser.parse_args()

    config = load_run_config(args.config)
    logger = get_logger(config.run_id, config.run_log_dir)

    phase_num = args.phase
    module = PHASE_MODULES.get(phase_num)
    if not module:
        print(f"Unknown phase: {phase_num}", file=sys.stderr)
        return 1

    if not config.output_path.exists():
        print(f"Output file missing: {config.output_path}", file=sys.stderr)
        return 1

    df = read_csv(config.output_path)

    if args.start_record:
        config.resume_from_record = args.start_record

    # Apply batch size: limit DataFrame to only N pending records + already-completed ones
    if args.batch_size > 0 and phase_num != 0:
        from core.csv_io import phase_complete
        completed_mask = df.apply(lambda row: phase_complete(row, phase_num), axis=1)
        completed_df = df[completed_mask]
        pending_df = df[~completed_mask]
        batch_df = pending_df.head(args.batch_size)
        df = pd.concat([completed_df, batch_df], ignore_index=True)
        logger.info(
            f"Batch limit: {len(batch_df)} of {len(pending_df)} pending records "
            f"({len(completed_df)} already done)"
        )

    logger.info(f"=== Batch Phase {phase_num} ===")
    try:
        df = module.run(df, config, logger)
        if phase_num not in (6, 8):
            write_csv(df, config.output_path)
    except KeyboardInterrupt:
        logger.warning("Interrupted")
        return 130
    except Exception:
        import traceback
        logger.error(f"Phase {phase_num} failed:\n{traceback.format_exc()}")
        return 1

    logger.info("Phase complete")

    # Auto-sync to Supabase after each phase batch
    if config.output_path.exists():
        from core.supabase_sync import upsert_csv

        try:
            sync_result = upsert_csv(config.output_path)
            if sync_result.get("status") == "ok":
                logger.info(f"Supabase sync: {sync_result.get('inserted', 0)} rows upserted")
            elif sync_result.get("status") == "skipped":
                logger.debug(f"Supabase sync skipped: {sync_result.get('reason', 'no DB')}")
            else:
                logger.warning(f"Supabase sync issue: {sync_result}")
        except Exception as sync_exc:
            logger.warning(f"Supabase auto-sync failed (non-fatal): {sync_exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
