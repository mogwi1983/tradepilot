"""Pull sequential batches from Supabase, run free phases, apply address gate + tuning."""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.batch_gate import batch_address_stats, batch_address_summary_for_tuning
from core.config import load_run_config
from core.csv_io import ensure_columns, phase_complete, read_csv, register_post_write_hook, write_csv
from core.env import load_env as _load_env
from core.logger import get_logger
from core.pipeline_state import load_pipeline_state, record_batch_completion
from core.supabase_sync import (
    db_rows_to_dataframe,
    fetch_next_batch_sequential,
    upsert_dataframe,
)
from core.tuning import load_tuning, save_tuning, suggest_tuning_change
from core.utils import is_blank
from dashboard.job_status import finish_job, start_job, write_job
from phases import (
    phase1_website,
    phase2_facebook,
    phase3_other_presence,
    phase4_address_resolve,
    phase7_classify,
)

DEFAULT_DB_PHASES = [1, 2, 3, 4, 7]
PHASE_MODULES = {
    1: phase1_website,
    2: phase2_facebook,
    3: phase3_other_presence,
    4: phase4_address_resolve,
    7: phase7_classify,
}

_batch_licenses: list[str] = []
_current_phase: int | None = None


def _process_phases(config) -> list[int]:
    return config.db_process_phases or DEFAULT_DB_PHASES


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


def _run_one_batch(config, logger, limit: int, batch_number: int) -> pd.DataFrame | None:
    global _batch_licenses, _current_phase

    rows = fetch_next_batch_sequential(limit=limit)
    if not rows:
        return None

    df = db_rows_to_dataframe(rows)
    if df.empty or "license_number" not in df.columns:
        raise RuntimeError("Supabase rows could not be converted to CSV format")

    _batch_licenses = df["license_number"].astype(str).str.strip().tolist()
    write_job(
        pulled=len(_batch_licenses),
        total_in_batch=len(_batch_licenses),
        licenses=_batch_licenses,
        message=f"Batch {batch_number}: {len(_batch_licenses)} contractor(s) — starting pipeline",
    )
    logger.info(f"Batch {batch_number}: pulled {len(_batch_licenses)} contractor(s)")

    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(df, config.output_path)

    phases = _process_phases(config)
    for phase_num in phases:
        module = PHASE_MODULES.get(phase_num)
        if module is None:
            continue
        _current_phase = phase_num
        write_job(
            current_phase=phase_num,
            message=f"Batch {batch_number} — phase {phase_num}…",
        )
        logger.info(f"=== Batch {batch_number} / Phase {phase_num} ===")
        df = read_csv(config.output_path)
        df = ensure_columns(df, list(df.columns))
        df = module.run(df, config, logger)
        write_csv(df, config.output_path)

    _current_phase = None
    return read_csv(config.output_path)


def main() -> int:
    global _batch_licenses, _current_phase

    _load_env()
    parser = argparse.ArgumentParser(description="Sequential Supabase batch processor")
    parser.add_argument("--config", default="run_config.json")
    parser.add_argument("--limit", type=int, default=None, help="Batch size override")
    parser.add_argument(
        "--max-batches",
        type=int,
        default=0,
        help="Max batches this run (0 = unlimited until queue empty)",
    )
    parser.add_argument(
        "--single-batch",
        action="store_true",
        help="Process one batch only (no auto-continue)",
    )
    args = parser.parse_args()

    config = load_run_config(args.config)
    logger = get_logger(config.run_id, config.run_log_dir)
    batch_size = args.limit or config.batch_size
    gate_pct = config.address_gate_pct
    auto_continue = config.auto_continue_batches and not args.single_batch
    max_batches = args.max_batches if args.max_batches > 0 else (1 if args.single_batch else 0)

    state = load_pipeline_state(config.pipeline_state_path)
    start_batch = int(state.get("batches_completed", 0)) + 1

    start_job(
        "db_pull_process",
        f"Sequential batch processing (size {batch_size}, gate {gate_pct}%)…",
    )
    register_post_write_hook(_post_write_sync)

    batches_run = 0
    try:
        while True:
            if max_batches > 0 and batches_run >= max_batches:
                logger.info(f"Reached max_batches={max_batches}")
                break

            batch_number = start_batch + batches_run
            df = _run_one_batch(config, logger, batch_size, batch_number)
            if df is None:
                finish_job("completed", "All contractors processed — queue empty")
                logger.info("No unprocessed contractors remaining")
                return 0

            stats = batch_address_stats(df)
            rate = float(stats["address_rate_pct"])
            tuning_applied = False
            tuning_summary = ""

            if rate < gate_pct:
                logger.info(
                    f"Batch {batch_number} address rate {rate}% < {gate_pct}% — requesting DeepSeek tuning"
                )
                write_job(message=f"Address rate {rate}% — DeepSeek tuning…")
                summary = batch_address_summary_for_tuning(df)
                summary["batch_number"] = batch_number
                current_tuning = load_tuning(config.pipeline_tuning_path)
                try:
                    updated_tuning, tuning_summary = suggest_tuning_change(
                        summary, current_tuning, logger
                    )
                    save_tuning(config.pipeline_tuning_path, updated_tuning)
                    tuning_applied = True
                    logger.info(f"Tuning applied: {tuning_summary}")
                except Exception as exc:
                    logger.error(f"DeepSeek tuning failed: {exc}")
                    tuning_summary = f"tuning failed: {exc}"
            else:
                logger.info(
                    f"Batch {batch_number} address rate {rate}% >= {gate_pct}% — proceeding"
                )

            record_batch_completion(
                config.pipeline_state_path,
                batch_number=batch_number,
                batch_size=int(stats["batch_size"]),
                addresses_found=int(stats["addresses_found"]),
                address_rate_pct=rate,
                tuning_applied=tuning_applied,
                tuning_summary=tuning_summary,
                license_range=_batch_licenses,
            )

            upsert_dataframe(df, license_numbers=_batch_licenses)
            batches_run += 1
            msg = (
                f"Batch {batch_number} done: {stats['addresses_found']}/{stats['batch_size']} "
                f"addresses ({rate}%)"
            )
            if tuning_applied:
                msg += f" · tuned: {tuning_summary[:80]}"
            write_job(message=msg)

            if not auto_continue:
                finish_job("completed", msg + " — single-batch mode")
                return 0

            _batch_licenses = []

        finish_job(
            "completed",
            f"Completed {batches_run} batch(es) this run",
        )
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
