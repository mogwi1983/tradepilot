"""Seed the contractors table from the source CSV.

Usage:
    python scripts/seed_supabase_from_csv.py
    python scripts/seed_supabase_from_csv.py --csv data/source/batch1_search_log_results.csv
    python scripts/seed_supabase_from_csv.py --truncate
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "data" / "source" / "batch1_search_log_results.csv"
MIGRATION = ROOT / "supabase" / "migrations" / "001_create_contractors.sql"
MIGRATION_003 = ROOT / "supabase" / "migrations" / "003_sequential_pipeline.sql"

# CSV column name -> contractors table column name
CSV_TO_DB: dict[str, str] = {
    "license_number": "license_number",
    "license_subtype": "license_subtype",
    "county": "county",
    "owner_name_raw": "owner_name_raw",
    "business_name_raw": "business_name_raw",
    "owner_var_1": "owner_var_1",
    "owner_var_2": "owner_var_2",
    "biz_var_1": "biz_var_1",
    "biz_var_2": "biz_var_2",
    "biz_var_3": "biz_var_3",
    "biz_var_4": "biz_var_4",
    "combo_var_1": "combo_var_1",
    "combo_var_2": "combo_var_2",
    "combo_var_3": "combo_var_3",
    "combo_var_4": "combo_var_4",
    "address_found": "address_found",
    "address": "address_raw",
    "address_confidence_%": "address_confidence_pct",
    "address_source": "address_source",
    "website_y/n": "website_yn",
    "website_url": "website_url",
    "website_confidence_%": "website_confidence_pct",
    "fb_y/n": "fb_yn",
    "fb_url": "fb_url",
    "fb_confidence_%": "fb_confidence_pct",
    "other_presence_types": "other_presence_types",
    "other_presence_y/n": "other_presence_yn",
    "other_confidence_%": "other_confidence_pct",
    "search_notes": "search_notes",
    "cohort": "cohort",
    "mail_wave": "mail_wave",
}

DB_COLUMNS = list(dict.fromkeys(CSV_TO_DB.values())) + ["seed_row_order"]


def _blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return str(value).strip() == ""


def _to_text(value) -> str | None:
    if _blank(value):
        return None
    return str(value).strip()


def _to_int(value) -> int | None:
    if _blank(value):
        return None
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


INT_COLUMNS = {
    "address_confidence_pct",
    "website_confidence_pct",
    "fb_confidence_pct",
    "other_confidence_pct",
}


def row_to_db_tuple(row: pd.Series, row_index: int) -> tuple:
    values: dict[str, object] = {}
    for csv_col, db_col in CSV_TO_DB.items():
        raw = row.get(csv_col, "")
        if db_col in INT_COLUMNS:
            values[db_col] = _to_int(raw)
        else:
            values[db_col] = _to_text(raw)
    values["seed_row_order"] = row_index
    return tuple(values[col] for col in DB_COLUMNS)


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if "license_number" in df.columns:
        df["license_number"] = df["license_number"].astype(str).str.strip()
    return df


def get_database_url() -> str:
    load_dotenv(ROOT / ".env.local")
    load_dotenv(ROOT / ".env")
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set in .env.local")
    return url


def run_migration(conn) -> None:
    for path in (MIGRATION, MIGRATION_003):
        if path.exists():
            sql = path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
    conn.commit()


def seed(conn, df: pd.DataFrame, *, truncate: bool) -> int:
    rows = [row_to_db_tuple(df.iloc[i], i) for i in range(len(df))]
    cols_sql = ", ".join(DB_COLUMNS)
    update_cols = [c for c in DB_COLUMNS if c != "license_number"]
    update_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)

    with conn.cursor() as cur:
        if truncate:
            cur.execute("TRUNCATE contractors")
        execute_values(
            cur,
            f"""
            INSERT INTO contractors ({cols_sql})
            VALUES %s
            ON CONFLICT (license_number) DO UPDATE SET {update_sql}
            """,
            rows,
            page_size=200,
        )
    conn.commit()
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Supabase contractors table from CSV")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="Source CSV path")
    parser.add_argument("--truncate", action="store_true", help="Clear table before insert")
    parser.add_argument("--skip-migration", action="store_true", help="Skip running SQL migration")
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        return 1

    df = load_csv(args.csv)
    print(f"Loaded {len(df)} rows from {args.csv}")

    url = get_database_url()
    conn = psycopg2.connect(url)
    try:
        if not args.skip_migration:
            print(f"Running migration: {MIGRATION.name}")
            run_migration(conn)

        inserted = seed(conn, df, truncate=args.truncate)
        print(f"Upserted {inserted} record(s) into contractors")

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM contractors")
            total = cur.fetchone()[0]
        print(f"Table now has {total} row(s)")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
