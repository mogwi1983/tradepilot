"""Compute pipeline progress stats from the working CSV."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from core.config import RunConfig
from core.utils import is_blank


PHASE_DEFS: list[dict[str, Any]] = [
    {"id": 0, "name": "Filter", "column": "phase0_timestamp", "kind": "timestamp"},
    {"id": 1, "name": "Website", "column": "website_y/n", "kind": "yn"},
    {"id": 2, "name": "Facebook", "column": "fb_y/n", "kind": "yn"},
    {"id": 3, "name": "Other presence", "column": "phase3_timestamp", "kind": "timestamp"},
    {"id": 4, "name": "Address", "column": "address_found", "kind": "yn"},
    {"id": 5, "name": "Lob verify", "column": "lob_deliverability", "kind": "lob"},
    {"id": 6, "name": "Escalation", "column": "phase6_exported", "kind": "flag"},
    {"id": 7, "name": "Classify", "column": "batch_assignment", "kind": "category"},
    {"id": 8, "name": "QA", "column": "phase8_complete", "kind": "flag"},
]


def _count_processed(df: pd.DataFrame, column: str, kind: str) -> int:
    if column not in df.columns:
        return 0
    count = 0
    for value in df[column]:
        if kind == "flag":
            if str(value).lower() in ("true", "1", "yes", "y"):
                count += 1
            continue
        if not is_blank(value):
            count += 1
    return count


def _value_counts(df: pd.DataFrame, column: str) -> dict[str, int]:
    if column not in df.columns:
        return {}
    counts: dict[str, int] = {}
    for value in df[column]:
        if is_blank(value):
            key = "pending"
        else:
            key = str(value).strip()
        counts[key] = counts.get(key, 0) + 1
    return counts


def _yn_counts(df: pd.DataFrame, column: str) -> dict[str, int]:
    raw = _value_counts(df, column)
    return {
        "Y": raw.get("Y", 0) + raw.get("y", 0),
        "N": raw.get("N", 0) + raw.get("n", 0),
        "UNCERTAIN": raw.get("UNCERTAIN", 0) + raw.get("uncertain", 0),
        "pending": raw.get("pending", 0),
    }


def _bool_count(df: pd.DataFrame, column: str, truthy: str = "true") -> int:
    if column not in df.columns:
        return 0
    n = 0
    for value in df[column]:
        if is_blank(value):
            continue
        if str(value).lower() in (truthy, "1", "yes"):
            n += 1
    return n


def _load_lob_budget(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"total_free_verifications": 0, "used": 0, "remaining": 0, "last_updated": None}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _record_summaries(df: pd.DataFrame, limit: int = 50) -> list[dict[str, Any]]:
    cols = [
        "license_number",
        "county",
        "business_name_raw",
        "owner_name_raw",
        "website_y/n",
        "fb_y/n",
        "address_found",
        "lob_deliverability",
        "batch_assignment",
        "lob_ready",
        "confidence_tier",
        "exclusion_reason",
        "unresolved_reason",
    ]
    available = [c for c in cols if c in df.columns]
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        entry = {c: ("" if is_blank(row.get(c)) else str(row.get(c))) for c in available}
        entry["status"] = _record_status(row)
        rows.append(entry)

    priority = {"failed": 0, "warning": 1, "success": 2, "pending": 3}
    rows.sort(key=lambda r: (priority.get(r["status"], 9), r.get("license_number", "")))
    return rows[:limit]


def _record_status(row: pd.Series) -> str:
    if str(row.get("lob_ready", "")).lower() == "true":
        return "success"
    if str(row.get("batch_assignment", "")) in ("batch_1", "batch_2"):
        return "success"
    if str(row.get("batch_assignment", "")) == "excluded":
        return "warning"
    if str(row.get("lob_deliverability", "")) == "undeliverable":
        return "failed"
    if str(row.get("address_found", "")).upper() == "N" and not is_blank(row.get("phase4_timestamp", row.get("address_attempt_log"))):
        return "failed"
    if not is_blank(row.get("batch_assignment")):
        return "warning"
    if not is_blank(row.get("website_y/n")) or not is_blank(row.get("fb_y/n")):
        return "pending"
    return "pending"


def compute_dashboard_stats(config: RunConfig) -> dict[str, Any]:
    output_path = config.output_path
    if not output_path.exists():
        return {
            "error": f"Output file not found: {output_path}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    df = pd.read_csv(output_path)
    total = len(df)

    phases = []
    for phase in PHASE_DEFS:
        col = phase["column"]
        if phase["id"] == 3 and col not in df.columns:
            col = "gbp_found" if "gbp_found" in df.columns else "other_presence_y/n"
        if phase["id"] == 5 and col not in df.columns:
            col = "lob_verified"
        processed = _count_processed(df, col, phase["kind"])
        phases.append(
            {
                "id": phase["id"],
                "name": phase["name"],
                "column": col,
                "processed": processed,
                "total": total,
                "pct": round(100 * processed / total, 1) if total else 0,
            }
        )

    website = _yn_counts(df, "website_y/n")
    facebook = _yn_counts(df, "fb_y/n")
    address = _yn_counts(df, "address_found")

    lob_raw = _value_counts(df, "lob_deliverability") if "lob_deliverability" in df.columns else {}
    lob = {
        "deliverable": lob_raw.get("deliverable", 0),
        "undeliverable": lob_raw.get("undeliverable", 0),
        "not_called": lob_raw.get("not_called", 0) + lob_raw.get("pending", 0),
        "other": sum(
            v
            for k, v in lob_raw.items()
            if k not in ("deliverable", "undeliverable", "not_called", "pending")
        ),
    }

    batch_raw = _value_counts(df, "batch_assignment")
    batch = {
        "batch_1": batch_raw.get("batch_1", 0),
        "batch_2": batch_raw.get("batch_2", 0),
        "excluded": batch_raw.get("excluded", 0),
        "unresolved": batch_raw.get("unresolved", 0),
        "pending": batch_raw.get("pending", 0),
    }

    tiers_raw = _value_counts(df, "confidence_tier")
    tiers = {
        "A": tiers_raw.get("A", 0),
        "B": tiers_raw.get("B", 0),
        "C": tiers_raw.get("C", 0),
        "pending": tiers_raw.get("pending", 0),
    }

    mail_ready = _bool_count(df, "lob_ready")
    address_found_y = address.get("Y", 0)
    deliverable = lob.get("deliverable", 0)

    funnel = [
        {"stage": "Total records", "count": total},
        {"stage": "Address found", "count": address_found_y},
        {"stage": "Lob deliverable", "count": deliverable},
        {"stage": "Mail ready", "count": mail_ready},
        {"stage": "Batch 1 assigned", "count": batch.get("batch_1", 0)},
    ]

    counties: dict[str, int] = {}
    if "county" in df.columns:
        for value in df["county"]:
            key = str(value).strip().title() if not is_blank(value) else "Unknown"
            counties[key] = counties.get(key, 0) + 1

    success_rate = round(100 * mail_ready / total, 1) if total else 0
    address_rate = round(100 * address_found_y / total, 1) if total else 0

    qa_report = config.run_log_dir / f"qa_report_{config.run_id}.md"
    run_log = config.run_log_dir / "run.log"

    return {
        "run_id": config.run_id,
        "output_file": str(output_path),
        "total_records": total,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "success_rate": success_rate,
        "address_rate": address_rate,
        "phases": phases,
        "website": website,
        "facebook": facebook,
        "address": address,
        "lob": lob,
        "batch": batch,
        "confidence_tiers": tiers,
        "funnel": funnel,
        "counties": counties,
        "lob_budget": _load_lob_budget(config.lob_budget_path),
        "records": _record_summaries(df),
        "artifacts": {
            "qa_report_exists": qa_report.exists(),
            "qa_report_path": str(qa_report),
            "run_log_exists": run_log.exists(),
            "run_log_path": str(run_log),
        },
    }
