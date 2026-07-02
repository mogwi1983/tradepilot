"""Lob USPS address verification + budget tracking."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from core.env import get_lob_api_key
from core.utils import now_iso


class LobBudgetExhaustedError(Exception):
    """Remaining verifications = 0."""


class LobBudgetWarningError(Exception):
    """Remaining < 50 — log warning but continue."""


@dataclass
class LobResult:
    lob_verified: bool
    lob_deliverability: str
    lob_standardized_address: str
    lob_address_type: str
    lob_vacancy: str


def _load_budget(path: Path) -> dict:
    if not path.exists():
        data = {
            "total_free_verifications": 300,
            "used": 0,
            "remaining": 300,
            "last_updated": now_iso(),
            "runs": [],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data
    return json.loads(path.read_text(encoding="utf-8"))


def _save_budget(path: Path, data: dict) -> None:
    data["last_updated"] = now_iso()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def check_budget(budget_file: str | Path) -> tuple[int, bool]:
    """Return (remaining, warn). Raises LobBudgetExhaustedError if 0."""
    path = Path(budget_file)
    data = _load_budget(path)
    remaining = int(data.get("remaining", 0))
    if remaining <= 0:
        raise LobBudgetExhaustedError("Lob free verification budget exhausted")
    return remaining, remaining < 50


def _parse_address_raw(address_raw: str) -> dict[str, str]:
    """Best-effort parse of a single-line US address."""
    parts = [p.strip() for p in address_raw.replace("\n", ", ").split(",") if p.strip()]
    if len(parts) < 2:
        return {"primary_line": address_raw.strip(), "city": "", "state": "TX", "zip_code": ""}

    # Last part often "TX 76102" or "Texas 76102"
    state_zip = parts[-1].split()
    state = "TX"
    zip_code = ""
    if len(state_zip) >= 2:
        state = state_zip[0].upper()[:2]
        zip_code = state_zip[-1]
        city = parts[-2]
        primary = ", ".join(parts[:-2]) if len(parts) > 2 else parts[0]
    else:
        city = parts[-1]
        primary = ", ".join(parts[:-1])

    return {
        "primary_line": primary,
        "city": city,
        "state": state if state else "TX",
        "zip_code": zip_code,
    }


def verify_address(address: dict[str, str], budget_file: str | Path, *, run_id: str = "") -> LobResult:
    path = Path(budget_file)
    remaining, _ = check_budget(path)

    if address.get("street") or address.get("primary_line"):
        payload = {
            "primary_line": address.get("primary_line") or address.get("street", ""),
            "city": address.get("city", ""),
            "state": address.get("state", "TX"),
            "zip_code": address.get("zip") or address.get("zip_code", ""),
        }
    else:
        payload = _parse_address_raw(address.get("full", "") or address.get("address_raw", ""))

    if not payload.get("primary_line"):
        return LobResult(
            lob_verified=False,
            lob_deliverability="not_called",
            lob_standardized_address="",
            lob_address_type="",
            lob_vacancy="",
        )

    api_key = get_lob_api_key()
    resp = requests.post(
        "https://api.lob.com/v1/us_verifications",
        auth=(api_key, ""),
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    budget = _load_budget(path)
    budget["used"] = int(budget.get("used", 0)) + 1
    budget["remaining"] = max(0, int(budget.get("total_free_verifications", 300)) - budget["used"])
    if run_id:
        budget.setdefault("runs", []).append({"run_id": run_id, "at": now_iso()})
    _save_budget(path, budget)

    deliverability = str(data.get("deliverability", "undeliverable"))
    components = data.get("components") or {}
    std_parts = [
        data.get("primary_line") or payload["primary_line"],
        data.get("secondary_line") or "",
        f"{components.get('city', payload.get('city', ''))}, "
        f"{components.get('state', payload.get('state', ''))} "
        f"{components.get('zip_code', payload.get('zip_code', ''))}".strip(),
    ]
    standardized = ", ".join(p for p in std_parts if p).strip(", ")

    return LobResult(
        lob_verified=True,
        lob_deliverability=deliverability,
        lob_standardized_address=standardized,
        lob_address_type=str(data.get("address_type", "") or ""),
        lob_vacancy=str(data.get("vacancy", "unknown") or "unknown"),
    )
