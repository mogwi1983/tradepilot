"""Pipeline tuning config — adjusted by DeepSeek when address gate fails."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from core.llm import LLMClient
from core.logger import RunLogger

DEFAULT_TUNING_PATH = Path(__file__).resolve().parent.parent / "data" / "pipeline_tuning.json"

DEFAULT_TUNING: dict[str, Any] = {
    "version": 1,
    "phase1": {"website_min_confidence": 85, "extra_search_queries": []},
    "phase2": {"fb_min_confidence": 85, "extra_search_queries": []},
    "phase4": {
        "address_accept_confidence": 75,
        "gmaps_min_match_confidence": 85,
        "gsearch_min_match_confidence": 75,
        "extra_gmaps_queries": [],
        "extra_gsearch_queries": [],
        "disabled_sources": [],
    },
    "history": [],
}


def load_tuning(path: Path | None = None) -> dict[str, Any]:
    tuning_path = path or DEFAULT_TUNING_PATH
    if not tuning_path.exists():
        return copy.deepcopy(DEFAULT_TUNING)
    with tuning_path.open(encoding="utf-8") as f:
        data = json.load(f)
    out = copy.deepcopy(DEFAULT_TUNING)
    for key, val in data.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = {**out[key], **val}
        else:
            out[key] = val
    return out


def save_tuning(path: Path, tuning: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(tuning, f, indent=2)


def phase_tuning(tuning: dict[str, Any], phase: str) -> dict[str, Any]:
    return dict(tuning.get(phase, {}))


def format_query_templates(templates: list[str], row) -> list[str]:
    """Expand tuning query templates using row fields."""
    county = str(row.get("county", "")).title()
    subs = {
        "business": str(row.get("business_name_raw", "")),
        "county": county,
        "owner": str(row.get("owner_var_1", "") or row.get("owner_name_raw", "")),
        "biz1": str(row.get("biz_var_1", "")),
        "biz2": str(row.get("biz_var_2", "")),
        "combo": str(row.get("combo_var_1", "")),
    }
    out: list[str] = []
    for template in templates:
        try:
            out.append(str(template).format(**subs))
        except (KeyError, ValueError):
            out.append(str(template))
    return out


def suggest_tuning_change(
    batch_summary: dict[str, Any],
    current_tuning: dict[str, Any],
    logger: RunLogger,
) -> tuple[dict[str, Any], str]:
    """Ask DeepSeek for one config change. Returns (updated_tuning, rationale)."""
    client = LLMClient.from_provider("deepseek", logger)
    system = (
        "You tune a Texas HVAC contractor enrichment pipeline. "
        "Respond with JSON only: {\"phase\": \"phase1|phase2|phase4\", "
        "\"field\": \"snake_case_field_name\", \"value\": <new_value>, "
        "\"rationale\": \"one sentence\"}. "
        "Allowed fields: phase1.website_min_confidence (int 50-95), "
        "phase1.extra_search_queries (list of strings with {business},{county},{owner} placeholders), "
        "phase2.fb_min_confidence (int 50-95), phase2.extra_search_queries (list), "
        "phase4.address_accept_confidence (int 50-95), "
        "phase4.gmaps_min_match_confidence (int 50-95), "
        "phase4.gsearch_min_match_confidence (int 50-95), "
        "phase4.extra_gmaps_queries (list), phase4.extra_gsearch_queries (list), "
        "phase4.disabled_sources (list, remove a source to enable more aggressive search). "
        "Valid disabled_sources entries: website, facebook, gmaps, gsearch, opencorporates, county_cad. "
        "Propose exactly ONE change most likely to raise mailing-address hit rate."
    )
    user = json.dumps(
        {
            "batch_summary": batch_summary,
            "current_tuning": {
                k: current_tuning.get(k)
                for k in ("phase1", "phase2", "phase4")
            },
        },
        indent=2,
    )
    raw = client._chat(system, user)
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        proposal = json.loads(raw[start:end])
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"DeepSeek tuning response not valid JSON: {raw[:500]}") from exc

    phase = str(proposal.get("phase", "phase4"))
    field = str(proposal.get("field", ""))
    value = proposal.get("value")
    rationale = str(proposal.get("rationale", "DeepSeek tuning adjustment"))

    updated = copy.deepcopy(current_tuning)
    if phase not in updated:
        updated[phase] = {}
    updated[phase][field] = value

    history = list(updated.get("history", []))
    history.append(
        {
            "batch_number": batch_summary.get("batch_number"),
            "phase": phase,
            "field": field,
            "value": value,
            "rationale": rationale,
            "address_rate_pct": batch_summary.get("address_rate_pct"),
        }
    )
    updated["history"] = history[-30:]
    return updated, rationale
