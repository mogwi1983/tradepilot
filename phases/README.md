# phases/

One Python module per pipeline phase (0–8). Executed sequentially by `main.py`.

## Contract (every phase)

```python
def run(df: pd.DataFrame, config: RunConfig, logger: RunLogger) -> pd.DataFrame:
    """
    1. Skip records where this phase's timestamp column is already set.
    2. Process remaining records; write only owned columns via csv_io.
    3. Save CSV after each record.
    4. Return updated DataFrame.
    """
```

## Files

| File | Phase | Spec section |
|---|---|---|
| `phase0_filter.py` | Universe filter | ARCHITECTURE § Phase 0 |
| `phase1_website.py` | Website detection | ARCHITECTURE § Phase 1 |
| `phase2_facebook.py` | Facebook detection | ARCHITECTURE § Phase 2 |
| `phase3_other_presence.py` | GBP, Yelp, etc. | ARCHITECTURE § Phase 3 |
| `phase4_address_resolve.py` | Free address ladder | ARCHITECTURE § Phase 4 |
| `phase5_lob_verify.py` | Lob USPS verify | ARCHITECTURE § Phase 5 |
| `phase6_escalation.py` | Escalation CSV export | ARCHITECTURE § Phase 6 |
| `phase7_classify.py` | Batch classification | ARCHITECTURE § Phase 7 |
| `phase8_qa.py` | QA audit report | ARCHITECTURE § Phase 8 |

## Agent notes

- **Search minimums:** Phases 1–4 require 4–5 *distinct* queries per record — not punctuation variants.
- **DeepSeek usage:** Reasoning inside phases only — not for orchestration.
- **Phase 6:** No API calls. Output-only CSV to `data/output/`.
- **Phase 8:** Output to `runs/{run_id}/qa_report_{run_id}.md`, not the working CSV.

## Column ownership

Before writing any column, check `ARCHITECTURE.md` § Column Ownership Rules. Phase 5 owns `lob_*`; Phase 7 owns `batch_assignment`, `lob_ready`, `confidence_*`.
