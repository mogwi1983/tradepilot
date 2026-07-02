# runs/

Per-run artifacts created at pipeline execution time. **Gitignored** except `.gitkeep` and this README.

## Layout

```
runs/
└── {run_id}/           # matches run_config.json → run_id
    ├── run.log         # structured log from core/logger.py
    └── qa_report_{run_id}.md   # Phase 8 output
```

## Agent notes

- Create `runs/{run_id}/` at pipeline start in `main.py`.
- `run.log` format: `timestamp | level | phase | license_number | message`
- Do not commit run folders — they contain PII from processing logs.

## Related outputs (not in this folder)

- Working CSV → `data/output/` (see `run_config.json` → `output_file`)
- Escalation queue → `data/output/escalation_queue_{run_id}.csv`
