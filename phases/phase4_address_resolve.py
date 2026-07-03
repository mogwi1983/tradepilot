"""Phase 4 — Address Resolution (free sources only)."""

from __future__ import annotations

import pandas as pd

from core.browser import BrowserSession
from core.config import RunConfig
from core.csv_io import ensure_columns, phase_complete, update_record, write_csv
from core.llm import get_llm_client
from core.logger import RunLogger
from core.tuning import format_query_templates, load_tuning, phase_tuning
from core.utils import display_name, is_blank, is_pobox, now_iso


def _gmaps_queries(row: pd.Series) -> list[str]:
    county = str(row.get("county", "")).title()
    return [
        f"{row.get('business_name_raw', '')} {county} TX",
        f"{row.get('biz_var_1', '')} {county} TX",
        f"{row.get('biz_var_2', '')} {county} TX",
        f"{row.get('combo_var_1', '')} TX",
        f"{row.get('owner_var_1', '')} HVAC {county} TX",
    ]


def _gsearch_queries(row: pd.Series) -> list[str]:
    county = str(row.get("county", "")).title()
    return [
        f"{row.get('business_name_raw', '')} address",
        f"{row.get('biz_var_1', '')} {county} TX address",
        f"{row.get('biz_var_2', '')} contact TX",
        f"{row.get('combo_var_1', '')} address TX",
        f"{row.get('owner_var_1', '')} HVAC {county} TX",
    ]


def _candidate_from_extracted(extracted: dict, source: str, url: str) -> dict | None:
    if not extracted:
        return None
    conf = int(extracted.get("confidence", 0) or 0)
    full = extracted.get("full") or ", ".join(
        p for p in [extracted.get("street"), extracted.get("city"), extracted.get("state"), extracted.get("zip")] if p
    )
    if not full.strip():
        return None
    return {
        "address_raw": full,
        "address_source": source,
        "address_source_url": url,
        "address_confidence_%": str(conf),
        "address_type_guess": extracted.get("address_type", "unknown"),
    }


