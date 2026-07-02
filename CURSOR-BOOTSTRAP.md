# TradePilot — Cursor Agent Bootstrap Prompt

## Instructions for James

Copy everything inside the "PROMPT START" and "PROMPT END" markers below and paste it
directly into Cursor Agent (Composer in agent mode). Make sure the four seed files are
already in your project directory before running this prompt.

---

## PROMPT START

You are building a Python project called **TradePilot** — a pipeline for mining, enriching,
and verifying licensed trade contractor leads from public licensing databases.

Four reference documents are already in this directory. Read all four before writing
any code:

- `PROJECT.md` — what TradePilot is, why it exists, and where it is going
- `ARCHITECTURE.md` — the full pipeline design, all phases, all technology decisions
- `DATA-SCHEMA.md` — every CSV column defined, who owns it, and what values are valid
- `CURSOR-BOOTSTRAP.md` — this file (you are reading it)

---

## What to Build

Scaffold the complete TradePilot project according to the directory structure in
ARCHITECTURE.md. Create all files and directories listed there. For each phase file
and core module, write complete, working Python — not stubs, not placeholders.

---

## Technology Requirements

- Language: Python 3.11+
- Browser automation: browser-use library (pip install browser-use)
- LLM reasoning: DeepSeek API via openai-compatible client (base_url: https://api.deepseek.com)
- Address validation: Lob Python SDK (pip install lob-python) or requests to Lob REST API
- CSV handling: pandas
- HTTP: httpx or requests
- Environment: python-dotenv reading from .env.local
- Logging: Python logging module, structured output to runs/{run_id}/run.log

---

## Environment Variables

Create `.env.example` with these key names (no values):

```
DEEPSEEK_API_KEY=
LOB_API_KEY=
BROWSER_USE_HEADLESS=true
```

The actual `.env.local` will be created manually by the developer.
Add `.env.local` to `.gitignore`. Commit `.env.example`.

---

## Build Instructions

### Step 1 — Project scaffold

Create the full directory structure from ARCHITECTURE.md:

```
tradepilot/
├── PROJECT.md
├── ARCHITECTURE.md
├── DATA-SCHEMA.md
├── CURSOR-BOOTSTRAP.md
├── README.md
├── .env.example
├── .gitignore
├── run_config.json
├── requirements.txt
├── main.py
├── data/
│   ├── source/           (empty, developer drops CSV here)
│   ├── output/           (empty, phases write here)
│   └── lob_budget.json
├── phases/
│   ├── __init__.py
│   ├── phase0_filter.py
│   ├── phase1_website.py
│   ├── phase2_facebook.py
│   ├── phase3_other_presence.py
│   ├── phase4_address_resolve.py
│   ├── phase5_lob_verify.py
│   ├── phase6_escalation.py
│   ├── phase7_classify.py
│   └── phase8_qa.py
├── core/
│   ├── __init__.py
│   ├── browser.py
│   ├── deepseek.py
│   ├── lob.py
│   ├── csv_io.py
│   ├── config.py
│   └── logger.py
└── runs/
    └── .gitkeep
```

### Step 2 — Core modules

Build these modules first, as all phases depend on them.

**core/config.py**
- Load `run_config.json`
- Expose a `RunConfig` dataclass with all fields typed
- Validate that input_file exists at startup
- Raise clear errors if required fields are missing

**core/csv_io.py**
- `read_csv(path)` → returns DataFrame
- `write_csv(df, path)` → writes CSV preserving column order
- `update_record(df, license_number, updates: dict)` → updates a single record's columns
- Column lock enforcement: each phase registers which columns it owns.
  If a phase tries to write to a column it does not own, raise a ColumnOwnershipError.
- Never overwrite a column that already has a non-blank value unless `force=True` is passed.
  This enforces resumability — completed records are not reprocessed.

**core/logger.py**
- Structured logger that writes to both console and `runs/{run_id}/run.log`
- Log levels: DEBUG, INFO, WARNING, ERROR
- Every log line includes: timestamp, phase name, record license_number, message

**core/browser.py**
- Wrap browser-use to provide a clean interface for phases
- `search(query: str) → list[SearchResult]`
- `fetch_page(url: str) → PageContent`
- `SearchResult` has: title, url, snippet
- `PageContent` has: url, title, text, links
- Handle browser session lifecycle: open once per phase run, close on completion
- Respect `BROWSER_USE_HEADLESS` env variable
- Add retry logic: if a search fails, retry up to 3 times with exponential backoff

**core/deepseek.py**
- DeepSeek API client using openai-compatible interface
- `reason(prompt: str, context: str) → str`
- `score_match(candidate: str, target: str, context: str) → int` → returns 0–100 confidence
- `extract_address(page_text: str, business_name: str) → dict` → returns address fields or empty dict
- Keep system prompts concise and task-specific
- Log every DeepSeek call with token count to run.log

**core/lob.py**
- Lob API client
- `verify_address(address: dict) → LobResult`
- `LobResult` has all fields from DATA-SCHEMA.md Phase 5 columns
- Read and update `data/lob_budget.json` on every call
- Raise `LobBudgetExhaustedError` if remaining verifications = 0
- Raise `LobBudgetWarningError` if remaining < 50 (but continue)

### Step 3 — Phase implementations

Implement each phase file according to the specification in ARCHITECTURE.md.
Each phase must:

1. Accept a DataFrame and RunConfig as inputs
2. Process only records that do not already have this phase's timestamp column populated
   (this is how resumability works — skip already-completed records)
3. Write results back to the DataFrame using `csv_io.update_record()`
4. Save the CSV after every record (not just at the end of the phase)
   so that a crash does not lose progress
5. Log every record processed at INFO level
6. Log every search attempt at DEBUG level
7. Return the updated DataFrame

**Phase 0 — phase0_filter.py**
Filter the source CSV to the working universe per run_config.json.
Apply: active license filter, county filter, license_subtype filter, record limit (max_records).
Sort by county priority order from run_config.json before applying max_records limit
so Tarrant County records are processed first.

**Phase 1 — phase1_website.py**
Use browser-use to run the search bundle defined in ARCHITECTURE.md.
Use DeepSeek to score whether a found URL belongs to this contractor.
Implement the retry ladder: minimum 5 distinct queries, different name variations each time.
Write to Phase 1 columns only.

**Phase 2 — phase2_facebook.py**
Same structure as Phase 1 but for Facebook.
Add logic to reject personal profiles: use DeepSeek to classify whether a Facebook page
is a business page or personal profile based on page content.

**Phase 3 — phase3_other_presence.py**
Detect GBP, Yelp, Angi, HomeAdvisor, Thumbtack, Instagram, LinkedIn.
Minimum 4 searches per record.

**Phase 4 — phase4_address_resolve.py**
Implement all four free address sources in priority order.
For each source, attempt the required minimum number of queries.
Use DeepSeek to extract address from page content when found.
Track address_source_count, address_conflict_detected.
Write the full attempt log to address_attempt_log (pipe-delimited).

**Phase 5 — phase5_lob_verify.py**
Call Lob API for all records with address_found = Y.
Process in priority order: website/facebook sourced first, then gmaps, then gsearch.
Check and update lob_budget.json before and after each call.
Never call Lob for records with address_found = N.

**Phase 6 — phase6_escalation.py**
Produce escalation_queue_{run_id}.csv in data/output/.
Include records with address_found = N OR lob_deliverability = undeliverable.
Do not call any paid API. Output only.

**Phase 7 — phase7_classify.py**
Apply classification logic from ARCHITECTURE.md.
Calculate confidence_score using rubric from DATA-SCHEMA.md.
Assign confidence_tier.

**Phase 8 — phase8_qa.py**
Run all mandatory checks from ARCHITECTURE.md.
Write qa_report_{run_id}.md to runs/{run_id}/.
Print summary to console.

### Step 4 — main.py

Build a pipeline runner that:

1. Loads run_config.json
2. Reads the working CSV
3. Runs phases in the order specified in run_config.json `phases_to_run`
4. Respects `start_phase` (skip phases with lower numbers)
5. Passes the DataFrame between phases
6. Saves the CSV after each phase completes
7. Logs start time, end time, and record counts for each phase
8. Handles interruptions gracefully — the CSV is always in a valid state

CLI usage:
```bash
python main.py                        # run all phases
python main.py --start-phase 4        # resume from phase 4
python main.py --phases 1 2 3         # run specific phases only
python main.py --record ABC123456     # run all phases for one record only (testing)
```

### Step 5 — README.md

Write a clear README that covers:
- What TradePilot is (one paragraph from PROJECT.md)
- Setup instructions (clone, virtualenv, pip install -r requirements.txt, create .env.local)
- How to run the pipeline (main.py usage)
- How to configure a run (run_config.json)
- How to resume an interrupted run
- How to check the Lob budget

### Step 6 — requirements.txt

Include all dependencies with pinned major versions:
- browser-use
- openai (for DeepSeek via openai-compatible client)
- pandas
- httpx
- python-dotenv
- requests (fallback)
- lob-python (or requests for Lob REST API if SDK is not available)

---

## Quality Standards

- No hardcoded API keys anywhere. All credentials from .env.local via python-dotenv.
- No silent failures. Every exception must be caught, logged, and either retried or escalated.
- Every CSV write must be atomic — write to a temp file, then rename to target, to prevent corruption.
- Type hints on all function signatures.
- Docstrings on all public functions.
- The pipeline must be runnable with `python main.py` from the project root with no additional setup
  beyond creating .env.local.

---

## What NOT to Build

- No web interface or API server — this is a CLI pipeline only for now
- No database — CSV is the only data store
- No agent framework, no LangChain, no LlamaIndex — phases are plain Python scripts
- No async/await complexity unless browser-use specifically requires it for its interface
- No Docker or containerization at this stage

---

## Final Check Before You Begin

Before writing a single line of code:
1. Confirm you have read PROJECT.md, ARCHITECTURE.md, and DATA-SCHEMA.md
2. Confirm the directory structure you will create matches ARCHITECTURE.md exactly
3. Confirm you understand the column ownership rules in DATA-SCHEMA.md
4. Confirm you understand the resumability requirement in core/csv_io.py

If anything is ambiguous, ask before building.

## PROMPT END

