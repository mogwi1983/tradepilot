"""Phase 8 — QA Audit."""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from core.config import RunConfig
from core.logger import RunLogger
from core.utils import is_blank

VALID_COHORTS = {"cohort_1", "cohort_2", "cohort_3", "excluded", "unresolved"}
VALID_WAVES = {"wave_1", "wave_2", "pending", "ineligible"}


def run(df: pd.DataFrame, config: RunConfig, logger: RunLogger) -> pd.DataFrame:
    logger.set_phase("phase8")
    violations: dict[int, list[str]] = defaultdict(list)

    for _, row in df.iterrows():
        lic = str(row["license_number"])
        if is_blank(row.get("cohort")):
            violations[1].append(lic)

    for _, row in df.iterrows():
        lic = str(row["license_number"])
        cohort = str(row.get("cohort", ""))
        if cohort and cohort not in VALID_COHORTS:
            violations[2].append(lic)

    for _, row in df.iterrows():
        lic = str(row["license_number"])
        if str(row.get("lob_ready", "")).lower() == "true":
            if str(row.get("lob_deliverability", "")) != "deliverable":
                violations[3].append(lic)
            if is_blank(row.get("lob_standardized_address")):
                violations[3].append(lic)

    for _, row in df.iterrows():
        lic = str(row["license_number"])
        if str(row.get("cohort", "")) == "excluded" and is_blank(row.get("exclusion_reason")):
            violations[4].append(lic)

    for _, row in df.iterrows():
        lic = str(row["license_number"])
        try:
            score = int(row.get("confidence_score") or 0)
        except ValueError:
            violations[5].append(lic)
            continue
        tier = str(row.get("confidence_tier", ""))
        expected = "A" if score >= 75 else "B" if score >= 50 else "C"
        if tier != expected:
            violations[5].append(lic)

    for _, row in df.iterrows():
        lic = str(row["license_number"])
        web = str(row.get("website_y/n", "")).upper()
        fb = str(row.get("fb_y/n", "")).upper()
        cohort = str(row.get("cohort", ""))
        if cohort == "cohort_1" and (web != "N" or fb != "N"):
            violations[6].append(lic)
        if cohort == "cohort_2" and not (web == "N" and fb == "Y"):
            violations[6].append(lic)
        if cohort == "cohort_3" and web != "Y":
            violations[6].append(lic)

    counts = df["license_number"].astype(str).value_counts()
    violations[7].extend(counts[counts > 1].index.tolist()[:20])

    cohort_counts = {c: (df["cohort"] == c).sum() for c in VALID_COHORTS if "cohort" in df.columns}
    wave1 = (df["mail_wave"] == "wave_1").sum() if "mail_wave" in df.columns else 0
    wave2 = (df["mail_wave"] == "wave_2").sum() if "mail_wave" in df.columns else 0
    mail_ready = (df["lob_ready"].astype(str).str.lower() == "true").sum() if "lob_ready" in df.columns else 0

    lines = [
        f"# QA Report — {config.run_id}",
        "",
        f"Total records audited: **{len(df)}**",
        "",
        "## Cohort counts",
        f"- Cohort 1 (no FB / no site): {cohort_counts.get('cohort_1', 0)}",
        f"- Cohort 2 (FB only): {cohort_counts.get('cohort_2', 0)}",
        f"- Cohort 3 (has site): {cohort_counts.get('cohort_3', 0)}",
        f"- Excluded: {cohort_counts.get('excluded', 0)}",
        f"- Unresolved: {cohort_counts.get('unresolved', 0)}",
        "",
        "## Mail waves",
        f"- Wave 1 (initial 200/cohort cap): {wave1}",
        f"- Wave 2 (overflow): {wave2}",
        f"- Mail ready total: {mail_ready}",
        "",
        "## Violations",
    ]

    check_names = {
        1: "Missing cohort",
        2: "Invalid cohort value",
        3: "lob_ready without deliverable address",
        4: "excluded without exclusion_reason",
        5: "confidence_tier mismatch",
        6: "cohort does not match website/fb signals",
        7: "duplicate license_number",
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
    print("\n".join(lines[:25]))
    print(f"\n... full report: {report_path}")

    return df
