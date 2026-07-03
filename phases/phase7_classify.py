"""Phase 7 — Cohort classification and mail-wave assignment."""

from __future__ import annotations

import pandas as pd

from core.config import RunConfig
from core.csv_io import ensure_columns, update_record, write_csv
from core.logger import RunLogger
from core.utils import is_blank, normalize_county, now_iso

DEFAULT_COHORT_TARGETS = {"cohort_1": 200, "cohort_2": 200, "cohort_3": 200}
COHORT_ORDER = ("cohort_1", "cohort_2", "cohort_3")


def _cohort_targets(config: RunConfig) -> dict[str, int]:
    raw = getattr(config, "cohort_mail_targets", None) or DEFAULT_COHORT_TARGETS
    return {k: int(v) for k, v in raw.items()}


def _assign_cohort(
    row: pd.Series,
    target_counties: set[str],
    *,
    skip_county_validation: bool = False,
) -> tuple[str, str, str]:
    """Return (cohort, exclusion_reason, unresolved_reason)."""
    if not skip_county_validation:
        county = normalize_county(row.get("county", ""))
        if county not in target_counties:
            return "excluded", "out_of_geography", ""

    web = str(row.get("website_y/n", "")).upper().strip()
    fb = str(row.get("fb_y/n", "")).upper().strip()

    if web == "UNCERTAIN" or fb == "UNCERTAIN":
        return "unresolved", "", "uncertain_presence_detection"

    # Cohort 3: has website (Facebook optional — may not have run Phase 2 yet)
    if web == "Y":
        return "cohort_3", "", ""

    if not web:
        return "unresolved", "", "incomplete_presence_data"
    if web == "N" and not fb:
        return "unresolved", "", "awaiting_facebook_detection"

    if web == "N" and fb == "Y":
        return "cohort_2", "", ""
    if web == "N" and fb == "N":
        return "cohort_1", "", ""

    return "unresolved", "", "incomplete_presence_data"


def _score(row: pd.Series, cohort: str) -> int:
    score = 0
    src_count = int(row.get("address_source_count") or 0) if str(row.get("address_source_count", "")).isdigit() else 0
    if src_count == 1:
        score += 15
    elif src_count == 2:
        score += 25
    elif src_count >= 3:
        score += 35

    if str(row.get("address_conflict_detected", "")).lower() != "true" and src_count >= 2:
        score += 5
    if row.get("address_raw") and row.get("address_source"):
        score += 5
    if str(row.get("address_type_guess", "")).lower() == "residential":
        score -= 5

    lob_del = str(row.get("lob_deliverability", ""))
    if lob_del == "deliverable":
        score += 25
    elif lob_del == "deliverable_missing_unit":
        score += 10
    if str(row.get("lob_vacancy", "")) == "vacant":
        score -= 15

    if cohort in COHORT_ORDER:
        score += 20
    elif cohort == "unresolved":
        score += 5

    if str(row.get("address_conflict_detected", "")).lower() == "true" and cohort == "unresolved":
        score -= 10
    fb_conf = int(row.get("fb_confidence_%") or 0) if str(row.get("fb_confidence_%", "")).isdigit() else 0
    if str(row.get("fb_y/n", "")).upper() == "Y" and fb_conf < 60:
        score -= 5

    return max(0, min(100, score))


def _tier(score: int) -> str:
    if score >= 75:
        return "A"
    if score >= 50:
        return "B"
    return "C"


def _lob_ready(row: pd.Series) -> bool:
    return (
        str(row.get("lob_deliverability", "")) == "deliverable"
        and str(row.get("lob_vacancy", "")) != "vacant"
    )


def _assign_mail_waves(df: pd.DataFrame, targets: dict[str, int]) -> pd.DataFrame:
    """Rank mail-ready records per cohort; top N -> wave_1, rest -> wave_2."""
    df = df.copy()
    if "mail_wave" not in df.columns:
        df["mail_wave"] = ""

    for cohort in COHORT_ORDER:
        cap = targets.get(cohort, 200)
        mask = df["cohort"] == cohort if "cohort" in df.columns else pd.Series([False] * len(df))
        ready_mask = mask & (df.get("lob_ready", pd.Series([""] * len(df))).astype(str).str.lower() == "true")
        ready_idx = df.index[ready_mask]
        if len(ready_idx) == 0:
            continue

        scores = pd.to_numeric(df.loc[ready_idx, "confidence_score"], errors="coerce").fillna(0)
        ranked = scores.sort_values(ascending=False).index.tolist()
        for i, idx in enumerate(ranked):
            df.at[idx, "mail_wave"] = "wave_1" if i < cap else "wave_2"
            df.at[idx, "batch_assignment"] = "batch_1" if i < cap else "batch_2"

    for idx, row in df.iterrows():
        cohort = str(row.get("cohort", ""))
        if cohort in ("excluded", "unresolved", ""):
            if is_blank(row.get("mail_wave")):
                df.at[idx, "mail_wave"] = "ineligible"
                df.at[idx, "batch_assignment"] = cohort if cohort else "unresolved"
            continue
        if is_blank(row.get("mail_wave")):
            df.at[idx, "mail_wave"] = "pending"
            df.at[idx, "batch_assignment"] = "pending"

    return df


def run(df: pd.DataFrame, config: RunConfig, logger: RunLogger) -> pd.DataFrame:
    logger.set_phase("phase7")
    df = ensure_columns(
        df,
        [
            "cohort",
            "mail_wave",
            "batch_assignment",
            "lob_ready",
            "exclusion_reason",
            "unresolved_reason",
            "confidence_score",
            "confidence_tier",
            "phase7_timestamp",
        ],
    )

    target = {normalize_county(c) for c in config.target_counties}
    targets = _cohort_targets(config)
    ts = now_iso()

    for idx, row in df.iterrows():
        lic = str(row["license_number"])
        if not is_blank(row.get("cohort")) and not is_blank(row.get("phase7_timestamp")):
            # Re-classify when presence signals updated (e.g. website set after prior phase 7)
            web = str(row.get("website_y/n", "")).upper()
            fb = str(row.get("fb_y/n", "")).upper()
            cohort = str(row.get("cohort", ""))
            expected = _assign_cohort(row, target, skip_county_validation=config.skip_county_validation)[0]
            if cohort == expected:
                continue
        if config.resume_from_record and lic != str(config.resume_from_record):
            continue

        cohort, excl, unres = _assign_cohort(row, target, skip_county_validation=config.skip_county_validation)
        score = _score(row, cohort)
        tier = _tier(score)
        ready = _lob_ready(row)

        df = update_record(
            df,
            lic,
            {
                "cohort": cohort,
                "lob_ready": str(ready).lower(),
                "exclusion_reason": excl,
                "unresolved_reason": unres,
                "confidence_score": str(score),
                "confidence_tier": tier,
                "phase7_timestamp": ts,
            },
            phase=7,
            force=True,
        )
        logger.info(f"cohort={cohort} tier={tier} score={score}", license_number=lic)

    df = _assign_mail_waves(df, targets)
    write_csv(df, config.output_path)

    for cohort in COHORT_ORDER:
        n = (df["cohort"] == cohort).sum()
        w1 = ((df["cohort"] == cohort) & (df["mail_wave"] == "wave_1")).sum()
        w2 = ((df["cohort"] == cohort) & (df["mail_wave"] == "wave_2")).sum()
        logger.info(f"{cohort}: {n} assigned, wave_1={w1}, wave_2={w2}")

    return df
