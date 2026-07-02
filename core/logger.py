"""Structured logging to console and runs/{run_id}/run.log."""

from __future__ import annotations

import logging
from pathlib import Path


class RunLogger:
    def __init__(self, run_id: str, log_dir: Path) -> None:
        self.run_id = run_id
        self.phase = "main"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "run.log"

        self._logger = logging.getLogger(f"tradepilot.{run_id}")
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()
        self._logger.propagate = False

        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")

        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        self._logger.addHandler(fh)

        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        self._logger.addHandler(ch)

    def set_phase(self, phase: str) -> None:
        self.phase = phase

    def _msg(self, license_number: str, message: str) -> str:
        lic = license_number or "-"
        return f"{self.phase} | {lic} | {message}"

    def debug(self, message: str, *, license_number: str = "") -> None:
        self._logger.debug(self._msg(license_number, message))

    def info(self, message: str, *, license_number: str = "") -> None:
        self._logger.info(self._msg(license_number, message))

    def warning(self, message: str, *, license_number: str = "") -> None:
        self._logger.warning(self._msg(license_number, message))

    def error(self, message: str, *, license_number: str = "") -> None:
        self._logger.error(self._msg(license_number, message))


def get_logger(run_id: str, log_dir: Path | None = None) -> RunLogger:
    if log_dir is None:
        log_dir = Path("runs") / run_id
    return RunLogger(run_id, log_dir)
