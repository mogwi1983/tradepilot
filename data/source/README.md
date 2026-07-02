# data/source/

Drop raw TDLR exports or seed working CSVs here.

## Current file

| File | Records | Notes |
|---|---|---|
| `batch1_search_log_results.csv` | ~1,924 | Pre-generated name variations; partial columns from prior search attempt |

## Required source columns (TDLR)

`license_number`, `license_subtype`, `county`, `owner_name_raw`, `business_name_raw`

## Pre-generated columns (do not overwrite)

`owner_var_1` … `combo_var_4` — see `DATA-SCHEMA.md` § Name Variation Columns.

## Agent notes

- Phase 0 reads `run_config.json` → `input_file`, writes filtered rows to `output_file`.
- County values in seed data are UPPERCASE (e.g. `TARRANT`) — normalize in Phase 0 if filtering against mixed-case `target_counties`.
- New runs: place file here, update `input_file` in `run_config.json`.
