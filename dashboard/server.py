"""TradePilot dashboard server — auth, CSV export, batch runner, and proxy-aware paths."""

from __future__ import annotations

import argparse
import csv
import io
import json
import mimetypes
import os
import subprocess
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_run_config
from core.env import load_env as _load_env
from dashboard.stats import compute_dashboard_stats

# Load .env.local before reading env vars
_load_env()

# ── auth ──────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DASHBOARD_TOKEN", "")


def authenticate(headers: dict) -> bool:
    if not TOKEN:
        return True  # no token configured = open access
    return headers.get("x-dashboard-token", "") == TOKEN


class DashboardHandler(BaseHTTPRequestHandler):
    config_path: Path = ROOT / "run_config.json"

    # ── helpers ──────────────────────────────────────────────────────────

    def _base_path(self) -> str:
        """Detect reverse-proxy prefix so relative API paths work."""
        prefix = self.headers.get("X-Forwarded-Prefix", "")
        return prefix.rstrip("/")

    def _json_response(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        if TOKEN:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, X-Dashboard-Token")
            self.send_header("Access-Control-Allow-Methods",
                             "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        try:
            raw_length = self.headers.get("Content-Length", "0")
            length = int(raw_length) if raw_length and raw_length.isdigit() else 0
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            if not raw or not raw.strip():
                return {}
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError, OSError, ConnectionError):
            return {}

    def _csv_response(self, filename: str, csv_text: str) -> None:
        body = csv_text.encode("utf-8-sig")
        self.send_response(200)
        self.send_header("Content-Type",
                         "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _export_csv(self, config, cohort: str | None = None,
                    ready_only: bool = False) -> str:
        output_path = config.output_path
        if not output_path.exists():
            return ""

        import pandas as pd
        df = pd.read_csv(output_path)
        total = len(df)

        if ready_only and "lob_ready" in df.columns:
            df = df[df["lob_ready"].astype(str).str.lower() == "true"]
        if cohort and "batch_assignment" in df.columns:
            df = df[df["batch_assignment"].astype(str).str.strip() == cohort]

        buf = io.StringIO()
        df.to_csv(buf, index=False)
        return buf.getvalue()

    # ── routing ──────────────────────────────────────────────────────────

    def _route(self, method: str, path: str, headers: dict,
               body: dict | None = None) -> None:
        # Auth check for all /api/* routes
        authorized = authenticate(headers)
        # For GET requests, also check ?token= query param (for export downloads)
        if method == "GET" and not authorized:
            parsed_qs = urlparse(self.path)
            if parsed_qs.query:
                for part in parsed_qs.query.split("&"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        if k == "token" and v == TOKEN:
                            authorized = True

        if path.startswith("/api/") and not authorized:
            self._json_response(401, {"error": "Unauthorized — set X-Dashboard-Token header or configure DASHBOARD_TOKEN"})
            return

        try:
            config = load_run_config(self.config_path)
        except Exception as exc:
            self._json_response(500, {"error": f"Config error: {exc}"})
            return

        # ── stats ────────────────────────────────────────────────────
        if method == "GET" and path == "/api/stats":
            try:
                payload = compute_dashboard_stats(config)
                self._json_response(200, payload)
            except Exception as exc:
                self._json_response(500, {"error": str(exc),
                                          "traceback": traceback.format_exc()})

        # ── export ───────────────────────────────────────────────────
        elif method == "GET" and path.startswith("/api/export"):
            parsed = urlparse(self.path)
            qs = parsed.query
            params = {}
            if qs:
                for part in qs.split("&"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        params[k] = v

            cohort = params.get("cohort")
            ready = params.get("ready", "").lower() == "true"

            csv_text = self._export_csv(config, cohort=cohort,
                                        ready_only=ready)
            if not csv_text:
                self._json_response(404, {"error": "No data to export"})
                return

            parts = []
            if cohort:
                parts.append(cohort)
            if ready:
                parts.append("lob-ready")
            label = "_".join(parts) if parts else "full"
            self._csv_response(f"tradepilot_{label}.csv", csv_text)

        # ── batch run ────────────────────────────────────────────────
        elif method == "POST" and path == "/api/run-batch":
            try:
                phase_str = body.get("phase", "1") if body else "1"
                phase = int(phase_str)
                batch_size = int(body.get("batch_size", 100)) if body else 100
            except (ValueError, TypeError):
                self._json_response(400, {"error": "Invalid phase or batch_size"})
                return

            # ── run phase in subprocess ──────────────────────────────────
            cmd = [
                sys.executable, "-m", "dashboard.runner",
                "--config", str(self.config_path),
                "--phase", str(phase),
                "--batch-size", str(batch_size),
            ]
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=600,
                    cwd=str(ROOT)
                )
                self._json_response(200, {
                    "exit_code": result.returncode,
                    "stdout": result.stdout[-2000:],
                    "stderr": result.stderr[-2000:],
                })
            except subprocess.TimeoutExpired:
                self._json_response(504, {"error": "Batch timed out (600s)"})
            except Exception as exc:
                self._json_response(500, {"error": str(exc)})

        else:
            self._json_response(404, {"error": "Not found"})

    # ── HTTP method handlers ─────────────────────────────────────────

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # Static files
        if path in ("/", "/index.html"):
            self._serve_file(STATIC_DIR / "index.html",
                             "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            target = STATIC_DIR / rel
            if target.is_file():
                mime, _ = mimetypes.guess_type(str(target))
                self._serve_file(target,
                                 mime or "application/octet-stream")
                return

        self._route("GET", path, self.headers)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            body = self._read_body()
            self._route("POST", parsed.path, self.headers, body)
        except Exception:
            self._json_response(500, {"error": "Internal server error processing POST"})

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, X-Dashboard-Token")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, OPTIONS")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        if args and isinstance(args[0], str) and \
           args[0].startswith("GET /api/stats"):
            return
        super().log_message(format, *args)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TradePilot pipeline progress dashboard")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765,
                        help="Bind port (default: 8765)")
    parser.add_argument("--config", default="run_config.json",
                        help="Path to run_config.json")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path

    DashboardHandler.config_path = config_path

    server = ThreadingHTTPServer((args.host, args.port),
                                 DashboardHandler)
    print(f"TradePilot dashboard: http://{args.host}:{args.port}")
    print(f"Reading: {config_path}")
    print(f"Token auth: {'ON' if TOKEN else 'OFF'}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
