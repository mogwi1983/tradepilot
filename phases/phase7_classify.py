"""
Phase 7 — Batch Classification + confidence scoring.

Spec: ARCHITECTURE.md § Phase 7, DATA-SCHEMA.md § Confidence Score Rubric
Owns: batch_assignment, lob_ready, exclusion_reason, unresolved_reason, confidence_score, confidence_tier, phase7_timestamp
"""

from __future__ import annotations

import pandas as pd

from core.config import RunConfig


def run(df: pd.DataFrame, config: RunConfig, logger) -> pd.DataFrame:
    raise NotImplementedError
