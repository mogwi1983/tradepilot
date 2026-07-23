"""Supabase REST Client helper for contractors table with automatic column filtering."""

from __future__ import annotations

import os
import re
import requests
from typing import Any

from core.env import load_env
from core.system_logger import get_system_logger

_KNOWN_COLUMNS: set[str] | None = None


def get_supabase_config() -> dict[str, str] | None:
    load_env()
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if url and key:
        return {"url": url.rstrip("/"), "key": key}
    return None


def discover_columns(cfg: dict[str, str], table: str = "contractors", unique_key: str = "license_number") -> set[str]:
    global _KNOWN_COLUMNS
    if _KNOWN_COLUMNS is not None:
        return _KNOWN_COLUMNS

    url = f"{cfg['url']}/rest/v1/{table}"
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    params = {"on_conflict": unique_key}

    probe = {
        "license_number": "PROBE_KEY",
        "license_subtype": "BE",
        "county": "DALLAS",
        "owner_name_raw": "PROBE OWNER",
        "business_name_raw": "PROBE BIZ",
        "website_yn": "N",
        "website_url": "",
        "fb_yn": "N",
        "fb_url": "",
        "address_raw": "",
        "address_source": "",
        "cohort": "unresolved",
    }

    resp = requests.post(url, headers=headers, params=params, json=[probe], timeout=15)
    if resp.status_code in (200, 201):
        _KNOWN_COLUMNS = set(probe.keys())
        # Clean up probe row
        requests.delete(url, headers=headers, params={"license_number": "eq.PROBE_KEY"}, timeout=10)
        return _KNOWN_COLUMNS

    missing = set()
    for m in re.finditer(r"Could not find the '([^']+)' column", resp.text):
        missing.add(m.group(1))

    known = set(probe.keys()) - missing
    known.add(unique_key)
    _KNOWN_COLUMNS = known
    return _KNOWN_COLUMNS


def upsert_contractor(
    data: dict[str, Any],
    table: str = "contractors",
    unique_key: str = "license_number",
) -> bool:
    """Upsert a single record into Supabase contractors table."""
    cfg = get_supabase_config()
    logger = get_system_logger()
    if not cfg:
        logger.warning("Supabase", "Supabase credentials not set — skipping DB upsert")
        return False

    url = f"{cfg['url']}/rest/v1/{table}"
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    params = {"on_conflict": unique_key}

    key_map = {
        "owner_name": "owner_name_raw",
        "business_name": "business_name_raw",
        "address_line1": "address_raw",
    }

    mapped = {}
    for k, v in data.items():
        db_key = key_map.get(k, k)
        if v is None or str(v).lower() in ("nan", "none", "null"):
            mapped[db_key] = None
        else:
            mapped[db_key] = str(v).strip()

    # Filter out columns not supported by schema
    known_cols = discover_columns(cfg, table, unique_key)
    filtered = {k: v for k, v in mapped.items() if k in known_cols or k == unique_key}

    try:
        resp = requests.post(url, headers=headers, params=params, json=[filtered], timeout=15)
        if resp.status_code in (200, 201):
            return True
        logger.error(
            "Supabase",
            f"Upsert failed HTTP {resp.status_code}",
            license_number=str(data.get("license_number", "N/A")),
            details=resp.text[:200],
        )
        return False
    except Exception as exc:
        logger.error(
            "Supabase",
            f"Upsert exception: {exc}",
            license_number=str(data.get("license_number", "N/A")),
        )
        return False


def bulk_seed_contractors(
    records: list[dict[str, Any]],
    table: str = "contractors",
    batch_size: int = 100,
) -> int:
    """Bulk upsert contractor records during seeding."""
    cfg = get_supabase_config()
    logger = get_system_logger()
    if not cfg:
        logger.warning("Supabase", "Supabase credentials missing — bulk seed skipped")
        return 0

    known_cols = discover_columns(cfg, table, "license_number")

    url = f"{cfg['url']}/rest/v1/{table}"
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    params = {"on_conflict": "license_number"}

    inserted_count = 0
    key_map = {
        "owner_name": "owner_name_raw",
        "business_name": "business_name_raw",
        "address_line1": "address_raw",
    }

    for i in range(0, len(records), batch_size):
        chunk = records[i : i + batch_size]
        cleaned_chunk = []
        for r in chunk:
            item = {}
            for k, v in r.items():
                db_key = key_map.get(k, k)
                if db_key in known_cols or db_key == "license_number":
                    item[db_key] = None if v is None or str(v).lower() in ("nan", "none") else str(v).strip()
            cleaned_chunk.append(item)

        try:
            resp = requests.post(url, headers=headers, params=params, json=cleaned_chunk, timeout=30)
            if resp.status_code in (200, 201):
                inserted_count += len(cleaned_chunk)
            else:
                logger.error("Supabase", f"Bulk seed chunk failed HTTP {resp.status_code}", details=resp.text[:300])
        except Exception as exc:
            logger.error("Supabase", f"Bulk seed chunk exception: {exc}")

    logger.info("Supabase", f"Seeded {inserted_count}/{len(records)} contractors to {table}")
    return inserted_count
