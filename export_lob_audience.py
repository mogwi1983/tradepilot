"""Export Lob-ready CSV files for target cohorts."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.supabase_client import get_supabase_config
from core.system_logger import get_system_logger
import requests


def fetch_cohort_from_supabase(cohort: str) -> list[dict]:
    cfg = get_supabase_config()
    if not cfg:
        return []

    url = f"{cfg['url']}/rest/v1/contractors_v2"
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
    }
    params = {
        "select": "license_number,owner_name,business_name,address_line1,address_city,address_state,address_zip,cohort",
        "address_line1": "not.is.null",
        "order": "license_number.asc",
    }
    if cohort != "all":
        params["cohort"] = f"eq.{cohort}"

    resp = requests.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code == 200:
        return resp.json()
    return []


def export_lob_csv(cohort: str = "cohort_1", output_dir: Path | None = None) -> Path | None:
    logger = get_system_logger()
    output_dir = output_dir or (ROOT / "exports")
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = fetch_cohort_from_supabase(cohort)
    if not rows:
        # Fallback to working CSV if Supabase has no data yet
        working_csv = ROOT / "data" / "output" / "working_batch.csv"
        if working_csv.exists():
            df_csv = pd.read_csv(working_csv, dtype=str).fillna("")
            if cohort != "all":
                df_csv = df_csv[df_csv["cohort"] == cohort]
            df_csv = df_csv[df_csv["address_line1"] != ""]
            rows = df_csv.to_dict(orient="records")

    if not rows:
        logger.warning("Export", f"No records with valid addresses found for cohort: {cohort}")
        return None

    lob_rows = []
    for r in rows:
        lob_rows.append({
            "name": str(r.get("owner_name", "")).strip()[:40],
            "company": str(r.get("business_name", "")).strip()[:40],
            "address_line1": str(r.get("address_line1", "")).strip()[:64],
            "address_city": str(r.get("address_city", "")).strip()[:200],
            "address_state": str(r.get("address_state", "TX")).strip()[:2],
            "address_zip": str(r.get("address_zip", "")).strip(),
            "metadata_license_number": str(r.get("license_number", "")).strip(),
            "metadata_cohort": str(r.get("cohort", "")).strip(),
        })

    df_out = pd.DataFrame(lob_rows)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"lob_{cohort}_{ts}.csv"
    df_out.to_csv(out_path, index=False, encoding="utf-8")

    logger.info("Export", f"Exported {len(df_out)} records to Lob CSV: {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Lob-ready CSV audience file")
    parser.add_argument("--cohort", default="cohort_1", choices=["cohort_1", "cohort_2", "cohort_3", "all"])
    args = parser.parse_args()

    out_file = export_lob_csv(args.cohort)
    if out_file:
        print(f"Success: Exported {args.cohort} to {out_file}")


if __name__ == "__main__":
    main()
