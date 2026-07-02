# data/output/

Runtime working directory. **Gitignored** — only `.gitkeep` is tracked.

## Files created at runtime

| Pattern | Created by | Purpose |
|---|---|---|
| `{run_id}.csv` or name from `output_file` | Phase 0+ | Single working file — all phases append columns |
| `escalation_queue_{run_id}.csv` | Phase 6 | Records needing paid enrichment or human review |

## Agent notes

- Path comes from `run_config.json` → `output_file`.
- Phases must save after **every record** (resumability).
- Never commit output CSVs — they may contain PII (addresses, owner names).
