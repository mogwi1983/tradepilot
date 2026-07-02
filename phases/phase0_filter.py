"""
Phase 0 — Universe Filter.

Spec: ARCHITECTURE.md § Phase 0
Owns: run_id, phase0_timestamp, batch1_excluded
"""

from __future__ import annotations

import pandas as pd

from core.config import RunConfig


def run(df: pd.DataFrame, config: RunConfig, logger) -> pd.DataFrame:
    raise NotImplementedError
