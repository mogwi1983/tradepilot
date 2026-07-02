# TradePilot — Pipeline Architecture

## Core Design Philosophy

The pipeline is divided into discrete, sequential phases.
Each phase has one responsibility, defined inputs, defined outputs, and defined failure behavior.
No phase does more than one kind of work.
No phase may proceed past a failure without logging why it failed.

Phases are not "agents." They are structured scripts with browser automation,
API calls, and file I/O. DeepSeek is used for reasoning tasks within phases
(name matching, confidence scoring, evidence interpretation) — not for orchestration.

---

## Technology Stack

| Concern | Tool | Notes |
|---|---|---|
| Language | Python | Primary pipeline language |
| Browser automation | browser-use | Intelligent web navigation for presence detection and address search |
| LLM reasoning | DeepSeek API | Used within phases for matching, scoring, and interpretation |
| Address validation | Lob API | USPS-grade deliverability check — 300 free verifications on current plan |
| Data format | CSV | Single working file updated in place by each phase |
| Config | .env.local | All API keys stored here, never committed |
| Environment | Cursor Pro | Development environment |

---

## Pipeline Phases

```
Phase 0 — Universe Filter
Phase 1 — Website Detection
Phase 2 — Facebook Detection
Phase 3 — Other Presence Detection
Phase 4 — Address Resolution (free sources)
Phase 5 — Lob Address Verification
Phase 6 — Escalation Queue Export
Phase 7 — Batch Classification
Phase 8 — QA Audit
```

Phases run sequentially. Each phase reads from the working CSV and writes results
back into the same file by appending to its designated columns.
Phases do not touch columns owned by other phases.

---

## Phase Definitions

### Phase 0 — Universe Filter

**Purpose:** Produce the working universe of records for a given run.

**Input:** Raw TDLR export CSV

**Filters applied:**
- License status = ACTIVE
- County in target list
- License subtype in scope list (configurable per run)
- Exclude records already in prior batch pipelines

**Output:** Filtered working CSV with all source columns preserved plus:
- `run_id` — unique identifier for this pipeline run
- `phase0_timestamp`
- `batch1_excluded` (true/false)

**Failure behavior:** If input file is missing or column names don't match schema,
halt and log error. Do not proceed.

---

### Phase 1 — Website Detection

**Purpose:** Determine whether a standalone business website exists for each record.

**Input:** Working CSV (phase 0 output)

**For each record, attempt a minimum of 5 distinct searches using browser-use:**

Search bundle (use pre-generated name variations from CSV columns):
1. `business_name_raw` + county + TX
2. `biz_var_1` + county + TX
3. `biz_var_2` + HVAC + TX
4. `combo_var_1` + county + TX
5. `owner_var_1` + HVAC + county + TX

**What counts as a website:**
- A standalone domain (e.g., `smithhvac.com`, `codyac.net`)
- The domain must clearly belong to this contractor
- Match confidence must be 85% or greater

**What does NOT count as a website:**
- Facebook page
- Google Business Profile
- Yelp, Angi, HomeAdvisor, Thumbtack, LinkedIn, Instagram

If a directory listing is found, log it as other presence — not as a website.

**Retry rules:**
- Each retry must use a meaningfully different query (different name variation,
  different keyword, with/without county, etc.)
- Repeating the same query with minor punctuation changes does not count as a retry
- If confidence is 50–74%, retry within the same source before moving on
- If confidence is 75–89%, accept provisionally and run one confirming attempt

**Output columns written:**
- `website_y/n` — Y / N / UNCERTAIN
- `website_url` — URL if found, blank if not
- `website_confidence_%` — integer 0–100
- `website_search_notes` — pipe-delimited log of attempts and outcomes
- `phase1_timestamp`

**Failure behavior:** If no result found after full bundle, write N and log all attempts.
Never leave `website_y/n` blank.

---

### Phase 2 — Facebook Detection

**Purpose:** Determine whether a Facebook business page exists for each record.

**Input:** Working CSV (phase 1 output)

**For each record, attempt a minimum of 5 distinct searches:**

Search bundle:
1. `business_name_raw` site:facebook.com
2. `biz_var_1` site:facebook.com
3. `biz_var_2` + county + Facebook
4. `combo_var_1` site:facebook.com
5. `owner_var_1` + HVAC + Facebook + county + TX

