"""Pull unprocessed contractors from Supabase and run the enrichment pipeline."""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_run_config
from core.csv_io import ensure_columns, phase_complete, read_csv, register_post_write_hook, write_csv
from core.env import load_env as _load_env
from core.logger import get_logger
from core.supabase_sync import (
    db_rows_to_dataframe,
    fetch_unprocessed_contractors,
    upsert_dataframe,
)
from core.utils import is_blank
from dashboard.job_status import finish_job, start_job, write_job
from phases import (
    phase1_website,
    phase2_facebook,
    phase3_other_presence,
    phase4_address_resolve,
    phase5_lob_verify,
    phase7_classify,
)

PROCESS_PHASES = [1, 2, 3, 4, 5, 7]
PHASE_MODULES = {
    1: phase1_website,
    2: phase2_facebook,
    3: phase3_other_presence,
    4: phase4_address_resolve,
    5: phase5_lob_verify,
    7: phase7_classify,
}

_batch_licenses: list[str] = []
_current_phase: int | None = None


def _count_phase_done(df: pd.DataFrame, phase: int) -> int:
    done = 0
    for _, row in df.iterrows():
        if phase_complete(row, phase):
            done += 1
        elif phase == 1 and not is_blank(row.get("website_y/n")):
            done += 1
    return done


def _post_write_sync(df: pd.DataFrame, _path: Path) -> None:
    if not _batch_licenses:
        return
    upsert_dataframe(df, license_numbers=_batch_licenses)
    if _current_phase is not None:
        done = _count_phase_done(df, _current_phase)
        write_job(
            message=(
                f"Phase {_current_phase}: {done}/{len(_batch_licenses)} records "
                f"saved to DB"
            ),
        )


def main() -> int:
    global _batch_licenses, _current_phase

    _load_env()
    parser = argparse.ArgumentParser(description="Pull contractors from Supabase and process")
    parser.add_argument("--config", default="run_config.json")
    parser.add_argument("--limit", type=int, default=50, help="Records to pull (default: 50)")
    args = parser.parse_args()

    config = load_run_config(args.config)
    logger = get_logger(config.run_id, config.run_log_dir)

    start_job(
        "db_pull_process",
        f"Pulling up to {args.limit} contractor(s) from Supabase…",
    )
    register_post_write_hook(_post_write_sync)

    try:
        rows = fetch_unprocessed_contractors(limit=args.limit)
        if not rows:
            finish_job("completed", "No unprocessed contractors found in Supabase")
            logger.info("No unprocessed contractors in Supabase")
            return 0

        df = db_rows_to_dataframe(rows)
        if df.empty or "license_number" not in df.columns:
            finish_job("failed", "Supabase rows could not be converted to CSV format")
            return 1

        _batch_licenses = df["license_number"].astype(str).str.strip().tolist()
        write_job(
            pulled=len(_batch_licenses),
            total_in_batch=len(_batch_licenses),
            licenses=_batch_licenses,
            message=f"Pulled {len(_batch_licenses)} contractor(s) — starting pipeline",
        )
        logger.info(f"Pulled {len(_batch_licenses)} contractor(s) from Supabase")

        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        write_csv(df, config.output_path)
        logger.info(f"Working CSV set to {len(df)} record(s): {config.output_path}")

        for phase_num in PROCESS_PHASES:
            _current_phase = phase_num
            module = PHASE_MODULES[phase_num]
            write_job(
                current_phase=phase_num,
                message=f"Running phase {phase_num} on {len(_batch_licenses)} record(s)…",
            )
            logger.info(f"=== Phase {phase_num} (DB batch) ===")

            df = read_csv(config.output_path)
            df = ensure_columns(df, list(df.columns))
            df = module.run(df, config, logger)
            write_csv(df, config.output_path)

        _current_phase = None
        finish_job(
            "completed",
            f"Processed {len(_batch_licenses)} contractor(s) — synced to Supabase",
        )
        logger.info("DB batch pipeline complete")
        return 0

    except Exception as exc:
        logger.error(f"DB batch failed:\n{traceback.format_exc()}")
        finish_job("failed", str(exc))
        return 1
    finally:
        _current_phase = None
        _batch_licenses = []
        register_post_write_hook(None)


if __name__ == "__main__":
    raise SystemExit(main())
