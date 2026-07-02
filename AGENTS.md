# Agent Guide — TradePilot

**You are building a Python CLI pipeline, not a web app.** Read this file first; drill into linked docs only when your task requires it.

## Build order

1. **Read** `PROJECT.md` (1 min) — confirm scope: Texas HVAC, TDLR, CSV pipeline.
2. **Read** `ARCHITECTURE.md` — phase definitions, column ownership, resumability rules.
3. **Read** `DATA-SCHEMA.md` — before touching any CSV column.
4. **Implement** per `CURSOR-BOOTSTRAP.md` — full spec for core modules + phases.

## Where things go

| Task | Location | Notes |
|---|---|---|
| Run configuration | `run_config.json` | Single active config at repo root |
| Drop raw / seed CSVs | `data/source/` | Committed seed data lives here |
| Phase working output | `data/output/` | Gitignored except `.gitkeep` |
| Lob verification counter | `data/lob_budget.json` | Phase 5 updates after each call |
| Shared utilities | `core/` | All phases import from here — no cross-phase imports |
| Pipeline steps | `phases/phase{N}_*.py` | One file per phase, sequential 0→8 |
| Run logs + QA reports | `runs/{run_id}/` | Created at runtime, gitignored |
| Entry point | `main.py` | Loads config, runs phases in order |
| API keys | `.env.local` | Never commit; see `.env.example` |

## Hard rules (do not violate)

- **Column ownership:** Each phase writes only its columns (see ARCHITECTURE.md table). Use `core/csv_io.py` to enforce.
- **Resumability:** Never overwrite a non-blank phase column unless `force=True`. Save CSV after every record.
- **No silent failures:** Log and continue or halt with reason — never leave Y/N fields blank after a phase runs.
- **No paid APIs in Phase 4 or 6:** Free address ladder only in Phase 4; escalation CSV only in Phase 6.
- **Lob budget:** Check `data/lob_budget.json` before every Lob call. Halt at 0 remaining.
- **No agent frameworks:** Plain Python scripts — no LangChain, no orchestration LLM.

## Phase cheat sheet

| Phase | File | Input → adds columns for |
|---|---|---|
| 0 | `phase0_filter.py` | Filter universe → `run_id`, `batch1_excluded` |
| 1 | `phase1_website.py` | Website detection → `website_*` |
| 2 | `phase2_facebook.py` | Facebook detection → `fb_*` |
| 3 | `phase3_other_presence.py` | GBP, Yelp, etc. → `gbp_*`, `other_*` |
| 4 | `phase4_address_resolve.py` | Free address ladder → `address_*` |
| 5 | `phase5_lob_verify.py` | USPS verify → `lob_*` |
| 6 | `phase6_escalation.py` | Export `escalation_queue_{run_id}.csv` |
| 7 | `phase7_classify.py` | Batch assignment → `batch_assignment`, `confidence_*` |
| 8 | `phase8_qa.py` | Write `qa_report_{run_id}.md` |

## Seed data note

`data/source/batch1_search_log_results.csv` is a pre-enriched working file (~1,900 records) with name-variation columns and partial prior search columns. Phase 0 may filter it; later phases should respect existing non-blank values (resumability).

## What NOT to build (MVP)

- Web UI, REST API, database, Docker, LangChain/LlamaIndex
- Paid enrichment without human approval (Phase 6 queue only)

## Subdirectory READMEs

- [data/README.md](data/README.md) — file paths and data flow
- [core/README.md](core/README.md) — module responsibilities
- [phases/README.md](phases/README.md) — phase interface contract
- [runs/README.md](runs/README.md) — log and report conventions
