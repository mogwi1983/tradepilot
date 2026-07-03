"""Read/write pipeline batch state and address-gate history."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_STATE: dict[str, Any] = {
    "batches_completed": 0,
    "total_processed": 0,
    "last_batch_number": 0,
    "last_address_rate_pct": None,
    "last_batch_addresses_found": 0,
    "last_batch_size": 0,
    "tuning_applied_count": 0,
    "batch_history": [],
}


def load_pipeline_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return dict(DEFAULT_STATE)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    out = dict(DEFAULT_STATE)
    out.update(data)
    return out


def save_pipeline_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def record_batch_completion(
    path: Path,
    *,
    batch_number: int,
    batch_size: int,
    addresses_found: int,
    address_rate_pct: float,
    tuning_applied: bool,
    tuning_summary: str = "",
    license_range: list[str] | None = None,
) -> dict[str, Any]:
    state = load_pipeline_state(path)
    entry = {
        "batch_number": batch_number,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "batch_size": batch_size,
        "addresses_found": addresses_found,
        "address_rate_pct": address_rate_pct,
        "tuning_applied": tuning_applied,
        "tuning_summary": tuning_summary,
        "license_first": (license_range or [""])[0],
        "license_last": (license_range or ["", ""])[-1],
    }
    history = list(state.get("batch_history", []))
    history.append(entry)
    state["batch_history"] = history[-50:]
    state["batches_completed"] = int(state.get("batches_completed", 0)) + 1
    state["total_processed"] = int(state.get("total_processed", 0)) + batch_size
    state["last_batch_number"] = batch_number
    state["last_address_rate_pct"] = address_rate_pct
    state["last_batch_addresses_found"] = addresses_found
    state["last_batch_size"] = batch_size
    if tuning_applied:
        state["tuning_applied_count"] = int(state.get("tuning_applied_count", 0)) + 1
    save_pipeline_state(path, state)
    return state
