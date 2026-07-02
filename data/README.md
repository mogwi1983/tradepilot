# data/

All pipeline I/O is CSV + one JSON budget file. No database.

## Paths

| Path | Committed? | Purpose |
|---|---|---|
| `source/` | Yes (seed files) | Input CSVs — TDLR exports or pre-enriched working files |
| `output/` | No (gitignored) | Working CSV updated in place by phases; escalation exports |
| `lob_budget.json` | Yes | Persistent Lob free-tier counter — **authoritative** for Phase 5 |

## Data flow

```
data/source/{input}.csv
        │
        ▼  Phase 0 copies/filters
data/output/{output}.csv   ← phases 1–7 append columns here
        │
        ├── Phase 6 → data/output/escalation_queue_{run_id}.csv
        └── Phase 8 → runs/{run_id}/qa_report_{run_id}.md
```

`run_config.json` defines `input_file`, `output_file`, and `lob_budget_file`.

## Agent notes

- **Atomic writes:** Write to `*.tmp` then rename — prevents corrupt CSV on crash.
- **Column schema:** `DATA-SCHEMA.md` is the source of truth. Source + name-variation columns are read-only after ingest.
- **Seed file:** `source/batch1_search_log_results.csv` has legacy columns (`address`, `search_notes`) from a prior attempt — map or migrate to canonical schema when implementing Phase 1+.
- Do not commit files in `output/` except `.gitkeep`.

## Subdirectories

- [source/README.md](source/README.md)
- [output/README.md](output/README.md)
