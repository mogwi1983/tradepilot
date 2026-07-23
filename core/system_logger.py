"""Root system logger writing structured Markdown entries to SYSTEM_LOG.md and console stdout."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT_DIR / "SYSTEM_LOG.md"


class SystemLogger:
    def __init__(self, log_path: Path | None = None) -> None:
        self.log_path = log_path or LOG_FILE
        self._ensure_log_file()

    def _ensure_log_file(self) -> None:
        if not self.log_path.exists():
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            header = (
                "# TradePilot System Execution & Audit Log\n\n"
                "This log tracks pipeline execution events, system performance, "
                "site throttling, address validation results, gaps, security notes, and areas for improvement.\n\n"
                "---\n\n"
                "| Timestamp (UTC) | Level | Component | License # | Message | Details |\n"
                "|---|---|---|---|---|---|\n"
            )
            self.log_path.write_text(header, encoding="utf-8")

    def _log(
        self,
        level: str,
        component: str,
        message: str,
        license_number: str = "N/A",
        details: str = "",
    ) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        clean_msg = message.replace("|", "/").replace("\n", " ")
        clean_details = (details or "").replace("|", "/").replace("\n", " ")
        lic = str(license_number).strip() or "N/A"

        # Format markdown table line
        line = f"| {ts} | {level:5} | {component:12} | {lic:9} | {clean_msg} | {clean_details} |\n"

        # Console print
        print(f"[{ts}] [{level:5}] [{component}] [{lic}] {clean_msg}")

        # Append to SYSTEM_LOG.md
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as exc:
            print(f"Failed to append to log file {self.log_path}: {exc}", file=sys.stderr)

    def info(self, component: str, message: str, license_number: str = "N/A", details: str = "") -> None:
        self._log("INFO", component, message, license_number, details)

    def warning(self, component: str, message: str, license_number: str = "N/A", details: str = "") -> None:
        self._log("WARN", component, message, license_number, details)

    def error(self, component: str, message: str, license_number: str = "N/A", details: str = "") -> None:
        self._log("ERROR", component, message, license_number, details)

    def debug(self, component: str, message: str, license_number: str = "N/A", details: str = "") -> None:
        if os.getenv("DEBUG", "").lower() in ("1", "true", "yes"):
            self._log("DEBUG", component, message, license_number, details)


_global_logger: SystemLogger | None = None


def get_system_logger() -> SystemLogger:
    global _global_logger
    if _global_logger is None:
        _global_logger = SystemLogger()
    return _global_logger
