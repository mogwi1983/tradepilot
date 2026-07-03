"""TradePilot dashboard server — auth, CSV export, batch runner, and proxy-aware paths."""

from __future__ import annotations

import argparse
import csv
import io
import json
import mimetypes
import os
import socket
import subprocess
import sys
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

API_VERSION = 2

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_run_config
from core.env import load_env as _load_env
from dashboard.stats import compute_dashboard_stats
from dashboard.job_status import finish_job, read_job

# Load .env.local before reading env vars
_load_env()

# ── auth ──────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DASHBOARD_TOKEN", "")

# Background DB pull/process subprocess
_db_process: subprocess.Popen | None = None


def _db_job_alive() -> bool:
    global _db_process
    if _db_process is None:
        return False
    if _db_process.poll() is None:
        return True
    _db_process = None
    return False


def _dashboard_job() -> dict:
    job = read_job()
    if job.get("state") == "running" and not _db_job_alive():
        job = finish_job("failed", job.get("message") or "Background job stopped unexpectedly")
    return job


def start_db_pull(config_path: Path, limit: int = 50) -> tuple[bool, str]:
    global _db_process
    if _db_job_alive():
        return False, "A DB pull/process job is already running"
    job = read_job()
    if job.get("state") == "running":
        return False, "A batch job is already running"

    cmd = [
        sys.executable,
        "-m",
        "dashboard.db_runner",
        "--config",
        str(config_path),
        "--limit",
        str(limit),
    ]
    _db_process = subprocess.Popen(cmd, cwd=str(ROOT))
    return True, f"Pulling and processing up to {limit} contractor(s) from Supabase"


def authenticate(headers: dict) -> bool:
    if not TOKEN:
        return True  # no token configured = open access
    return headers.get("x-dashboard-token", "") == TOKEN


def _port_available(host: str, port: int) -> bool:
    """Return True when host:port can be bound exclusively."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


class DashboardHTTPServer(ThreadingHTTPServer):
    """Single-instance server — do not allow address reuse."""

    allow_reuse_address = False


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
        if cohort:
            if "cohort" in df.columns:
                df = df[df["cohort"].astype(str).str.strip() == cohort]
            elif "batch_assignment" in df.columns:
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
        if method == "GET" and path == "/api/health":
            self._json_response(200, {
                "ok": True,
                "api_version": API_VERSION,
                "supports_post": True,
                "endpoints": ["GET /api/stats", "GET /api/export", "POST /api/run-batch", "POST /api/pull-process"],
            })

        elif method == "GET" and path == "/api/stats":
            try:
                payload = compute_dashboard_stats(config)
                payload["job"] = _dashboard_job()
                payload["server"] = {
                    "api_version": API_VERSION,
                    "supports_post": True,
                }
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

        # ── pull from Supabase + process ───────────────────────────────
        elif method == "POST" and path == "/api/pull-process":
            try:
                limit = int(body.get("limit", 50)) if body else 50
            except (ValueError, TypeError):
                self._json_response(400, {"error": "Invalid limit"})
                return

            if limit < 1 or limit > 500:
                self._json_response(400, {"error": "limit must be between 1 and 500"})
                return

            ok, message = start_db_pull(self.config_path, limit=limit)
            code = 200 if ok else 409
            self._json_response(code, {
                "ok": ok,
                "message": message,
                "job": _dashboard_job(),
            })

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
    parser.add_argument("--open", action="store_true",
                        help="Open the dashboard in your default browser")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path

    DashboardHandler.config_path = config_path

    if not _port_available(args.host, args.port):
        print(
            f"ERROR: Port {args.port} is already in use on {args.host}.\n"
            "Another dashboard (or stale process) is still running.\n"
            "Stop it first, then restart:\n"
            f"  Get-NetTCPConnection -LocalPort {args.port} | "
            "Select-Object -ExpandProperty OwningProcess -Unique | "
            "ForEach-Object {{ Stop-Process -Id $_ -Force }}\n"
            "  npm run dashboard",
            flush=True,
        )
        raise SystemExit(1)

    server = DashboardHTTPServer((args.host, args.port), DashboardHandler)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    display_host = "localhost" if args.host in ("127.0.0.1", "0.0.0.0", "") else args.host
    url = f"http://{display_host}:{args.port}/"
    print(f"TradePilot dashboard: {url}", flush=True)
    print(f"Also reachable at: http://127.0.0.1:{args.port}/", flush=True)
    print(f"Reading: {config_path}", flush=True)
    print(f"Token auth: {'ON' if TOKEN else 'OFF'}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
