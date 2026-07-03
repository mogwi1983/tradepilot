"""Compute pipeline progress stats from the working CSV and campaign universe."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from core.batch import batch_meta, universe_meta
from core.campaign import (
    COHORT_ORDER,
    compute_campaign_summary,
    cohort_targets,
    load_cohort_manifest,
    normalize_supabase_rows,
)
from core.config import RunConfig
from core.pipeline_state import load_pipeline_state
from core.supabase_sync import fetch_campaign_view, fetch_contractors_for_campaign
from core.tuning import load_tuning
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


def _record_summaries(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    cols = [
        "license_number",
        "county",
        "business_name_raw",
        "owner_name_raw",
        "website_y/n",
        "fb_y/n",
        "address_found",
        "lob_deliverability",
        "cohort",
        "mail_wave",
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
    if limit is not None:
        return rows[:limit]
    return rows


def _record_status(row: pd.Series) -> str:
    if str(row.get("address_found", "")).upper().strip() == "Y":
        return "success"
    if str(row.get("mail_wave", "")) == "wave_1" and str(row.get("lob_ready", "")).lower() == "true":
        return "success"
    if str(row.get("mail_wave", "")) == "wave_2" and str(row.get("lob_ready", "")).lower() == "true":
        return "warning"
    if str(row.get("cohort", "")) in COHORT_ORDER and str(row.get("lob_ready", "")).lower() == "true":
        return "warning"
    if str(row.get("cohort", "")) == "excluded":
        return "warning"
    if str(row.get("lob_deliverability", "")) == "undeliverable":
        return "failed"
    if str(row.get("address_found", "")).upper() == "N" and not is_blank(
        row.get("phase4_timestamp", row.get("address_attempt_log"))
    ):
        return "failed"
    if not is_blank(row.get("cohort")):
        return "pending"
    if not is_blank(row.get("website_y/n")) or not is_blank(row.get("fb_y/n")):
        return "pending"
    return "pending"


def _campaign_from_supabase(
    config: RunConfig,
    manifest: dict[str, Any],
    targets: dict[str, int],
    universe_total: int,
) -> dict[str, Any] | None:
    try:
        view_rows = fetch_campaign_view()
        if view_rows is not None:
            # Reconstruct a minimal dataframe from view + universe summary endpoint
            rows = fetch_contractors_for_campaign()
            if rows:
                df = normalize_supabase_rows(rows)
                processed = int(df["phase7_timestamp"].apply(lambda v: not is_blank(v)).sum()) if "phase7_timestamp" in df.columns else 0
                return compute_campaign_summary(
                    df,
                    targets=targets,
                    manifest=manifest,
                    universe_total=len(rows) or universe_total,
                    universe_processed=processed,
                    source="supabase",
                )
        rows = fetch_contractors_for_campaign()
        if not rows:
            return None
        df = normalize_supabase_rows(rows)
        processed = int(df["phase7_timestamp"].apply(lambda v: not is_blank(v)).sum()) if "phase7_timestamp" in df.columns else 0
        return compute_campaign_summary(
            df,
            targets=targets,
            manifest=manifest,
            universe_total=len(rows) or universe_total,
            universe_processed=processed,
            source="supabase",
        )
    except Exception:
        return None


def _empty_campaign_payload(manifest: dict[str, Any], targets: dict[str, int], universe_total: int) -> dict[str, Any]:
    return compute_campaign_summary(
        pd.DataFrame(),
        targets=targets,
        manifest=manifest,
        universe_total=universe_total,
        universe_processed=0,
        source="none",
    )


def _stats_shell(
    config: RunConfig,
    manifest: dict[str, Any],
    targets: dict[str, int],
    universe: dict[str, int],
    meta: dict[str, Any],
    job: dict[str, Any] | None,
) -> dict[str, Any]:
    total_goal = sum(targets.get(c, 200) for c in COHORT_ORDER)
    return {
        "run_id": config.run_id,
        "output_file": str(config.output_path),
        "total_records": 0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "success_rate": 0,
        "address_rate": 0,
        "processing_summary": {
            "in_working_file": 0,
            "website_done": 0,
            "facebook_done": 0,
            "address_done": 0,
            "lob_called": 0,
            "classified": 0,
            "mail_ready": 0,
            "pending_mail_ready": 0,
        },
        "campaign": _empty_campaign_payload(manifest, targets, universe["total_eligible"]),
        "universe": universe,
        "phases": [],
        "website": {"Y": 0, "N": 0, "UNCERTAIN": 0, "pending": 0},
        "facebook": {"Y": 0, "N": 0, "UNCERTAIN": 0, "pending": 0},
        "address": {"Y": 0, "N": 0, "UNCERTAIN": 0, "pending": 0},
        "lob": {"deliverable": 0, "undeliverable": 0, "not_called": 0, "other": 0},
        "batch": {"batch_1": 0, "batch_2": 0, "pending": 0, "excluded": 0, "unresolved": 0},
        "cohorts": {c: 0 for c in (*COHORT_ORDER, "excluded", "unresolved", "pending")},
        "waves": {"wave_1": 0, "wave_2": 0, "pending": 0, "ineligible": 0},
        "confidence_tiers": {"A": 0, "B": 0, "C": 0, "pending": 0},
        "funnel": [
            {"stage": "Universe eligible", "count": universe["total_eligible"]},
            {"stage": "Wave-1 addresses (goal)", "count": 0, "goal": total_goal},
            {"stage": "Mail ready (all waves)", "count": 0},
            {"stage": "Current batch in file", "count": 0},
        ],
        "counties": {},
        "lob_budget": _load_lob_budget(config.lob_budget_path),
        "records": [],
        "batch_progress": meta,
        "job": job or {"state": "idle"},
        "artifacts": {
            "qa_report_exists": False,
            "qa_report_path": str(config.run_log_dir / f"qa_report_{config.run_id}.md"),
            "run_log_exists": False,
            "run_log_path": str(config.run_log_dir / "run.log"),
        },
    }


def compute_dashboard_stats(config: RunConfig, *, job: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = batch_meta(config)
    manifest = load_cohort_manifest(config.cohort_manifest_path)
    targets = cohort_targets(config, manifest)
    universe = universe_meta(config)
    output_path = config.output_path

    campaign = _campaign_from_supabase(config, manifest, targets, universe["total_eligible"])
    if campaign is None:
        campaign = _empty_campaign_payload(manifest, targets, universe["total_eligible"])

    if not output_path.exists():
        shell = _stats_shell(config, manifest, targets, universe, meta, job)
        shell["campaign"] = campaign
        return shell

    df = pd.read_csv(output_path)
    total = len(df)

    if campaign.get("source") != "supabase":
        batch_processed = int(df["phase7_timestamp"].apply(lambda v: not is_blank(v)).sum()) if "phase7_timestamp" in df.columns else 0
        campaign = compute_campaign_summary(
            df,
            targets=targets,
            manifest=manifest,
            universe_total=universe["total_eligible"],
            universe_processed=batch_processed,
            source="csv_batch",
        )

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
        "pending": batch_raw.get("pending", 0),
        "excluded": batch_raw.get("excluded", 0),
        "unresolved": batch_raw.get("unresolved", 0),
    }

    cohort_raw = _value_counts(df, "cohort") if "cohort" in df.columns else {}
    cohorts = {
        "cohort_1": cohort_raw.get("cohort_1", 0),
        "cohort_2": cohort_raw.get("cohort_2", 0),
        "cohort_3": cohort_raw.get("cohort_3", 0),
        "excluded": cohort_raw.get("excluded", 0),
        "unresolved": cohort_raw.get("unresolved", 0),
        "pending": cohort_raw.get("pending", 0),
    }

    wave_raw = _value_counts(df, "mail_wave") if "mail_wave" in df.columns else {}
    waves = {
        "wave_1": wave_raw.get("wave_1", 0),
        "wave_2": wave_raw.get("wave_2", 0),
        "pending": wave_raw.get("pending", 0),
        "ineligible": wave_raw.get("ineligible", 0),
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

    def _phase_complete_count(yn_map: dict[str, int]) -> int:
        return yn_map.get("Y", 0) + yn_map.get("N", 0) + yn_map.get("UNCERTAIN", 0)

    processing_summary = {
        "in_working_file": total,
        "website_done": _phase_complete_count(website),
        "facebook_done": _phase_complete_count(facebook),
        "address_done": _phase_complete_count(address),
        "lob_called": lob.get("deliverable", 0) + lob.get("undeliverable", 0) + lob.get("other", 0),
        "classified": batch.get("batch_1", 0) + batch.get("batch_2", 0) + batch.get("excluded", 0) + batch.get("unresolved", 0),
        "mail_ready": mail_ready,
        "pending_mail_ready": max(0, total - mail_ready),
    }

    funnel = [
        {"stage": "Universe eligible", "count": universe["total_eligible"]},
        {"stage": "Addresses found (600 goal)", "count": campaign.get("addresses_found_total", 0), "goal": campaign["total_goal_addresses"]},
        {"stage": "Processed through pipeline", "count": campaign.get("universe", {}).get("processed_through_pipeline", 0)},
        {"stage": "Current batch in file", "count": total},
        {"stage": "Address found (batch)", "count": address_found_y},
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
    pipeline_state = load_pipeline_state(config.pipeline_state_path)
    tuning = load_tuning(config.pipeline_tuning_path)

    return {
        "run_id": config.run_id,
        "output_file": str(output_path),
        "total_records": total,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "success_rate": success_rate,
        "address_rate": address_rate,
        "processing_summary": processing_summary,
        "campaign": campaign,
        "universe": universe,
        "phases": phases,
        "website": website,
        "facebook": facebook,
        "address": address,
        "lob": lob,
        "batch": batch,
        "cohorts": cohorts,
        "waves": waves,
        "confidence_tiers": tiers,
        "funnel": funnel,
        "counties": counties,
        "lob_budget": _load_lob_budget(config.lob_budget_path),
        "records": _record_summaries(df),
        "batch_progress": meta,
        "pipeline_state": pipeline_state,
        "address_gate_pct": config.address_gate_pct,
        "tuning_revision": tuning.get("history", [])[-3:],
        "job": job or {"state": "idle"},
        "artifacts": {
            "qa_report_exists": qa_report.exists(),
            "qa_report_path": str(qa_report),
            "run_log_exists": run_log.exists(),
            "run_log_path": str(run_log),
        },
    }
