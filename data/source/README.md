# data/source/

Drop raw TDLR exports or seed working CSVs here.

## Campaign: 600 initial mailers (3 cohorts x 200)

See `cohort_manifest.json` for full rules.

| Cohort | Profile | Wave 1 target |
|---|---|---|
| `cohort_1` | No Facebook **and** no website | 200 mail-ready addresses |
| `cohort_2` | Has Facebook, **no** website | 200 mail-ready addresses |
| `cohort_3` | Has website (FB optional) | 200 mail-ready addresses |

Overflow beyond 200 mail-ready per cohort -> `mail_wave=wave_2` (second mailer batch).

**Having a website is NOT excluded.** Site owners are `cohort_3`.

## Current file

| File | Records | Notes |
|---|---|---|
| `batch1_search_log_results.csv` | ~1,924 | Name variations + `cohort` / `mail_wave` columns (filled by Phase 7) |

## Required source columns (TDLR)

`license_number`, `license_subtype`, `county`, `owner_name_raw`, `business_name_raw`

## Pre-generated columns (do not overwrite)

`owner_var_1` … `combo_var_4` — see `DATA-SCHEMA.md` § Name Variation Columns.

## Output columns (Phase 7)

`cohort`, `mail_wave`, `batch_assignment` (`batch_1` = wave 1, `batch_2` = overflow)
