"""
Load and validate run_config.json.

Spec: CURSOR-BOOTSTRAP.md Step 2 — core/config.py
Fields: see RunConfig in ARCHITECTURE.md § Run Configuration
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class RunConfig:
    """Typed view of run_config.json. Implement validation in load_run_config()."""

    run_id: str
    input_file: str
    output_file: str
    target_counties: list[str]
    license_subtypes: list[str]
    max_records: int
    county_priority: list[str]
    lob_budget_file: str
    phases_to_run: list[int]
    start_phase: int
    resume_from_record: str | None


def load_run_config(path: str | Path = "run_config.json") -> RunConfig:
    """Load run_config.json, validate required fields, confirm input_file exists."""
    raise NotImplementedError("Implement per CURSOR-BOOTSTRAP.md — validate input_file exists at startup")
