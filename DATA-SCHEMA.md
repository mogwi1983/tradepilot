# TradePilot — Data Schema

## Working File

All phases read from and write to a single working CSV file.
The file is defined in `run_config.json` as `output_file`.

Each phase appends its own columns to the file without touching columns owned by other phases.

---

## Source Columns (from TDLR export — do not modify)

| Column | Type | Notes |
|---|---|---|
| `license_number` | string | Primary key. Use for deduplication. |
| `license_subtype` | string | BE, BC, BR, AEBR, ARBE (in-scope for this pipeline) |
| `county` | string | County as reported by TDLR |
| `owner_name_raw` | string | Qualifier/owner name from TDLR |
| `business_name_raw` | string | Business name from TDLR. May be blank — fall back to owner_name_raw. |

---

## Name Variation Columns (pre-generated — do not modify)

These columns are pre-populated in the working CSV. Phases use these for search queries.
Do not regenerate or overwrite these values.

| Column | Type | Notes |
|---|---|---|
| `owner_var_1` | string | Owner name variation 1 (last, first format) |
| `owner_var_2` | string | Owner name variation 2 (first last, no middle) |
| `biz_var_1` | string | Business name stripped of legal suffixes (LLC, Inc, Co, etc.) |
| `biz_var_2` | string | Business name with HVAC/AC/air conditioning substitution |
| `biz_var_3` | string | Business name, first word only |
| `biz_var_4` | string | Business name, lowercase, no punctuation |
| `combo_var_1` | string | Owner last name + city/county |
| `combo_var_2` | string | Owner last name + trade keyword |
| `combo_var_3` | string | Business short name + county |
| `combo_var_4` | string | Owner first name + business short name |

---

## Phase 0 Columns

| Column | Type | Allowed Values | Notes |
|---|---|---|---|
| `run_id` | string | any | Unique identifier for this pipeline run |
| `batch1_excluded` | boolean | true / false | True if record was in a prior batch pipeline |
| `phase0_timestamp` | datetime | ISO 8601 | When this record was processed in Phase 0 |

---

## Phase 1 Columns — Website Detection

| Column | Type | Allowed Values | Notes |
|---|---|---|---|
| `website_y/n` | string | Y / N / UNCERTAIN | Never blank after Phase 1 runs |
| `website_url` | string | URL or blank | Only populated if website_y/n = Y |
| `website_confidence_%` | integer | 0–100 | Confidence that the found site belongs to this contractor |
| `website_search_notes` | string | pipe-delimited text | Log of all search attempts and outcomes |
| `phase1_timestamp` | datetime | ISO 8601 | |

**Rules:**
- `website_y/n` must never be blank after Phase 1 completes for a record
- A confidence below 85% should result in UNCERTAIN, not Y
- Directory listings (Yelp, Angi, GBP, Facebook) must not be logged as Y

---

## Phase 2 Columns — Facebook Detection

| Column | Type | Allowed Values | Notes |
|---|---|---|---|
| `fb_y/n` | string | Y / N / UNCERTAIN | Never blank after Phase 2 runs |
| `fb_url` | string | URL or blank | Only populated if fb_y/n = Y |
| `fb_page_name` | string | text or blank | Name shown on the Facebook page |
| `fb_last_post_date` | string | date or "no posts" or blank | Most recent post date |
| `fb_confidence_%` | integer | 0–100 | Confidence that the page belongs to this contractor |
| `fb_search_notes` | string | pipe-delimited text | Log of all search attempts and outcomes |
| `phase2_timestamp` | datetime | ISO 8601 | |

**Rules:**
- Personal Facebook profiles must not be counted as business pages
- Confidence 60–84% must be logged as UNCERTAIN with explanation in fb_search_notes
- `fb_y/n` must never be blank after Phase 2 completes for a record

---

## Phase 3 Columns — Other Presence Detection

| Column | Type | Allowed Values | Notes |
|---|---|---|---|
| `gbp_found` | string | Y / N | Google Business Profile found |
| `gbp_claimed` | string | Y / N / UNKNOWN | Whether GBP profile is claimed |
| `gbp_review_count` | integer | 0+ or blank | Number of GBP reviews if found |
| `yelp_found` | string | Y / N | |
| `angi_found` | string | Y / N | |
| `other_presence_types` | string | pipe-delimited list | All platforms where presence was detected |
| `other_presence_notes` | string | text | Notes on other presence findings |
| `phase3_timestamp` | datetime | ISO 8601 | |

---

## Phase 4 Columns — Address Resolution

