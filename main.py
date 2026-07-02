"""TradePilot pipeline runner."""

from __future__ import annotations

import argparse
import sys
import traceback

from core.config import RunConfig, load_run_config
from core.csv_io import read_csv, write_csv
from core.env import load_env
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


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(description="TradePilot lead intelligence pipeline")
    parser.add_argument("--config", default="run_config.json", help="Path to run config JSON")
    parser.add_argument("--start-phase", type=int, default=None, help="Resume from phase N")
    parser.add_argument("--phases", type=int, nargs="+", default=None, help="Run only these phases")
    parser.add_argument("--record", type=str, default=None, help="Process single license_number (testing)")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Admit and process at most N new records this run (default: run_config batch_size)",
    )
    args = parser.parse_args(argv)

    try:
        config = load_run_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    if args.start_phase is not None:
        config.start_phase = args.start_phase
    if args.record:
        config.resume_from_record = args.record
    if args.batch_size is not None:
        config.batch_size = args.batch_size

    phases = args.phases if args.phases else config.phases_to_run
    phases = [p for p in phases if p >= config.start_phase]

    logger = get_logger(config.run_id, config.run_log_dir)
    logger.info(f"Starting run {config.run_id} phases={phases}")

    df = None
    if 0 in phases:
        try:
            df = PHASE_MODULES[0].run(df, config, logger)
        except Exception:
            logger.error(traceback.format_exc())
            return 1
    else:
        if not config.output_path.exists():
            print(f"Output file missing: {config.output_path}. Run phase 0 first.", file=sys.stderr)
            return 1
        df = read_csv(config.output_path)

    for phase_num in phases:
        if phase_num == 0:
            continue
        module = PHASE_MODULES.get(phase_num)
        if not module:
            logger.warning(f"Unknown phase: {phase_num}")
            continue
        logger.info(f"=== Phase {phase_num} ===")
        try:
            df = module.run(df, config, logger)
            if phase_num not in (6, 8):
                write_csv(df, config.output_path)
        except KeyboardInterrupt:
            logger.warning("Interrupted — CSV state saved after last record")
            return 130
        except Exception:
            logger.error(f"Phase {phase_num} failed:\n{traceback.format_exc()}")
            return 1

    logger.info("Pipeline complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