**What counts as Facebook presence:**
- A Facebook business page or local business page
- Name match at 85% confidence or greater
- Must NOT be a personal profile

**What does NOT count:**
- Personal Facebook profiles
- Community posts that mention the business
- Directory pages linking to Facebook

If confidence is 60–84%, mark UNCERTAIN and document why.

**Output columns written:**
- `fb_y/n` — Y / N / UNCERTAIN
- `fb_url` — URL if found, blank if not
- `fb_page_name` — name on the page if found
- `fb_last_post_date` — most recent post date or "no posts"
- `fb_confidence_%` — integer 0–100
- `fb_search_notes` — pipe-delimited log of attempts and outcomes
- `phase2_timestamp`

---

### Phase 3 — Other Presence Detection

**Purpose:** Detect and log any additional digital presence signals.

**Input:** Working CSV (phase 2 output)

**Detect presence on:**
- Google Business Profile (GBP) — claimed or unclaimed
- Yelp
- Angi
- HomeAdvisor
- Thumbtack
- Instagram business page
- LinkedIn company page

**Minimum 4 distinct searches per record.**

These signals do not disqualify a record from Batch 1 or Batch 2 on their own.
They are logged for confidence scoring in Phase 7.

**Output columns written:**
- `gbp_found` — Y / N
- `gbp_claimed` — Y / N / UNKNOWN
- `gbp_review_count` — integer or blank
- `yelp_found` — Y / N
- `angi_found` — Y / N
- `other_presence_types` — pipe-delimited list of platforms found
- `other_presence_notes`
- `phase3_timestamp`

---

### Phase 4 — Address Resolution (Free Sources Only)

**Purpose:** Find a usable mailing address candidate using only free sources.

**Input:** Working CSV (phase 3 output), plus website_url and fb_url if found

**This phase does NOT call Lob. It only finds candidates.**

**Source priority order — stop at first high-confidence result:**

**Source 1 — Known website URL (if website_y/n = Y)**
Check in order:
1. Homepage footer
2. `/contact` page
3. `/about` or `/service-area` page

Stop and pass to Phase 5 if address found at 75%+ confidence.

**Source 2 — Facebook page (if fb_y/n = Y)**
Check:
1. Main page About/Info section
2. Contact tab

Stop and pass to Phase 5 if address found at 75%+ confidence.

**Source 3 — Google Maps / GBP**
Attempt minimum 5 searches:
1. `business_name_raw` + county + TX
2. `biz_var_1` + county + TX
3. `biz_var_2` + county + TX
4. `combo_var_1` + TX
5. `owner_var_1` + HVAC + county + TX

Accept if name matches at 85%+ and address is present.

**Source 4 — Google Search**
Attempt minimum 5 searches:
1. `business_name_raw` + address
2. `biz_var_1` + county + TX + address
3. `biz_var_2` + contact + TX
4. `combo_var_1` + address + TX
5. `owner_var_1` + HVAC + county + TX

Accept only if evidence is concrete and attributable to this contractor.

**Unusable address types — log but flag for human review:**
- PO Box
- PMB (private mailbox)
- UPS Store / Mailboxes Etc.
- Registered agent address
- Obvious filing-only address

**Output columns written:**
- `address_found` — Y / N / UNCERTAIN
- `address_raw` — raw address text as found
- `address_source` — which source produced it (website/facebook/gmaps/gsearch)
- `address_source_url` — URL evidence
- `address_confidence_%` — integer 0–100
- `address_type_guess` — residential / commercial / unknown
- `address_is_pobox` — true / false
- `address_attempt_log` — pipe-delimited log of all attempts
- `address_source_count` — how many independent sources returned an address
- `address_conflict_detected` — true if two sources returned different addresses
- `phase4_timestamp`

**Escalation trigger:**
If `address_found = N` after full free ladder, flag record for Phase 6 escalation queue.

---

### Phase 5 — Lob Address Verification

**Purpose:** USPS-validate address candidates found in Phase 4.

**Input:** Working CSV, filtered to records where `address_found = Y`

**Budget rule:**
- Total free verifications: 300
- Track count across all runs in a persistent `lob_budget.json` file
- If remaining verifications = 0, halt and log. Do not exceed the free tier automatically.
- If fewer than 50 remain, log a warning before continuing.