| Column | Type | Allowed Values | Notes |
|---|---|---|---|
| `address_found` | string | Y / N / UNCERTAIN | Never blank after Phase 4 runs |
| `address_raw` | string | text or blank | Address text exactly as found, not normalized |
| `address_source` | string | website / facebook / gmaps / gsearch / blank | Which source produced the candidate |
| `address_source_url` | string | URL or blank | URL where address was found |
| `address_confidence_%` | integer | 0–100 | Confidence that address belongs to this contractor |
| `address_type_guess` | string | residential / commercial / unknown | Based on address characteristics |
| `address_is_pobox` | boolean | true / false | True if address appears to be a PO Box or PMB |
| `address_attempt_log` | string | pipe-delimited text | Every source attempted, every result reviewed, every rejection reason |
| `address_source_count` | integer | 0+ | How many independent sources returned an address |
| `address_conflict_detected` | boolean | true / false | True if two sources returned meaningfully different addresses |
| `phase4_timestamp` | datetime | ISO 8601 | |

**Rules:**
- `address_attempt_log` must be populated for every record, even if nothing was found
- `address_found = N` is only valid after the full free ladder has been attempted
- PO Box addresses must be flagged in `address_is_pobox` but not automatically excluded
- If two sources disagree on address, set `address_conflict_detected = true` and log both in `address_attempt_log`

---

## Phase 5 Columns — Lob Verification

| Column | Type | Allowed Values | Notes |
|---|---|---|---|
| `lob_verified` | boolean | true / false | Whether Lob API was called for this record |
| `lob_deliverability` | string | deliverable / deliverable_missing_unit / deliverable_incorrect_unit / undeliverable / not_called | not_called if no address candidate exists |
| `lob_standardized_address` | string | text or blank | USPS-standardized address from Lob |
| `lob_address_type` | string | residential / commercial / blank | Lob classification |
| `lob_vacancy` | string | vacant / not_vacant / unknown / blank | Lob vacancy flag |
| `lob_verification_timestamp` | datetime | ISO 8601 or blank | |

**Rules:**
- `lob_verified = false` and `lob_deliverability = not_called` are valid for records with no address candidate
- Never call Lob for a record where `address_found = N`
- Lob budget must be tracked in `data/lob_budget.json`
- `lob_deliverability = undeliverable` means the record is not mail-ready — period

---

## Phase 7 Columns — Batch Classification

| Column | Type | Allowed Values | Notes |
|---|---|---|---|
| `batch_assignment` | string | batch_1 / batch_2 / excluded / unresolved | Never blank after Phase 7 |
| `lob_ready` | boolean | true / false | True only if Lob returned deliverable and address is not vacant |
| `exclusion_reason` | string | has_website / inactive_license / out_of_geography / duplicate / conflicting_evidence / blank | Required if batch_assignment = excluded |
| `unresolved_reason` | string | text or blank | Required if batch_assignment = unresolved |
| `confidence_score` | integer | 0–100 | Composite score per rubric in ARCHITECTURE.md |
| `confidence_tier` | string | A / B / C | A=75+, B=50–74, C=0–49 |
| `phase7_timestamp` | datetime | ISO 8601 | |

---

## Lob Budget File

Path: `data/lob_budget.json`

```json
{
  "total_free_verifications": 300,
  "used": 0,
  "remaining": 300,
  "last_updated": "2026-07-02T00:00:00Z",
  "runs": []
}
```

This file must be updated after every Phase 5 run.
It is the authoritative count of remaining free verifications.
If `remaining = 0`, Phase 5 must halt and log a warning before any API call is made.

---

## Confidence Score Rubric

Used in Phase 7. Add up all applicable points. Cap at 100.

**Address evidence (max 40 pts):**
- `address_source_count = 0`: +0
- `address_source_count = 1`: +15
- `address_source_count = 2`: +25
- `address_source_count >= 3`: +35
- No conflict AND source count ≥ 2: +5 bonus
- Full address complete (all fields): +5 bonus
- `address_type_guess = residential`: -5

**Lob verification (max 25 pts):**
- `lob_deliverability = deliverable`: +25
- `lob_deliverability = deliverable_missing_unit`: +10
- `lob_deliverability = undeliverable`: +0
- `lob_deliverability = not_called`: +0
- `lob_vacancy = vacant`: -15

**ICP alignment (max 20 pts):**
- `batch_assignment = batch_1 or batch_2`: +20
- `batch_assignment = unresolved`: +5
- `batch_assignment = excluded`: +0

**Penalties:**
- `address_conflict_detected = true` AND unresolved: -10
- `website_y/n = Y` (should be excluded): -20
- `fb_confidence_% < 60` AND `fb_y/n = Y`: -5

