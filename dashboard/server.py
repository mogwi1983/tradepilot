"""Local dev dashboard server for pipeline progress visualization."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_run_config
from dashboard.stats import compute_dashboard_stats


class DashboardHandler(BaseHTTPRequestHandler):
    config_path: Path = ROOT / "run_config.json"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/stats":
            self._serve_stats()
            return
        if path in ("/", "/index.html"):
            self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            rel = path[len("/static/") :]
            target = STATIC_DIR / rel
            if target.is_file():
                mime, _ = mimetypes.guess_type(str(target))
                self._serve_file(target, mime or "application/octet-stream")
                return

        self.send_error(404, "Not found")

    def _serve_stats(self) -> None:
        try:
            config = load_run_config(self.config_path)
            payload = compute_dashboard_stats(config)
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def _serve_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        if args and isinstance(args[0], str) and args[0].startswith("GET /api/stats"):
            return
        super().log_message(format, *args)


def main() -> None:
    parser = argparse.ArgumentParser(description="TradePilot pipeline progress dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    parser.add_argument("--config", default="run_config.json", help="Path to run_config.json")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path

    DashboardHandler.config_path = config_path

    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"TradePilot dashboard: http://{args.host}:{args.port}")
    print(f"Reading: {config_path}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
