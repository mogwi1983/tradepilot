"""
Structured logging to console and runs/{run_id}/run.log.

Spec: CURSOR-BOOTSTRAP.md Step 2 — core/logger.py
Format: timestamp | level | phase | license_number | message
"""

from __future__ import annotations

import logging
from pathlib import Path


def get_logger(run_id: str, log_dir: Path | None = None) -> logging.Logger:
    """Return a logger writing to runs/{run_id}/run.log and stderr."""
    raise NotImplementedError
