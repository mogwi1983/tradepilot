"""Seed contractors_v2 in Supabase from data/source/new_batch.csv."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.supabase_client import bulk_seed_contractors
from core.system_logger import get_system_logger


def parse_owner_name(raw_name: str) -> str:
    """Parse 'LAST, FIRST MIDDLE' format into 'First Last' title case."""
    if not raw_name or str(raw_name).lower() in ("nan", "none"):
        return ""
    text = str(raw_name).strip()
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) >= 2:
        last = parts[0]
        first_mid = parts[1].split()
        first = first_mid[0] if first_mid else ""
        return f"{first} {last}".title()
    return text.title()


def seed_database(csv_path: Path) -> list[dict]:
    logger = get_system_logger()
    logger.info("Seed", f"Reading source CSV: {csv_path}")

    df = pd.read_csv(csv_path, dtype=str).fillna("")
    records = []

    for _, row in df.iterrows():
        lic = str(row.get("LICENSE NUMBER", "")).strip()
        if not lic:
            continue
        raw_owner = row.get("NAME", "")
        clean_owner = parse_owner_name(raw_owner)
        biz_name = str(row.get("BUSINESS NAME", "")).strip()

        records.append({
            "license_number": lic,
            "license_type": str(row.get("LICENSE TYPE", "")).strip(),
            "license_subtype": str(row.get("LICENSE SUBTYPE", "")).strip(),
            "license_expiration_date": str(row.get("LICENSE EXPIRATION DATE", "")).strip(),
            "county": str(row.get("COUNTY", "")).strip(),
            "business_county": str(row.get("BUSINESS COUNTY", "")).strip(),
            "owner_name": clean_owner,
            "business_name": biz_name,
            "pipeline_status": "pending",
        })

    logger.info("Seed", f"Loaded {len(records)} contractor records from source CSV")
    bulk_seed_contractors(records)
    return records


if __name__ == "__main__":
    source_file = ROOT / "data" / "source" / "new_batch.csv"
    if not source_file.exists():
        print(f"Error: {source_file} does not exist", file=sys.stderr)
        sys.exit(1)
    seed_database(source_file)
