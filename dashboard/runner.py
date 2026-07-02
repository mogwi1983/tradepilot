"""Background pipeline runner for dashboard batch triggers."""

from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from core.config import load_run_config
from core.csv_io import read_csv

ROOT = Path(__file__).resolve().parent.parent


class JobState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class BatchJob:
    state: JobState = JobState.IDLE
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    records_before: int = 0
    records_after: int = 0
    batch_size: int = 0
    message: str = ""
    _process: subprocess.Popen[bytes] | None = field(default=None, repr=False)


_lock = threading.Lock()
_job = BatchJob()


def _python_executable() -> Path:
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return venv_python
    return Path(sys.executable)


def _output_count(config_path: Path) -> int:
    config = load_run_config(config_path)
    if not config.output_path.exists():
        return 0
    return len(read_csv(config.output_path))


def get_job_status() -> dict:
    with _lock:
        return {
            "state": _job.state.value,
            "started_at": _job.started_at,
            "finished_at": _job.finished_at,
            "exit_code": _job.exit_code,
            "records_before": _job.records_before,
            "records_after": _job.records_after,
            "records_added": max(0, _job.records_after - _job.records_before),
            "batch_size": _job.batch_size,
            "message": _job.message,
        }


def start_batch(config_path: Path, batch_size: int | None = None) -> tuple[bool, str]:
    global _job

    with _lock:
        if _job.state == JobState.RUNNING:
            return False, "A batch is already running. Wait for it to finish."

    config = load_run_config(config_path)
    size = batch_size if batch_size is not None else config.batch_size
    before = _output_count(config_path)

    cmd = [
        str(_python_executable()),
        str(ROOT / "main.py"),
        "--config",
        str(config_path),
        "--batch-size",
        str(size),
    ]

    def _worker() -> None:
        global _job
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        with _lock:
            _job._process = proc
            _job.state = JobState.RUNNING
            _job.started_at = datetime.now(timezone.utc).isoformat()
            _job.records_before = before
            _job.batch_size = size
            _job.message = f"Running batch of up to {size} record(s)"

        output, _ = proc.communicate()
        after = _output_count(config_path)
        tail = "\n".join(output.strip().splitlines()[-5:]) if output else ""

        with _lock:
            _job.exit_code = proc.returncode
            _job.finished_at = datetime.now(timezone.utc).isoformat()
            _job.records_after = after
            _job._process = None
            if proc.returncode == 0:
                added = after - before
                _job.state = JobState.COMPLETED
                _job.message = f"Batch complete — {added} record(s) added ({before} → {after})"
            else:
                _job.state = JobState.FAILED
                _job.message = f"Pipeline failed (exit {proc.returncode}). {tail}"

    threading.Thread(target=_worker, daemon=True).start()
    return True, f"Started batch of up to {size} record(s)"


def reset_job_if_idle() -> None:
    """Clear completed/failed status so the UI can show idle again."""
    global _job
    with _lock:
        if _job.state in (JobState.COMPLETED, JobState.FAILED):
            _job = BatchJob()
