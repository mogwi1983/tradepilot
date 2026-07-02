"""
Phase 1 — Website Detection (min 5 distinct searches per record).

Spec: ARCHITECTURE.md § Phase 1
Owns: website_y/n, website_url, website_confidence_%, website_search_notes, phase1_timestamp
"""

from __future__ import annotations

import pandas as pd

from core.config import RunConfig


def run(df: pd.DataFrame, config: RunConfig, logger) -> pd.DataFrame:
    raise NotImplementedError
