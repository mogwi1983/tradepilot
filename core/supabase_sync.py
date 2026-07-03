"""Supabase auto-sync — upsert the working CSV into the contractors table via REST API.

Skipped harmlessly if SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY are not set.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from core.env import load_env


def _get_supabase_config() -> dict[str, str] | None:
    load_env()
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if url and key:
        return {"url": url.rstrip("/"), "key": key}
    return None


def _discover_columns(cfg: dict, table: str, unique_key: str,
                      probe_row: dict) -> list[str]:
    """Probe the Supabase table to discover which columns exist."""
    url = f"{cfg['url']}/rest/v1/{table}"
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    params = {"on_conflict": unique_key}

    resp = requests.post(url, headers=headers, params=params,
                         json=[probe_row], timeout=15)

    if resp.status_code in (200, 201):
        return list(probe_row.keys())

    # Parse "Could not find the 'X' column" errors
    missing = set()
    for m in re.finditer(r"Could not find the '([^']+)' column", resp.text):
        missing.add(m.group(1))
    # Also try uppercase column references
    for m in re.finditer(r"Could not find the \"([^\"]+)\" column", resp.text):
        missing.add(m.group(1))

    known = [c for c in probe_row if c not in missing]
    if unique_key not in known:
        known.insert(0, unique_key)
    return known


def upsert_csv(
    csv_path: str | Path,
    table: str = "contractors",
    unique_key: str = "license_number",
    batch_size: int = 200,
) -> dict[str, Any]:
    """Read a CSV and upsert into Supabase via REST API.

    Returns a dict with counts of inserted/updated/skipped/errors.
    """
    cfg = _get_supabase_config()
    if not cfg:
        return {
            "status": "skipped",
            "reason": "SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set",
            "inserted": 0,
            "updated": 0,
        }

    result: dict[str, Any] = {
        "status": "ok",
        "csv_path": str(csv_path),
        "table": table,
        "unique_key": unique_key,
        "total_rows": 0,
        "inserted": 0,
        "updated": 0,
        "errors": 0,
        "error_details": [],
    }

    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    result["total_rows"] = len(df)

    if df.empty:
        return result

    # Normalise column names to lowercase, replace NaN
    df.columns = [c.lower().strip() for c in df.columns]
    df = df.fillna("")

    # Translate CSV column names to Postgres-compatible names
    col_rename = {}
    for c in df.columns:
        new_c = c.replace("/", "").replace("%", "pct").replace("-", "_")
        if new_c != c:
            col_rename[c] = new_c
    if col_rename:
        df = df.rename(columns=col_rename)
        result["renamed_columns"] = col_rename

    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

    # Discover valid columns by probing with first row
    first_row = {c: str(df.iloc[0][c]) for c in df.columns}
    known_cols = _discover_columns(cfg, table, unique_key, first_row)
    result["filtered_columns"] = len(df.columns) - len(known_cols)

    # Filter DataFrame to only known columns
    df = df[[c for c in df.columns if c in known_cols]]

    # Upsert in batches
    for start in range(0, len(df), batch_size):
        batch = df.iloc[start : start + batch_size]
        rows = []
        for _, row in batch.iterrows():
            record = {}
            for c in df.columns:
                val = str(row[c])
                record[c] = None if val == "" or val == "nan" else val
            rows.append(record)

        url = f"{cfg['url']}/rest/v1/{table}"
        params = {"on_conflict": unique_key}

        try:
            resp = requests.post(url, headers=headers, params=params,
                                 json=rows, timeout=60)
            if resp.status_code in (200, 201):
                result["inserted"] += len(rows)
            else:
                result["errors"] += 1
                result["error_details"].append(
                    f"batch {start}..{start + batch_size}: "
                    f"HTTP {resp.status_code} - {resp.text[:200]}"
                )
        except requests.exceptions.RequestException as exc:
            result["errors"] += 1
            result["error_details"].append(
                f"batch {start}..{start + batch_size}: {exc}"
            )

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Supabase CSV upsert via REST API")
    parser.add_argument("--csv", default=None, help="Path to CSV file")
    parser.add_argument(
        "--run", action="store_true",
        help="Read output_file from run_config.json",
    )
    parser.add_argument("--table", default="contractors",
                        help="Target table name")
    parser.add_argument(
        "--unique-key", default="license_number",
        help="Unique key for upsert",
    )
    args = parser.parse_args()

    csv_path = args.csv
    if args.run and not csv_path:
        from core.config import load_run_config
        config = load_run_config("run_config.json")
        csv_path = str(config.output_path)

    if not csv_path:
        print("Usage: python -m core.supabase_sync --csv <path> or --run")
        sys.exit(1)

    csv_path = Path(csv_path)
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}")
        sys.exit(1)

    result = upsert_csv(csv_path, table=args.table,
                        unique_key=args.unique_key)
    print(json.dumps(result, indent=2, default=str))
    if result.get("errors", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
