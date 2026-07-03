"""Load and validate run_config.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from core.env import load_env

_REQUIRED = (
    "run_id",
    "input_file",
    "output_file",
    "target_counties",
    "license_subtypes",
    "max_records",
    "county_priority",
    "lob_budget_file",
    "phases_to_run",
    "start_phase",
)


@dataclass
class RunConfig:
    run_id: str
    input_file: str
    output_file: str
    target_counties: list[str]
    license_subtypes: list[str]
    max_records: int
    county_priority: list[str]
    lob_budget_file: str
    phases_to_run: list[int]
    start_phase: int
    resume_from_record: str | None
    cohort_mail_targets: dict[str, int] | None = None
    batch_size: int = 100
    skip_county_validation: bool = False
    stratify_by_license_subtype: bool = True

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def resolve(self, path: str) -> Path:
        p = Path(path)
        return p if p.is_absolute() else self.project_root / p

    @property
    def input_path(self) -> Path:
        return self.resolve(self.input_file)

    @property
    def output_path(self) -> Path:
        return self.resolve(self.output_file)

    @property
    def lob_budget_path(self) -> Path:
        return self.resolve(self.lob_budget_file)

    @property
    def run_log_dir(self) -> Path:
        return self.project_root / "runs" / self.run_id


def load_run_config(path: str | Path = "run_config.json") -> RunConfig:
    load_env()
    root = Path(__file__).resolve().parent.parent
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = root / config_path

    if not config_path.exists():
        raise FileNotFoundError(f"run_config.json not found: {config_path}")

    with config_path.open(encoding="utf-8") as f:
        data = json.load(f)

    missing = [k for k in _REQUIRED if k not in data]
    if missing:
        raise ValueError(f"run_config.json missing fields: {', '.join(missing)}")

    cfg = RunConfig(
        run_id=str(data["run_id"]),
        input_file=str(data["input_file"]),
        output_file=str(data["output_file"]),
        target_counties=[str(c) for c in data["target_counties"]],
        license_subtypes=[str(s) for s in data["license_subtypes"]],
        max_records=int(data["max_records"]),
        county_priority=[str(c) for c in data["county_priority"]],
        lob_budget_file=str(data["lob_budget_file"]),
        phases_to_run=[int(p) for p in data["phases_to_run"]],
        start_phase=int(data["start_phase"]),
        resume_from_record=data.get("resume_from_record"),
        cohort_mail_targets=data.get("cohort_mail_targets"),
        batch_size=int(data.get("batch_size", 100)),
        skip_county_validation=bool(data.get("skip_county_validation", False)),
        stratify_by_license_subtype=bool(data.get("stratify_by_license_subtype", True)),
    )

    if not cfg.input_path.exists():
        raise FileNotFoundError(f"input_file does not exist: {cfg.input_path}")

    cfg.output_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.run_log_dir.mkdir(parents=True, exist_ok=True)
    return cfg