**Priority order for spending verifications:**
1. Addresses sourced from website or Facebook (highest confidence source)
2. Addresses sourced from Google Maps / GBP
3. Addresses sourced from Google Search
4. Partial address candidates flagged UNCERTAIN

Do NOT call Lob for records with no address candidate.
Do NOT call Lob for known PO Box addresses without human review first.

**Lob API call:**
POST to `https://api.lob.com/v1/us_verifications`
with the address candidate fields from Phase 4.

**Output columns written:**
- `lob_verified` — true / false
- `lob_deliverability` — deliverable / deliverable_missing_unit / deliverable_incorrect_unit / undeliverable
- `lob_standardized_address` — full USPS-standardized address string
- `lob_address_type` — residential / commercial
- `lob_vacancy` — vacant / not_vacant / unknown
- `lob_verification_timestamp`

**Mail readiness rule:**
- `lob_deliverability = deliverable` AND `lob_vacancy != vacant` → `lob_ready = true`
- All other outcomes → `lob_ready = false`, flag reason

---

### Phase 6 — Escalation Queue Export

**Purpose:** Produce a human-reviewable list of records that need paid enrichment.

**Input:** Working CSV

**Include records where:**
- `address_found = N` after full free ladder
- `lob_deliverability = undeliverable`
- `address_found = UNCERTAIN` and confidence < 50%

**Output:** Separate CSV file — `escalation_queue_[run_id].csv`

**Columns:**
- `license_number`
- `owner_name_raw`
- `business_name_raw`
- `county`
- `fb_url` (if found)
- `website_url` (if found)
- `address_attempt_log`
- `lob_result` (if applicable)
- `recommended_paid_source`
- `escalation_reason`

**This phase does not call any paid service.**
The output is for human review and authorization only.
No paid enrichment runs without explicit human approval.

---

### Phase 7 — Batch Classification

**Purpose:** Assign each record to Batch 1, Batch 2, Excluded, or Unresolved.

**Input:** Working CSV (all prior phases complete)

**Classification logic:**

| Assignment | Criteria |
|---|---|
| Batch 1 | website_y/n = N AND fb_y/n = N AND active license AND target county |
| Batch 2 | website_y/n = N AND fb_y/n = Y AND active license AND target county |
| Excluded | website_y/n = Y OR inactive license OR out of geography OR duplicate |
| Unresolved | UNCERTAIN values that prevent confident classification |

**Output columns written:**
- `batch_assignment` — batch_1 / batch_2 / excluded / unresolved
- `lob_ready` — true / false
- `exclusion_reason` — if excluded
- `unresolved_reason` — if unresolved
- `confidence_score` — integer 0–100 composite score
- `phase7_timestamp`

**Confidence scoring rubric:**
- Address source count = 1: +15 pts
- Address source count = 2: +25 pts
- Address source count ≥ 3: +35 pts
- No address conflict AND source count ≥ 2: +5 pts bonus
- Full address complete: +5 pts bonus
- Residential address: -5 pts
- Lob deliverable: +20 pts
- lob_vacancy = vacant: -15 pts
- website_y/n = Y (should be excluded — penalty if slipped through): -20 pts
- address_conflict_detected = true AND unresolved: -10 pts

Tiers:
- A: 75–100
- B: 50–74
- C: 0–49

---

### Phase 8 — QA Audit

**Purpose:** Validate the pipeline output for consistency, completeness, and rule violations.

**Input:** Working CSV (all phases complete)

**Mandatory checks:**
1. Every record has a `batch_assignment` value — no blank assignments
2. Every `lob_ready = true` record has a complete, deliverable address
3. Every `excluded` record has an `exclusion_reason`
4. Confidence tier matches score range (A=75+, B=50–74, C=0–49)
5. No `website_y/n = Y` record is marked `lob_ready = true`
6. Duplicate license numbers flagged
7. Batch 1 count, Batch 2 count, excluded count, unresolved count reported

**Output:** `qa_report_[run_id].md`
- Total records audited
- Violations by check number
- Record IDs with violations (up to 20 per check)
- Tier A count
- Tier B count
- Recommended corrections

---

## Run Configuration

Each pipeline run is configured via a `run_config.json` file.

