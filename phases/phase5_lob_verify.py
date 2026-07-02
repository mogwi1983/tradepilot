"""
Phase 5 — Lob Address Verification (budget-gated).

Spec: ARCHITECTURE.md § Phase 5
Owns: lob_verified, lob_deliverability, lob_standardized_address, lob_address_type, lob_vacancy, lob_verification_timestamp
Only process address_found = Y. Halt when lob_budget.json remaining = 0.
"""

from __future__ import annotations

import pandas as pd

from core.config import RunConfig


def run(df: pd.DataFrame, config: RunConfig, logger) -> pd.DataFrame:
    raise NotImplementedError
