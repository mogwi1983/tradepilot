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

# DB column -> working CSV column (inverse of seed script + migration fields)
DB_TO_CSV: dict[str, str] = {
    "website_yn": "website_y/n",
    "website_confidence_pct": "website_confidence_%",
    "fb_yn": "fb_y/n",
    "fb_confidence_pct": "fb_confidence_%",
    "address_raw": "address",
    "address_confidence_pct": "address_confidence_%",
    "other_presence_yn": "other_presence_y/n",
    "other_confidence_pct": "other_confidence_%",
}

DB_SKIP_COLUMNS = {"created_at", "updated_at"}


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


def _db_value_to_csv(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip()
    return "" if text.lower() in ("none", "nan") else text


def db_rows_to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert Supabase REST rows into a working CSV-shaped DataFrame."""
    csv_rows: list[dict[str, str]] = []
    for row in rows:
        csv_row: dict[str, str] = {}
        for db_col, val in row.items():
            if db_col in DB_SKIP_COLUMNS:
                continue
            csv_col = DB_TO_CSV.get(db_col, db_col)
            csv_row[csv_col] = _db_value_to_csv(val)
        csv_rows.append(csv_row)

    if not csv_rows:
        return pd.DataFrame()

    df = pd.DataFrame(csv_rows)
    if "license_number" in df.columns:
        df["license_number"] = df["license_number"].astype(str).str.strip()
    return df.fillna("")


def fetch_next_batch_sequential(
    limit: int = 100,
    table: str = "contractors",
) -> list[dict[str, Any]]:
    """Next unprocessed contractors in CSV seed order (top to bottom).

    When BATCH_ASSIGNMENT env var is set, only fetches records with
    that batch_assignment value (for parallel processing).
    """
    import os as _os
    cfg = _get_supabase_config()
    if not cfg:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")

    url = f"{cfg['url']}/rest/v1/{table}"
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
    }
    params = {
        "select": "*",
        "phase7_timestamp": "is.null",
        "order": "seed_row_order.asc.nullslast,license_number.asc",
        "limit": str(limit),
    }

    batch_filter = _os.environ.get("BATCH_ASSIGNMENT", "").strip()
    if batch_filter:
        params["batch_assignment"] = f"eq.{batch_filter}"

    resp = requests.get(url, headers=headers, params=params, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Supabase fetch failed: HTTP {resp.status_code} — {resp.text[:300]}")

    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected Supabase response: {data!r}")
    return data


def fetch_unprocessed_contractors(
    limit: int = 50,
    table: str = "contractors",
) -> list[dict[str, Any]]:
    """Backward-compatible alias — sequential order, no county/subtype filter."""
    return fetch_next_batch_sequential(limit=limit, table=table)


def fetch_contractors_for_campaign(
    table: str = "contractors",
    *,
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    """Paginated fetch of summary columns for campaign dashboard stats."""
    cfg = _get_supabase_config()
    if not cfg:
        return []

    url = f"{cfg['url']}/rest/v1/{table}"
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
    }
    columns = (
        "license_number,cohort,mail_wave,lob_ready,lob_deliverability,"
        "phase7_timestamp,website_yn,fb_yn,address_found,address_raw,"
        "address_is_pobox,batch1_excluded,seed_row_order"
    )
    rows: list[dict[str, Any]] = []
    offset = 0

    while True:
        params = {
            "select": columns,
            "order": "license_number.asc",
            "limit": str(page_size),
            "offset": str(offset),
        }
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Supabase campaign fetch failed: HTTP {resp.status_code} — {resp.text[:300]}"
            )
        batch = resp.json()
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    return rows


def fetch_campaign_view(table: str = "campaign_cohort_summary") -> list[dict[str, Any]] | None:
    """Try the SQL view first; return None if not deployed."""
    cfg = _get_supabase_config()
    if not cfg:
        return None

    url = f"{cfg['url']}/rest/v1/{table}"
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        return None
    data = resp.json()
    return data if isinstance(data, list) else None


def _prepare_df_for_upsert(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [c.lower().strip() for c in out.columns]
    out = out.fillna("")

    col_rename: dict[str, str] = {}
    for c in out.columns:
        new_c = c.replace("/", "").replace("%", "pct").replace("-", "_")
        if new_c != c:
            col_rename[c] = new_c
    if col_rename:
        out = out.rename(columns=col_rename)
    return out


def upsert_dataframe(
    df: pd.DataFrame,
    *,
    table: str = "contractors",
    unique_key: str = "license_number",
    batch_size: int = 200,
    license_numbers: list[str] | None = None,
) -> dict[str, Any]:
    """Upsert a DataFrame into Supabase via REST API."""
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
        "table": table,
        "unique_key": unique_key,
        "total_rows": 0,
        "inserted": 0,
        "updated": 0,
        "errors": 0,
        "error_details": [],
    }

    if df.empty:
        return result

    work = _prepare_df_for_upsert(df)
    if license_numbers:
        lic_set = {str(x).strip() for x in license_numbers}
        work = work[work[unique_key].astype(str).str.strip().isin(lic_set)]

    result["total_rows"] = len(work)
    if work.empty:
        return result

    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

    first_row = {c: str(work.iloc[0][c]) for c in work.columns}
    known_cols = _discover_columns(cfg, table, unique_key, first_row)
    work = work[[c for c in work.columns if c in known_cols]]

    for start in range(0, len(work), batch_size):
        batch = work.iloc[start : start + batch_size]
        rows = []
        for _, row in batch.iterrows():
            record = {}
            for c in work.columns:
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

    sync_result = upsert_dataframe(
        df,
        table=table,
        unique_key=unique_key,
        batch_size=batch_size,
    )
    sync_result["csv_path"] = str(csv_path)
    return sync_result


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
