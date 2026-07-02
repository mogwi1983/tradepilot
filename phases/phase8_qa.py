"""Phase 8 — QA Audit."""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from core.config import RunConfig
from core.logger import RunLogger
from core.utils import is_blank


def run(df: pd.DataFrame, config: RunConfig, logger: RunLogger) -> pd.DataFrame:
    logger.set_phase("phase8")
    violations: dict[int, list[str]] = defaultdict(list)

    # 1. Every record has batch_assignment
    for _, row in df.iterrows():
        lic = str(row["license_number"])
        if is_blank(row.get("batch_assignment")):
            violations[1].append(lic)

    # 2. lob_ready=true requires deliverable address
    for _, row in df.iterrows():
        lic = str(row["license_number"])
        if str(row.get("lob_ready", "")).lower() == "true":
            if str(row.get("lob_deliverability", "")) != "deliverable":
                violations[2].append(lic)
            if is_blank(row.get("lob_standardized_address")):
                violations[2].append(lic)

    # 3. excluded requires exclusion_reason
    for _, row in df.iterrows():
        lic = str(row["license_number"])
        if str(row.get("batch_assignment", "")) == "excluded" and is_blank(row.get("exclusion_reason")):
            violations[3].append(lic)

    # 4. confidence tier matches score
    for _, row in df.iterrows():
        lic = str(row["license_number"])
        try:
            score = int(row.get("confidence_score") or 0)
        except ValueError:
            violations[4].append(lic)
            continue
        tier = str(row.get("confidence_tier", ""))
        expected = "A" if score >= 75 else "B" if score >= 50 else "C"
        if tier != expected:
            violations[4].append(lic)

    # 5. website Y cannot be lob_ready
    for _, row in df.iterrows():
        lic = str(row["license_number"])
        if str(row.get("website_y/n", "")).upper() == "Y" and str(row.get("lob_ready", "")).lower() == "true":
            violations[5].append(lic)

    # 6. duplicate license numbers
    counts = df["license_number"].astype(str).value_counts()
    dups = counts[counts > 1].index.tolist()
    violations[6].extend(dups[:20])

    # Counts
    batch1 = (df["batch_assignment"] == "batch_1").sum() if "batch_assignment" in df.columns else 0
    batch2 = (df["batch_assignment"] == "batch_2").sum() if "batch_assignment" in df.columns else 0
    excluded = (df["batch_assignment"] == "excluded").sum() if "batch_assignment" in df.columns else 0
    unresolved = (df["batch_assignment"] == "unresolved").sum() if "batch_assignment" in df.columns else 0
    tier_a = (df["confidence_tier"] == "A").sum() if "confidence_tier" in df.columns else 0
    tier_b = (df["confidence_tier"] == "B").sum() if "confidence_tier" in df.columns else 0
    tier_c = (df["confidence_tier"] == "C").sum() if "confidence_tier" in df.columns else 0

    lines = [
        f"# QA Report — {config.run_id}",
        "",
        f"Total records audited: **{len(df)}**",
        "",
        "## Batch counts",
        f"- Batch 1: {batch1}",
        f"- Batch 2: {batch2}",
        f"- Excluded: {excluded}",
        f"- Unresolved: {unresolved}",
        "",
        "## Confidence tiers",
        f"- Tier A: {tier_a}",
        f"- Tier B: {tier_b}",
        f"- Tier C: {tier_c}",
        "",
        "## Violations",
    ]

    check_names = {
        1: "Missing batch_assignment",
        2: "lob_ready without deliverable address",
        3: "excluded without exclusion_reason",
        4: "confidence_tier mismatch",
        5: "website Y with lob_ready true",
        6: "duplicate license_number",
    }

    total_violations = 0
    for check_num in sorted(check_names):
        ids = list(dict.fromkeys(violations[check_num]))[:20]
        total_violations += len(violations[check_num])
        lines.append(f"### Check {check_num}: {check_names[check_num]}")
        lines.append(f"Count: {len(violations[check_num])}")
        if ids:
            lines.append("Record IDs: " + ", ".join(ids))
        lines.append("")

    lines.append("## Recommended corrections")
    if total_violations == 0:
        lines.append("No violations detected.")
    else:
        lines.append(f"Review {total_violations} violation(s) above before mailing.")

    report_path = config.run_log_dir / f"qa_report_{config.run_id}.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"QA report written: {report_path}")
    print("\n".join(lines[:20]))
    print(f"\n... full report: {report_path}")

    return df
