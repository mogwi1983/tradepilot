"""
Phase 4 — Address Resolution (free sources only; no Lob).

Spec: ARCHITECTURE.md § Phase 4
Owns: address_* columns, phase4_timestamp
Priority: website → facebook → gmaps → gsearch
"""

from __future__ import annotations

import pandas as pd

from core.config import RunConfig


def run(df: pd.DataFrame, config: RunConfig, logger) -> pd.DataFrame:
    raise NotImplementedError
