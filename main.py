"""
TradePilot pipeline runner.

Spec: CURSOR-BOOTSTRAP.md Step 4 — main.py

Usage (after implementation):
  python main.py
  python main.py --start-phase 4
  python main.py --phases 1 2 3
  python main.py --record ABC123456

Agent: implement phase dispatch, CLI args, and graceful interruption handling.
Read AGENTS.md before modifying this file.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TradePilot lead intelligence pipeline")
    parser.add_argument("--start-phase", type=int, default=None, help="Resume from phase N")
    parser.add_argument("--phases", type=int, nargs="+", default=None, help="Run only these phases")
    parser.add_argument("--record", type=str, default=None, help="Process single license_number (testing)")
    args = parser.parse_args(argv)

    print(
        "TradePilot scaffold: pipeline not yet implemented.\n"
        "See AGENTS.md and CURSOR-BOOTSTRAP.md for build instructions.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