def run(df: pd.DataFrame, config: RunConfig, logger: RunLogger) -> pd.DataFrame:
    logger.set_phase("phase4")
    df = ensure_columns(
        df,
        [
            "address_found",
            "address_raw",
            "address_source",
            "address_source_url",
            "address_confidence_%",
            "address_type_guess",
            "address_is_pobox",
            "address_attempt_log",
            "address_source_count",
            "address_conflict_detected",
            "phase4_timestamp",
        ],
    )

    browser = BrowserSession(logger)
    llm = get_llm_client(logger)
    name_fn = display_name
    tuning = load_tuning(config.pipeline_tuning_path)
    p4 = phase_tuning(tuning, "phase4")
    disabled = {str(s).lower() for s in p4.get("disabled_sources", [])}
    accept_conf = int(p4.get("address_accept_confidence", 75))
    gmaps_match = int(p4.get("gmaps_min_match_confidence", 85))
    gsearch_match = int(p4.get("gsearch_min_match_confidence", 75))

    try:
        for _, row in df.iterrows():
            lic = str(row["license_number"])
            if phase_complete(row, 4) or not is_blank(row.get("address_found")):
                continue
            if config.resume_from_record and lic != str(config.resume_from_record):
                continue

            log: list[str] = []
            candidates: list[dict] = []
            name = name_fn(row)

            # Source 1 — website
            if (
                "website" not in disabled
                and str(row.get("website_y/n", "")).upper() == "Y"
                and row.get("website_url")
            ):
                url = str(row["website_url"])
                try:
                    page = browser.fetch_page(url)
                    for path_suffix in ("", "/contact", "/about", "/service-area"):
                        fetch_url = url.rstrip("/") + path_suffix if path_suffix else url
                        if path_suffix:
                            page = browser.fetch_page(fetch_url)
                        extracted = llm.extract_address(page.text, name)
                        cand = _candidate_from_extracted(extracted, "website", fetch_url)
                        log.append(f"website|url={fetch_url}|found={bool(cand)}")
                        if cand and int(cand["address_confidence_%"]) >= 75:
                            candidates.append(cand)
                            break
                    if candidates:
                        pass
                except Exception as exc:
                    log.append(f"website|error={exc}")

            # Source 2 — Facebook
            if (
                "facebook" not in disabled
                and not candidates
                and str(row.get("fb_y/n", "")).upper() == "Y"
                and row.get("fb_url")
            ):
                url = str(row["fb_url"])
                try:
                    page = browser.fetch_page(url)
                    extracted = llm.extract_address(page.text, name)
                    cand = _candidate_from_extracted(extracted, "facebook", url)
                    log.append(f"facebook|url={url}|found={bool(cand)}")
                    if cand and int(cand["address_confidence_%"]) >= 75:
                        candidates.append(cand)
                except Exception as exc:
                    log.append(f"facebook|error={exc}")

            # Source 3 — Google Maps / GBP via search
            if "gmaps" not in disabled and not candidates:
                for q in _gmaps_queries(row) + format_query_templates(
                    p4.get("extra_gmaps_queries", []), row
                ):
                    q = " ".join(str(q).split())
                    try:
                        for r in browser.search(f"{q} maps"):
                            if "google.com/maps" not in r.url.lower():
                                continue
                            ctx = f"{r.title} {r.snippet}"
                            conf = llm.score_match(r.title, name, ctx)
                            extracted = llm.extract_address(ctx, name)
                            cand = _candidate_from_extracted(extracted, "gmaps", r.url)
                            log.append(f"gmaps|query={q}|conf={conf}|found={bool(cand)}")
                            if cand and conf >= gmaps_match:
                                cand["address_confidence_%"] = str(max(int(cand["address_confidence_%"]), conf))
                                candidates.append(cand)
                                break
                        if candidates:
                            break
                    except Exception as exc:
                        log.append(f"gmaps|query={q}|error={exc}")

            # Source 4 — Google search
            if "gsearch" not in disabled and not candidates:
                for q in _gsearch_queries(row) + format_query_templates(
                    p4.get("extra_gsearch_queries", []), row
                ):
                    q = " ".join(str(q).split())
                    try:
                        for r in browser.search(q):
                            conf = llm.score_match(r.title, name, r.snippet)
                            extracted = llm.extract_address(f"{r.title}\n{r.snippet}", name)
                            cand = _candidate_from_extracted(extracted, "gsearch", r.url)
                            log.append(f"gsearch|query={q}|conf={conf}|found={bool(cand)}")
                            if cand and conf >= gsearch_match:
                                cand["address_confidence_%"] = str(max(int(cand["address_confidence_%"]), conf))
                                candidates.append(cand)
                                break
                        if candidates:
                            break
                    except Exception as exc:
                        log.append(f"gsearch|query={q}|error={exc}")

            # Source 5 — Public records (TX SOS / county appraisal)
            if not candidates:
                # 5a — OpenCorporates (aggregates TX SOS registered-agent data)
                biz = str(row.get("business_name_raw", "")).strip()
                if biz and "opencorporates" not in disabled:
                    oc_q = f"opencorporates.com {biz} Texas"
                    try:
                        for r in browser.search(oc_q):
                            if "opencorporates.com" in r.url.lower():
                                page = browser.fetch_page(r.url)
                                extracted = llm.extract_address(page.text, biz)
                                cand = _candidate_from_extracted(extracted, "opencorporates", r.url)
                                log.append(f"opencorporates|url={r.url}|found={bool(cand)}")
                                if cand and int(cand["address_confidence_%"]) >= 70:
                                    candidates.append(cand)
                                    break
                    except Exception as exc:
                        log.append(f"opencorporates|error={exc}")

                # 5b — County appraisal district search
                if not candidates and "county_cad" not in disabled:
                    county = str(row.get("county", "")).strip().lower()
                    owner = str(row.get("owner_name_raw", "")).strip()
                    cad_urls = {
                        "tarrant": "https://www.tad.org",
                        "dallas": "https://www.dallascad.org",
                        "denton": "https://www.dentoncad.com",
                        "collin": "https://www.collincad.org",
                        "johnson": "https://www.johnsoncad.org",
                        "ellis": "https://www.elliscad.com",
                        "harris": "https://www.hcad.org",
                        "travis": "https://www.traviscad.org",
                        "bexar": "https://www.bcad.org",
                    }
                    cad_base = cad_urls.get(county)
                    if cad_base and owner:
                        cad_q = f"site:{cad_base} {owner}"
                        if biz:
                            cad_q = f"site:{cad_base} {owner} {biz[:40]}"
                        try:
                            for r in browser.search(cad_q):
                                if cad_base.replace("https://", "").replace("http://", "") in r.url.lower():
                                    page = browser.fetch_page(r.url)
                                    extracted = llm.extract_address(page.text, owner)
                                    cand = _candidate_from_extracted(extracted, "county_cad", r.url)
                                    log.append(f"county_cad|url={r.url}|found={bool(cand)}")
                                    if cand and int(cand["address_confidence_%"]) >= 70:
                                        candidates.append(cand)
                                        break
                        except Exception as exc:
                            log.append(f"county_cad|error={exc}")

            if candidates:
                best = max(candidates, key=lambda c: int(c["address_confidence_%"]))
                unique_addrs = {c["address_raw"].strip().lower() for c in candidates}
                conflict = len(unique_addrs) > 1
                found = "Y" if int(best["address_confidence_%"]) >= accept_conf else "UNCERTAIN"
                updates = {
                    "address_found": found,
                    "address_raw": best["address_raw"],
                    "address_source": best["address_source"],
                    "address_source_url": best["address_source_url"],
                    "address_confidence_%": best["address_confidence_%"],
                    "address_type_guess": best.get("address_type_guess", "unknown"),
                    "address_is_pobox": str(is_pobox(best["address_raw"])).lower(),
                    "address_attempt_log": "|".join(log),
                    "address_source_count": str(len(unique_addrs)),
                    "address_conflict_detected": str(conflict).lower(),
                    "phase4_timestamp": now_iso(),
                }
            else:
                updates = {
                    "address_found": "N",
                    "address_raw": "",
                    "address_source": "",
                    "address_source_url": "",
                    "address_confidence_%": "0",
                    "address_type_guess": "unknown",
                    "address_is_pobox": "false",
                    "address_attempt_log": "|".join(log) if log else "no_candidates",
                    "address_source_count": "0",
                    "address_conflict_detected": "false",
                    "phase4_timestamp": now_iso(),
                }

            df = update_record(df, lic, updates, phase=4)
            write_csv(df, config.output_path)
            logger.info(f"address_found={updates['address_found']}", license_number=lic)
    finally:
        browser.close()

    return df
