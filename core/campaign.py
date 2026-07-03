"""Campaign progress — 3 cohorts × 200 Lob-verified mailing addresses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from core.config import RunConfig
from core.utils import is_blank

DEFAULT_MANIFEST = Path(__file__).resolve().parent.parent / "data" / "source" / "cohort_manifest.json"
DEFAULT_TARGETS = {"cohort_1": 200, "cohort_2": 200, "cohort_3": 200}
COHORT_ORDER = ("cohort_1", "cohort_2", "cohort_3")

# CSV column names (working file) — Supabase rows are normalized before use.
CSV_COL_MAP = {
    "website_yn": "website_y/n",
    "fb_yn": "fb_y/n",
    "address_raw": "address",
}


def _col(df: pd.DataFrame, name: str) -> str:
    if name in df.columns:
        return name
    return CSV_COL_MAP.get(name, name)


def load_cohort_manifest(path: Path | None = None) -> dict[str, Any]:
    manifest_path = path or DEFAULT_MANIFEST
    if not manifest_path.exists():
        return {
            "campaign": "initial_600_mailers",
            "description": "Three cohorts × 200 Lob-verified addresses",
            "cohorts": {
                cid: {"label": cid, "rules": "", "mail_target": target, "overflow_wave": "wave_2"}
                for cid, target in DEFAULT_TARGETS.items()
            },
        }
    with manifest_path.open(encoding="utf-8") as f:
        return json.load(f)


def cohort_targets(config: RunConfig, manifest: dict[str, Any] | None = None) -> dict[str, int]:
    if config.cohort_mail_targets:
        return {k: int(v) for k, v in config.cohort_mail_targets.items()}
    manifest = manifest or load_cohort_manifest(config.cohort_manifest_path)
    out: dict[str, int] = {}
    for cid in COHORT_ORDER:
        entry = manifest.get("cohorts", {}).get(cid, {})
        out[cid] = int(entry.get("mail_target", DEFAULT_TARGETS.get(cid, 200)))
    return out


def _lob_ready_series(df: pd.DataFrame) -> pd.Series:
    col = "lob_ready"
    if col not in df.columns:
        return pd.Series([False] * len(df))
    return df[col].astype(str).str.lower().isin(("true", "1", "yes"))


def _cohort_series(df: pd.DataFrame) -> pd.Series:
    if "cohort" not in df.columns:
        return pd.Series([""] * len(df))
    return df["cohort"].astype(str).str.strip()


def _mail_wave_series(df: pd.DataFrame) -> pd.Series:
    if "mail_wave" not in df.columns:
        return pd.Series([""] * len(df))
    return df["mail_wave"].astype(str).str.strip()


def _address_found_series(df: pd.DataFrame) -> pd.Series:
    col = "address_found"
    if col not in df.columns:
        return pd.Series([False] * len(df))
    return df[col].astype(str).str.upper().str.strip() == "Y"


def compute_cohort_breakdown(df: pd.DataFrame, targets: dict[str, int], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-cohort counts for dashboard cards."""
    ready = _lob_ready_series(df)
    cohorts = _cohort_series(df)
    waves = _mail_wave_series(df)
    addr_found = _address_found_series(df)
    labels = {cid: manifest.get("cohorts", {}).get(cid, {}).get("label", cid) for cid in COHORT_ORDER}
    rules = {cid: manifest.get("cohorts", {}).get(cid, {}).get("rules", "") for cid in COHORT_ORDER}

    cards: list[dict[str, Any]] = []
    for cid in COHORT_ORDER:
        target = targets.get(cid, 200)
        mask = cohorts == cid
        assigned = int(mask.sum())
        addresses_found = int((mask & addr_found).sum())
        mail_ready = int((mask & ready).sum())
        wave_1 = int((mask & ready & (waves == "wave_1")).sum())
        wave_2 = int((mask & ready & (waves == "wave_2")).sum())
        pending_address = int((mask & ~addr_found).sum())
        still_needed = max(0, target - addresses_found)

        cards.append(
            {
                "id": cid,
                "label": labels.get(cid, cid),
                "rules": rules.get(cid, ""),
                "target": target,
                "assigned": assigned,
                "addresses_found": addresses_found,
                "mail_ready": mail_ready,
                "wave_1_addresses": wave_1,
                "wave_2_overflow": wave_2,
                "pending_address": pending_address,
                "still_needed": still_needed,
                "pct_of_target": round(100 * addresses_found / target, 1) if target else 0,
                "target_met": addresses_found >= target,
            }
        )
    return cards


def compute_campaign_summary(
    df: pd.DataFrame,
    *,
    targets: dict[str, int],
    manifest: dict[str, Any],
    universe_total: int,
    universe_processed: int | None = None,
    source: str = "csv",
) -> dict[str, Any]:
    """Aggregate campaign metrics for the dashboard."""
    cohort_cards = compute_cohort_breakdown(df, targets, manifest)
    total_goal = sum(targets.get(c, 200) for c in COHORT_ORDER)
    addresses_total = sum(c["addresses_found"] for c in cohort_cards)
    wave_1_total = sum(c["wave_1_addresses"] for c in cohort_cards)
    mail_ready_total = sum(c["mail_ready"] for c in cohort_cards)

    if universe_processed is None:
        if "phase7_timestamp" in df.columns:
            universe_processed = int(df["phase7_timestamp"].apply(lambda v: not is_blank(v)).sum())
        else:
            universe_processed = len(df)

    return {
        "name": manifest.get("campaign", "initial_600_mailers"),
        "description": manifest.get("description", ""),
        "source": source,
        "total_goal_addresses": total_goal,
        "addresses_found_total": addresses_total,
        "wave_1_addresses": wave_1_total,
        "mail_ready_total": mail_ready_total,
        "pct_complete": round(100 * addresses_total / total_goal, 1) if total_goal else 0,
        "still_needed_total": max(0, total_goal - addresses_total),
        "targets": targets,
        "cohorts": cohort_cards,
        "universe": {
            "total_eligible": universe_total,
            "processed_through_pipeline": universe_processed,
            "remaining_to_process": max(0, universe_total - universe_processed),
        },
    }


def normalize_supabase_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Map Supabase contractor rows to campaign-friendly column names."""
    if not rows:
        return pd.DataFrame()
    records: list[dict[str, str]] = []
    for row in rows:
        rec: dict[str, str] = {}
        for key, val in row.items():
            if key in ("created_at", "updated_at"):
                continue
            csv_key = CSV_COL_MAP.get(key, key)
            if val is None:
                rec[csv_key] = ""
            elif isinstance(val, bool):
                rec[csv_key] = "true" if val else "false"
            else:
                rec[csv_key] = str(val).strip()
        records.append(rec)
    return pd.DataFrame(records).fillna("")
