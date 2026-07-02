"""
Lob USPS address verification + budget tracking.

Spec: CURSOR-BOOTSTRAP.md Step 2 — core/lob.py
Budget file: data/lob_budget.json (see DATA-SCHEMA.md § Lob Budget File)
API: POST https://api.lob.com/v1/us_verifications
Env: LOB_API_KEY or LOB_SECRET_API_KEY_TEST / LOB_SECRET_API_KEY_LIVE
"""

from __future__ import annotations

from dataclasses import dataclass


class LobBudgetExhaustedError(Exception):
    """Remaining verifications = 0. Phase 5 must halt."""


class LobBudgetWarningError(Exception):
    """Remaining < 50. Log warning but continue."""


@dataclass
class LobResult:
    lob_verified: bool
    lob_deliverability: str
    lob_standardized_address: str
    lob_address_type: str
    lob_vacancy: str


def verify_address(address: dict[str, str], budget_file: str) -> LobResult:
    """Call Lob, update budget file, return result fields for CSV."""
    raise NotImplementedError
