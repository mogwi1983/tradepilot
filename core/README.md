# core/

Shared libraries used by all phases. **Phases must not import from each other.**

## Module map

| Module | Implement first? | Responsibility |
|---|---|---|
| `config.py` | Yes | Load/validate `run_config.json` → `RunConfig` dataclass |
| `csv_io.py` | Yes | Safe CSV read/write, column ownership, resumability |
| `logger.py` | Yes | Structured logs → console + `runs/{run_id}/run.log` |
| `browser.py` | Before Phase 1 | browser-use wrapper: search, fetch page, retries |
| `deepseek.py` | Before Phase 1 | LLM: match scoring, address extraction, classification |
| `lob.py` | Before Phase 5 | Lob verify + `lob_budget.json` read/update |

## Interface contracts (summary)

Full signatures in `CURSOR-BOOTSTRAP.md` Step 2.

- `csv_io.update_record(df, license_number, updates)` — enforces column ownership; skips non-blank unless `force=True`
- `browser.search(query) → list[SearchResult]`
- `deepseek.score_match(candidate, target, context) → int` (0–100)
- `lob.verify_address(address) → LobResult` — raises `LobBudgetExhaustedError` at 0 remaining

## Agent notes

- Load env from `.env.local` via `python-dotenv` in `config.py` or a single `core/env.py` if needed — not in every module.
- All public functions: type hints + docstrings.
- `ColumnOwnershipError` and budget errors are intentional guardrails — do not catch and swallow.

## Spec references

- Column ownership table → `ARCHITECTURE.md` § Column Ownership Rules
- Lob fields → `DATA-SCHEMA.md` § Phase 5 Columns
