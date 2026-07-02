"""
Phase 8 — QA Audit.

Spec: ARCHITECTURE.md § Phase 8
Output: runs/{run_id}/qa_report_{run_id}.md
"""

from __future__ import annotations

import pandas as pd

from core.config import RunConfig


def run(df: pd.DataFrame, config: RunConfig, logger) -> pd.DataFrame:
    raise NotImplementedError
