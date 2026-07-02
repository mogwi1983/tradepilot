"""
Safe CSV I/O with column ownership and resumability.

Spec: CURSOR-BOOTSTRAP.md Step 2 — core/csv_io.py
Column ownership: ARCHITECTURE.md § Column Ownership Rules
Schema: DATA-SCHEMA.md
"""

from __future__ import annotations

from typing import Any

import pandas as pd


class ColumnOwnershipError(Exception):
    """Raised when a phase writes to columns it does not own."""


# Map phase number → owned column names. Populate when implementing.
PHASE_COLUMNS: dict[int, list[str]] = {}


def read_csv(path: str) -> pd.DataFrame:
    raise NotImplementedError


def write_csv(df: pd.DataFrame, path: str) -> None:
    """Atomic write: temp file then rename."""
    raise NotImplementedError


def update_record(
    df: pd.DataFrame,
    license_number: str,
    updates: dict[str, Any],
    *,
    phase: int,
    force: bool = False,
) -> pd.DataFrame:
    """
    Update one row by license_number. Enforce PHASE_COLUMNS[phase].
    Skip keys that already have non-blank values unless force=True.
    """
    raise NotImplementedError
