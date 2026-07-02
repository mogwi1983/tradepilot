"""
Side-by-side LLM comparison: MiniMax M2.7 vs DeepSeek on the first N records.

Runs browser searches once, then calls both providers on identical inputs.
Does NOT modify the pipeline working CSV.

Usage:
  python compare_llm.py
  python compare_llm.py --limit 20
  python compare_llm.py --record 2151
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from core.browser import BrowserSession
from core.config import load_run_config
from core.csv_io import read_csv
from core.env import load_env
from core.llm import LLMClient
from core.logger import get_logger
from core.utils import display_name, is_probable_website, now_iso
from phases.phase1_website import _search_bundle as website_queries
from phases.phase2_facebook import _is_fb_url, _search_bundle as facebook_queries

DEFAULT_LIMIT = 20


@dataclass
class TaskResult:
    task: str
    license_number: str
    business_name: str
    input_summary: str
    minimax_value: str
    deepseek_value: str
    minimax_conf: int | None = None
    deepseek_conf: int | None = None
    agree: bool = False
    delta: int | None = None


@dataclass
class ComparisonRun:
    results: list[TaskResult] = field(default_factory=list)
    minimax_tokens: int = 0
    deepseek_tokens: int = 0
    minimax_calls: int = 0
    deepseek_calls: int = 0


def _website_verdict(conf: int) -> str:
    if conf >= 85:
        return "Y"
    if conf >= 60:
        return "UNCERTAIN"
    return "N"


def _best_website(
    browser: BrowserSession,
    minimax: LLMClient,
    deepseek: LLMClient,
    row: pd.Series,
    name: str,
) -> tuple[dict, dict]:
    """Return best (url, conf, yn) per provider from shared search results."""
    mm_best = {"url": "", "conf": 0, "yn": "N"}
    ds_best = {"url": "", "conf": 0, "yn": "N"}
    candidates: list[tuple[str, str]] = []

    for q in website_queries(row):
        q = " ".join(str(q).split())
        if len(q) < 4:
            continue
        try:
            for r in browser.search(q):
                if not is_probable_website(r.url):
                    continue
                ctx = f"Title: {r.title}\nSnippet: {r.snippet}\nURL: {r.url}"
                candidates.append((r.url, ctx))
        except Exception:
            continue

    seen: set[str] = set()
    for url, ctx in candidates:
        if url in seen:
            continue
        seen.add(url)
        mm_conf = minimax.score_match(url, name, ctx)
        ds_conf = deepseek.score_match(url, name, ctx)
        if mm_conf > mm_best["conf"]:
            mm_best = {"url": url, "conf": mm_conf, "yn": _website_verdict(mm_conf)}
        if ds_conf > ds_best["conf"]:
            ds_best = {"url": url, "conf": ds_conf, "yn": _website_verdict(ds_conf)}

    return mm_best, ds_best


def _best_facebook(
    browser: BrowserSession,
    minimax: LLMClient,
    deepseek: LLMClient,
    row: pd.Series,
    name: str,
) -> tuple[dict, dict]:
    mm_best = {"url": "", "conf": 0, "yn": "N"}
    ds_best = {"url": "", "conf": 0, "yn": "N"}

    for q in facebook_queries(row):
        q = " ".join(str(q).split())
        if len(q) < 4:
            continue
        try:
            for r in browser.search(q):
                if not _is_fb_url(r.url):
                    continue
                ctx = f"Title: {r.title}\nSnippet: {r.snippet}"
                mm_conf = minimax.score_match(r.title, name, ctx)
                ds_conf = deepseek.score_match(r.title, name, ctx)
                if mm_conf > mm_best["conf"]:
                    mm_best = {"url": r.url, "conf": mm_conf, "yn": "N"}
                if ds_conf > ds_best["conf"]:
                    ds_best = {"url": r.url, "conf": ds_conf, "yn": "N"}
        except Exception:
            continue

    for label, best, llm in [("mm", mm_best, minimax), ("ds", ds_best, deepseek)]:
        if best["url"] and best["conf"] >= 60:
            try:
                page = browser.fetch_page(best["url"])
                yn, conf = llm.classify_fb_page(page.text, name)
                best["yn"] = yn
                best["conf"] = max(conf, best["conf"])
            except Exception:
                if best["conf"] >= 85:
                    best["yn"] = "Y"
                elif best["conf"] >= 60:
                    best["yn"] = "UNCERTAIN"

    return mm_best, ds_best


def _address_sample(
    browser: BrowserSession,
    minimax: LLMClient,
    deepseek: LLMClient,
    row: pd.Series,
    name: str,
    website_url: str,
) -> tuple[dict, dict]:
    if not website_url:
        return {}, {}
    try:
        page = browser.fetch_page(website_url)
    except Exception:
        return {}, {}
    mm = minimax.extract_address(page.text, name)
    ds = deepseek.extract_address(page.text, name)
    return mm, ds


def compare_record(
    row: pd.Series,
    browser: BrowserSession,
    minimax: LLMClient,
    deepseek: LLMClient,
    logger,
) -> list[TaskResult]:
    lic = str(row["license_number"])
    name = display_name(row)
    out: list[TaskResult] = []

    logger.info(f"Comparing record {lic} — {name}")
    mm_web, ds_web = _best_website(browser, minimax, deepseek, row, name)
    out.append(
        TaskResult(
            task="website_yn",
            license_number=lic,
            business_name=name,
            input_summary=f"best_url mm={mm_web['url'][:80]} ds={ds_web['url'][:80]}",
            minimax_value=mm_web["yn"],
            deepseek_value=ds_web["yn"],
            minimax_conf=mm_web["conf"],
            deepseek_conf=ds_web["conf"],
            agree=mm_web["yn"] == ds_web["yn"],
            delta=abs(mm_web["conf"] - ds_web["conf"]),
        )
    )

    mm_fb, ds_fb = _best_facebook(browser, minimax, deepseek, row, name)
    out.append(
        TaskResult(
            task="facebook_yn",
            license_number=lic,
            business_name=name,
            input_summary=f"mm_url={mm_fb['url'][:60]} ds_url={ds_fb['url'][:60]}",
            minimax_value=mm_fb["yn"],
            deepseek_value=ds_fb["yn"],
            minimax_conf=mm_fb["conf"],
            deepseek_conf=ds_fb["conf"],
            agree=mm_fb["yn"] == ds_fb["yn"],
            delta=abs(mm_fb["conf"] - ds_fb["conf"]),
        )
    )

    web_url = mm_web["url"] or ds_web["url"]
    mm_addr, ds_addr = _address_sample(browser, minimax, deepseek, row, name, web_url)
    mm_full = mm_addr.get("full", "")
    ds_full = ds_addr.get("full", "")
    mm_conf = int(mm_addr.get("confidence", 0) or 0) if mm_addr else 0
    ds_conf = int(ds_addr.get("confidence", 0) or 0) if ds_addr else 0
    out.append(
        TaskResult(
            task="address_extract",
            license_number=lic,
            business_name=name,
            input_summary=web_url[:80] if web_url else "no_website",
            minimax_value=mm_full or "none",
            deepseek_value=ds_full or "none",
            minimax_conf=mm_conf,
            deepseek_conf=ds_conf,
            agree=(mm_full.lower() == ds_full.lower()) if mm_full and ds_full else mm_full == ds_full,
            delta=abs(mm_conf - ds_conf),
        )
    )

    return out


def write_report(
    run: ComparisonRun,
    out_dir: Path,
    *,
    limit: int,
    run_id: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = now_iso()

    rows = []
    for r in run.results:
        rows.append(
            {
                "license_number": r.license_number,
                "business_name": r.business_name,
                "task": r.task,
                "input_summary": r.input_summary,
                "minimax_value": r.minimax_value,
                "deepseek_value": r.deepseek_value,
                "minimax_conf": r.minimax_conf,
                "deepseek_conf": r.deepseek_conf,
                "agree": r.agree,
                "conf_delta": r.delta,
            }
        )
    detail_path = out_dir / "comparison_detail.csv"
    pd.DataFrame(rows).to_csv(detail_path, index=False)

    by_task: dict[str, list[TaskResult]] = {}
    for r in run.results:
        by_task.setdefault(r.task, []).append(r)

    lines = [
        f"# LLM Comparison — MiniMax M2.7 vs DeepSeek",
        "",
        f"- Run ID: `{run_id}`",
        f"- Records compared: **{limit}**",
        f"- Generated: {ts}",
        f"- Detail CSV: `comparison_detail.csv`",
        "",
        "## Token usage",
        f"- MiniMax: {run.minimax_tokens} tokens, {run.minimax_calls} calls",
        f"- DeepSeek: {run.deepseek_tokens} tokens, {run.deepseek_calls} calls",
        "",
        "## Agreement summary",
    ]

    total_agree = sum(1 for r in run.results if r.agree)
    lines.append(f"- Overall agreement: **{total_agree}/{len(run.results)}** ({100*total_agree/max(len(run.results),1):.0f}%)")
    lines.append("")

    for task, items in sorted(by_task.items()):
        agree = sum(1 for i in items if i.agree)
        deltas = [i.delta for i in items if i.delta is not None]
        avg_delta = sum(deltas) / len(deltas) if deltas else 0
        lines.append(f"### {task}")
        lines.append(f"- Agreement: {agree}/{len(items)}")
        lines.append(f"- Avg confidence delta: {avg_delta:.1f}")
        disagreements = [i for i in items if not i.agree]
        if disagreements:
            lines.append("- Disagreements:")
            for d in disagreements[:10]:
                lines.append(
                    f"  - `{d.license_number}` minimax={d.minimax_value}({d.minimax_conf}) "
                    f"deepseek={d.deepseek_value}({d.deepseek_conf})"
                )
        lines.append("")

    lines.extend(
        [
            "## Recommendation",
            "If agreement ≥ 85% and avg confidence delta < 15, MiniMax M2.7 is safe as default.",
            "Review disagreements in `comparison_detail.csv` before full pilot run.",
            "",
            "## Next step",
            "Set `LLM_PROVIDER=minimax` in `.env.local` and run: `python main.py`",
        ]
    )

    summary_path = out_dir / "comparison_summary.md"
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {summary_path}")
    print(f"Wrote {detail_path}")
    print("\n".join(lines[:25]))


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(description="MiniMax M2.7 vs DeepSeek comparison experiment")
    parser.add_argument("--config", default="run_config.json")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Records to compare (default 20)")
    parser.add_argument("--record", type=str, default=None, help="Single license_number only")
    args = parser.parse_args(argv)

    config = load_run_config(args.config)
    if not config.output_path.exists():
        print(f"Run phase 0 first — output missing: {config.output_path}", file=sys.stderr)
        return 1

    df = read_csv(config.output_path)
    if args.record:
        df = df[df["license_number"].astype(str) == str(args.record)]
    else:
        df = df.head(args.limit)

    if df.empty:
        print("No records to compare.", file=sys.stderr)
        return 1

    logger = get_logger(config.run_id, config.run_log_dir)
    logger.set_phase("llm_compare")

    minimax = LLMClient.from_provider("minimax", logger)
    deepseek = LLMClient.from_provider("deepseek", logger)
    browser = BrowserSession(logger)
    run = ComparisonRun()

    try:
        for _, row in df.iterrows():
            results = compare_record(row, browser, minimax, deepseek, logger)
            run.results.extend(results)
    finally:
        browser.close()

    run.minimax_tokens = minimax.total_tokens
    run.deepseek_tokens = deepseek.total_tokens
    run.minimax_calls = minimax.call_count
    run.deepseek_calls = deepseek.call_count

    out_dir = config.run_log_dir / "llm_comparison"
    write_report(run, out_dir, limit=len(df), run_id=config.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
