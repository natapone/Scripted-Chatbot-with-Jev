"""The local HTTP server — `http.server` on 127.0.0.1, standard library only.

Routes: `GET /` and `GET /assets/*` from `app/static/`; `GET /api/config` → the model id, the
exchange rate and its date; `GET /api/health` → `{"ok": true}`; anything else 404. Nothing outside
`app/static/` is ever read for a response, so `.env` cannot be served. The key is not on this
module's path at all: the Config is held on the server object and only its public fields are sent.
"""
from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.config import HOST, Config

STATIC = Path(__file__).resolve().parent / "static"
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8"}


def static_path(url_path: str) -> Path | None:
    """Map a request path to a file under STATIC, or None when it is outside or not a file."""
    if url_path == "/":
        url_path = "/index.html"
    if not url_path.startswith("/assets/") and url_path != "/index.html":
        return None
    rel = unquote(url_path).lstrip("/")
    if "\\" in rel or "\0" in rel:
        return None
    try:
        target = (STATIC / rel).resolve()
        target.relative_to(STATIC.resolve())  # refuses `..` and symlinks that leave STATIC
    except (ValueError, OSError):
        return None
    return target if target.is_file() else None


class Handler(BaseHTTPRequestHandler):
    server_version = "jev-demo/0.1"
    sys_version = ""

    def log_message(self, fmt, *args):  # the terminal shows the ready line, not every request
        return

    def do_GET(self):
        cfg: Config = self.server.cfg  # type: ignore[attr-defined]
        path = urlsplit(self.path).path
        if path == "/api/config":
            return self.send_json({"model": cfg.model, "thb_per_usd": cfg.thb_per_usd,
                                   "rate_date": cfg.rate_date})
        if path == "/api/health":
            return self.send_json({"ok": True})
        file = static_path(path)
        if file is None:
            return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        body = file.read_bytes()
        ctype = TYPES.get(file.suffix) or mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj, status=HTTPStatus.OK):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def make_server(cfg: Config, port: int | None = None) -> ThreadingHTTPServer:
    """Bind to 127.0.0.1 (never configurable) on cfg.port, or `port` (0 = ephemeral, for tests)."""
    httpd = ThreadingHTTPServer((HOST, cfg.port if port is None else port), Handler)
    httpd.daemon_threads = True
    httpd.cfg = cfg  # type: ignore[attr-defined]
    return httpd
