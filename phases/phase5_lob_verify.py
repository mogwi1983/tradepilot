"""Phase 5 — Lob Address Verification."""

from __future__ import annotations

import pandas as pd

from core.config import RunConfig
from core.csv_io import ensure_columns, phase_complete, update_record, write_csv
from core.lob import LobBudgetExhaustedError, LobNetworkError, check_budget, verify_address
from core.logger import RunLogger
from core.utils import is_blank, now_iso


_SOURCE_PRIORITY = {"website": 0, "facebook": 1, "gmaps": 2, "gsearch": 3}


def run(df: pd.DataFrame, config: RunConfig, logger: RunLogger) -> pd.DataFrame:
    logger.set_phase("phase5")
    df = ensure_columns(
        df,
        [
            "lob_verified",
            "lob_deliverability",
            "lob_standardized_address",
            "lob_address_type",
            "lob_vacancy",
            "lob_verification_timestamp",
        ],
    )

    pending = []
    for _, row in df.iterrows():
        lic = str(row["license_number"])
        if phase_complete(row, 5) or not is_blank(row.get("lob_verification_timestamp")):
            continue
        if str(row.get("address_found", "")).upper() != "Y":
            df = update_record(
                df,
                lic,
                {
                    "lob_verified": "false",
                    "lob_deliverability": "not_called",
                    "lob_standardized_address": "",
                    "lob_address_type": "",
                    "lob_vacancy": "",
                },
                phase=5,
            )
            continue
        if str(row.get("address_is_pobox", "")).lower() == "true":
            logger.warning("PO Box — skipping Lob without human review", license_number=lic)
            continue
        src = str(row.get("address_source", "gsearch"))
        pending.append((lic, _SOURCE_PRIORITY.get(src, 9), row))

    pending.sort(key=lambda x: x[1])

    for lic, _, row in pending:
        if config.resume_from_record and lic != str(config.resume_from_record):
            continue
        try:
            remaining, warn = check_budget(config.lob_budget_path)
            if warn:
                logger.warning(f"Lob budget low: {remaining} remaining")
        except LobBudgetExhaustedError:
            logger.error("Lob budget exhausted — halting Phase 5")
            break

        try:
            result = verify_address(
                {"full": str(row.get("address_raw", "")), "address_raw": str(row.get("address_raw", ""))},
                config.lob_budget_path,
                run_id=config.run_id,
            )
            df = update_record(
                df,
                lic,
                {
                    "lob_verified": str(result.lob_verified).lower(),
                    "lob_deliverability": result.lob_deliverability,
                    "lob_standardized_address": result.lob_standardized_address,
                    "lob_address_type": result.lob_address_type,
                    "lob_vacancy": result.lob_vacancy,
                    "lob_verification_timestamp": now_iso(),
                },
                phase=5,
            )
            write_csv(df, config.output_path)
            logger.info(f"lob={result.lob_deliverability}", license_number=lic)
        except LobBudgetExhaustedError:
            logger.error("Lob budget exhausted mid-run")
            break
        except LobNetworkError as exc:
            logger.warning(f"Lob network error (will retry next run): {exc}", license_number=lic)
            df = update_record(
                df,
                lic,
                {
                    "lob_verified": "false",
                    "lob_deliverability": "error",
                    "lob_standardized_address": "",
                    "lob_address_type": "",
                    "lob_vacancy": "",
                    # Intentionally NOT setting lob_verification_timestamp — retry next run
                },
                phase=5,
            )
            write_csv(df, config.output_path)
        except Exception as exc:
            logger.error(f"Lob error: {exc}", license_number=lic)
            df = update_record(
                df,
                lic,
                {
                    "lob_verified": "false",
                    "lob_deliverability": "undeliverable",
                    "lob_standardized_address": "",
                    "lob_address_type": "",
                    "lob_vacancy": "",
                    "lob_verification_timestamp": now_iso(),
                },
                phase=5,
            )
            write_csv(df, config.output_path)

    return df
