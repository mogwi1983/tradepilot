"""Shared job state for long-running dashboard batch operations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
JOB_PATH = ROOT / "data" / "dashboard_job.json"

DEFAULT_JOB: dict[str, Any] = {
    "state": "idle",
    "kind": "",
    "message": "",
    "started_at": None,
    "finished_at": None,
    "pulled": 0,
    "total_in_batch": 0,
    "current_phase": None,
    "licenses": [],
}


def read_job() -> dict[str, Any]:
    if not JOB_PATH.exists():
        return dict(DEFAULT_JOB)
    try:
        data = json.loads(JOB_PATH.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_JOB)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_JOB)


def write_job(**updates: Any) -> dict[str, Any]:
    job = read_job()
    job.update(updates)
    JOB_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOB_PATH.write_text(json.dumps(job, indent=2), encoding="utf-8")
    return job


def start_job(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    return write_job(
        state="running",
        kind=kind,
        message=message,
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        pulled=0,
        total_in_batch=0,
        current_phase=None,
        licenses=[],
        **extra,
    )


def finish_job(state: str, message: str) -> dict[str, Any]:
    return write_job(
        state=state,
        message=message,
        finished_at=datetime.now(timezone.utc).isoformat(),
        current_phase=None,
    )


def reconcile_job(process_running: bool) -> dict[str, Any]:
    """Mark stale running jobs failed when the subprocess has exited."""
    job = read_job()
    if job.get("state") == "running" and not process_running:
        return finish_job("failed", job.get("message") or "Process exited unexpectedly")
    return job
