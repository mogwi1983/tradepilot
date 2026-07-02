"""
Phase 3 — Other Presence (GBP, Yelp, Angi, etc.; min 4 searches).

Spec: ARCHITECTURE.md § Phase 3
Owns: gbp_*, yelp_found, angi_found, other_presence_*, phase3_timestamp
"""

from __future__ import annotations

import pandas as pd

from core.config import RunConfig


def run(df: pd.DataFrame, config: RunConfig, logger) -> pd.DataFrame:
    raise NotImplementedError