```json
{
  "run_id": "batch1-tarrant-pilot-100",
  "input_file": "data/source/batch1_search_log_results.csv",
  "output_file": "data/output/batch1_search_log_results.csv",
  "target_counties": ["Tarrant", "Dallas", "Denton", "Collin", "Johnson", "Ellis"],
  "license_subtypes": ["BE", "BC", "BR", "AEBR", "ARBE"],
  "max_records": 100,
  "county_priority": ["Tarrant", "Dallas", "Denton", "Collin", "Johnson", "Ellis"],
  "lob_budget_file": "data/lob_budget.json",
  "phases_to_run": [0, 1, 2, 3, 4, 5, 6, 7, 8],
  "start_phase": 0,
  "resume_from_record": null
}
```

The `start_phase` and `resume_from_record` fields allow the pipeline to resume
mid-run without reprocessing completed records.

---

## Directory Structure

```
tradepilot/
│
├── PROJECT.md                    ← product vision and business context
├── ARCHITECTURE.md               ← this file
├── DATA-SCHEMA.md                ← column definitions
├── CURSOR-BOOTSTRAP.md           ← Cursor Agent scaffold prompt
├── README.md                     ← generated by Cursor
│
├── .env.local                    ← API keys (never committed)
├── .env.example                  ← key names without values (committed)
├── .gitignore
│
├── run_config.json               ← active run configuration
├── data/
│   ├── source/
│   │   └── batch1_search_log_results.csv
│   ├── output/                   ← phases write here
│   └── lob_budget.json           ← persistent Lob verification counter
│
├── phases/
│   ├── phase0_filter.py
│   ├── phase1_website.py
│   ├── phase2_facebook.py
│   ├── phase3_other_presence.py
│   ├── phase4_address_resolve.py
│   ├── phase5_lob_verify.py
│   ├── phase6_escalation.py
│   ├── phase7_classify.py
│   └── phase8_qa.py
│
├── core/
│   ├── browser.py                ← browser-use wrapper and session manager
│   ├── deepseek.py               ← DeepSeek API client and prompt helpers
│   ├── lob.py                    ← Lob API client
│   ├── csv_io.py                 ← safe CSV read/write with column locking
│   ├── config.py                 ← run_config.json loader
│   └── logger.py                 ← structured run logging
│
├── runs/
│   └── batch1-tarrant-pilot-100/
│       ├── run.log
│       └── qa_report.md
│
└── main.py                       ← pipeline runner — executes phases in sequence
```

---

## Column Ownership Rules

Each phase owns specific columns. A phase must NEVER write to columns owned by another phase.

| Columns | Owner Phase |
|---|---|
| `run_id`, `phase0_timestamp`, `batch1_excluded` | Phase 0 |
| `website_y/n`, `website_url`, `website_confidence_%`, `website_search_notes`, `phase1_timestamp` | Phase 1 |
| `fb_y/n`, `fb_url`, `fb_page_name`, `fb_last_post_date`, `fb_confidence_%`, `fb_search_notes`, `phase2_timestamp` | Phase 2 |
| `gbp_found`, `gbp_claimed`, `gbp_review_count`, `yelp_found`, `angi_found`, `other_presence_types`, `other_presence_notes`, `phase3_timestamp` | Phase 3 |
| `address_found`, `address_raw`, `address_source`, `address_source_url`, `address_confidence_%`, `address_type_guess`, `address_is_pobox`, `address_attempt_log`, `address_source_count`, `address_conflict_detected`, `phase4_timestamp` | Phase 4 |
| `lob_verified`, `lob_deliverability`, `lob_standardized_address`, `lob_address_type`, `lob_vacancy`, `lob_verification_timestamp` | Phase 5 |
| `batch_assignment`, `lob_ready`, `exclusion_reason`, `unresolved_reason`, `confidence_score`, `phase7_timestamp` | Phase 7 |

---

## Resumability

The pipeline must be resumable at any phase and at any record.

Rules:
- If a column already has a value for a record, do not overwrite it
- Use `start_phase` in run_config.json to skip completed phases
- Use `resume_from_record` to pick up mid-phase after an interruption
- Log every record processed with timestamp so resume point is always known

This is critical because browser sessions time out, API rate limits hit,
and long runs across 1,900+ records will not complete in one uninterrupted session.

