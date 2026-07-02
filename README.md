# TradePilot

Lead intelligence pipeline: ingest licensed contractor data, detect digital presence, resolve mailing addresses, verify via USPS (Lob), and export mail-ready prospect segments.

**Status:** Scaffold only — pipeline code not yet implemented. See [AGENTS.md](AGENTS.md) to start building.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env.local
# Edit .env.local with API keys
python main.py
```

## Configure a run

Edit `run_config.json` at repo root. Key fields:

| Field | Purpose |
|---|---|
| `run_id` | Names the run folder under `runs/` |
| `input_file` | Source CSV (usually `data/source/`) |
| `output_file` | Working CSV phases read/write |
| `max_records` | Cap for pilot runs |
| `start_phase` / `resume_from_record` | Resume after interruption |

## Documentation map

| File | Read when |
|---|---|
| [AGENTS.md](AGENTS.md) | **Start here** — navigation for AI agents |
| [PROJECT.md](PROJECT.md) | Product vision, MVP scope, business context |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Pipeline phases, tech stack, column ownership |
| [DATA-SCHEMA.md](DATA-SCHEMA.md) | CSV column definitions and validation rules |
| [CURSOR-BOOTSTRAP.md](CURSOR-BOOTSTRAP.md) | Full implementation spec for first build agent |

## Directory layout

```
tradepilot/
├── main.py              # Pipeline runner (stub)
├── run_config.json      # Active run configuration
├── core/                # Shared libraries → core/README.md
├── phases/              # Phase 0–8 scripts → phases/README.md
├── data/                # CSV I/O + Lob budget → data/README.md
└── runs/                # Per-run logs and QA reports → runs/README.md
```

## Resume an interrupted run

1. Check `output_file` in `run_config.json` — completed records have phase timestamp columns populated.
2. Set `start_phase` to the phase that was interrupted.
3. Optionally set `resume_from_record` to a `license_number`.
4. Re-run `python main.py`.

## Lob budget

Tracked in `data/lob_budget.json`. Phase 5 must halt when `remaining` reaches 0.
