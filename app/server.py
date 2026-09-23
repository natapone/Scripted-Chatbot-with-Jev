"""The local HTTP server — `http.server` on 127.0.0.1, standard library only.

Routes: `GET /` and `GET /assets/*` from `app/static/`; `GET /api/config` → the model id, the
exchange rate and its date; `GET /api/health` → `{"ok": true}`; anything else 404. Nothing outside
`app/static/` is ever read for a response, so `.env` cannot be served. The key is not on this
module's path at all: the Config is held on the server object and only its public fields are sent.

Story 1.3 adds the conversation: `GET /api/session?id=` (create or restore), `POST /api/turn`
(one typed or clicked message, JSON body of at most 64 KB) and `POST /api/session/end`. The flow,
the store and the Jev client hang on the server object; the handler only routes. The key lives
inside the client's headers and is in no response.

Story 2.1 adds the speed test's engine (`app/speed.py`): `POST /api/run {session_id, target}` starts a
run on that session — or refuses it before its first call with `model_status: "cap"` — and
`GET /api/run?session_id=&since=` reports it: counts, the items from `since` on, and once it has ended
the recap figures for the recording driver. Nothing on the page reads them yet (Story 2.2, DR-010).
"""
from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from app.config import HOST, Config

STATIC = Path(__file__).resolve().parent / "static"
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8"}
MAX_BODY = 64 * 1024


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


def session_view(s, new: bool) -> dict:
    """What `GET /api/session` returns: the transcript, what is clickable now, the log, the raw
    bodies still in memory. `live_buttons` are the latest bot bubble's, with its `message_id` —
    the ones a click will be honoured for."""
    from app.turn import current_message_id
    current = current_message_id(s)
    bubble = next((b for b in s.transcript if b.get("who") == "bot" and b.get("id") == current), None)
    live = [dict(b, message_id=current) for b in (bubble or {}).get("buttons", [])]
    return {"session_id": s.session_id, "new": new, "turn_no": s.turn_no, "transcript": list(s.transcript),
            "live_buttons": live, "log": list(s.log), "raw": dict(s.raw)}


class Handler(BaseHTTPRequestHandler):
    server_version = "jev-demo/0.1"
    sys_version = ""

    def log_message(self, fmt, *args):  # the terminal shows the ready line, not every request
        return

    def do_GET(self):
        cfg: Config = self.server.cfg  # type: ignore[attr-defined]
        url = urlsplit(self.path)
        path = url.path
        if path == "/api/config":
            return self.send_json({"model": cfg.model, "thb_per_usd": cfg.thb_per_usd,
                                   "rate_date": cfg.rate_date})
        if path == "/api/health":
            return self.send_json({"ok": True})
        if path == "/api/session":
            return self.get_session(parse_qs(url.query).get("id", [""])[0])
        if path == "/api/run":
            q = parse_qs(url.query)
            return self.get_run(q.get("session_id", [""])[0], q.get("since", ["0"])[0])
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

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/api/turn", "/api/session/end", "/api/run"):
            return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        body = self.read_json()
        if body is None:
            return
        if path == "/api/turn":
            return self.post_turn(body)
        if path == "/api/run":
            return self.post_run(body)
        return self.post_end(body)

    # --- the speed test

    def post_run(self, body: dict):
        from app import speed
        session_id = body.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return self.send_json({"error": "session_id is missing"}, HTTPStatus.BAD_REQUEST)
        try:
            return self.send_json(self.server.runs.start(session_id, body.get("target")))  # type: ignore[attr-defined]
        except speed.RunError as e:
            return self.send_json({"error": e.message}, e.status)

    def get_run(self, session_id: str, since: str):
        from app import speed
        if not session_id:
            return self.send_json({"error": "session_id is missing"}, HTTPStatus.BAD_REQUEST)
        try:
            n = int(since or 0)
        except ValueError:
            return self.send_json({"error": "since must be a whole number"}, HTTPStatus.BAD_REQUEST)
        try:
            return self.send_json(self.server.runs.progress(session_id, n))  # type: ignore[attr-defined]
        except speed.RunError as e:
            return self.send_json({"error": e.message}, e.status)

    # --- the conversation

    def get_session(self, session_id: str):
        from app import turn
        store, flow = self.server.store, self.server.flow  # type: ignore[attr-defined]
        s = store.get(session_id.strip()) if session_id else None
        if s is None:
            s = turn.new_session(store, flow)
            return self.send_json(session_view(s, True))
        with store.lock(s.session_id):
            return self.send_json(session_view(s, False))

    def post_turn(self, body: dict):
        from app import turn
        srv = self.server
        cfg: Config = srv.cfg  # type: ignore[attr-defined]
        session_id = body.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return self.send_json({"error": "session_id is missing"}, HTTPStatus.BAD_REQUEST)
        try:
            result = turn.run_turn(srv.store, srv.flow, srv.client, session_id, body.get("turn_id"),  # type: ignore[attr-defined]
                                   text=body.get("text"), button=body.get("button"),
                                   spend_cap_usd=cfg.spend_cap_usd)
        except turn.TurnError as e:
            return self.send_json({"error": e.message}, e.status)
        return self.send_json(result)

    def post_end(self, body: dict):
        store = self.server.store  # type: ignore[attr-defined]
        session_id = body.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return self.send_json({"error": "session_id is missing"}, HTTPStatus.BAD_REQUEST)
        known = store.get(session_id) is not None
        store.end(session_id)
        return self.send_json({"ended": known, "session_id": session_id})

    def read_json(self) -> dict | None:
        """The body as a JSON object, or None after an error response was sent."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self.send_json({"error": f"body must be JSON of at most {MAX_BODY} bytes"},
                           HTTPStatus.REQUEST_ENTITY_TOO_LARGE if length > MAX_BODY else HTTPStatus.BAD_REQUEST)
            return None
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else None
        except (ValueError, UnicodeDecodeError):
            data = None
        if not isinstance(data, dict):
            self.send_json({"error": "body must be a JSON object"}, HTTPStatus.BAD_REQUEST)
            return None
        return data

    def send_json(self, obj, status=HTTPStatus.OK):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def make_server(cfg: Config, port: int | None = None, *, flow=None, store=None, client=None) -> ThreadingHTTPServer:
    """Bind to 127.0.0.1 (never configurable) on cfg.port, or `port` (0 = ephemeral, for tests).
    The flow, the store and the client are built from the Config when not given — a test passes
    its own store (a temp dir) and client (a fake connection)."""
    from app import flow as flow_module, jev, session, speed
    httpd = ThreadingHTTPServer((HOST, cfg.port if port is None else port), Handler)
    httpd.daemon_threads = True
    httpd.cfg = cfg  # type: ignore[attr-defined]
    httpd.flow = flow if flow is not None else flow_module.load()  # type: ignore[attr-defined]
    httpd.store = store if store is not None else session.Store(  # type: ignore[attr-defined]
        session.flow_version_of(flow_module.CATALOGUE), cfg.var_dir, ttl_s=cfg.session_ttl_s)
    httpd.client = client if client is not None else jev.Client(cfg.key, cfg.jev_host, cfg.jev_timeout)  # type: ignore[attr-defined]
    httpd.runs = speed.Runs(httpd.store, httpd.flow, httpd.client, spend_cap_usd=cfg.spend_cap_usd,  # type: ignore[attr-defined]
                            thb_per_usd=cfg.thb_per_usd, rate_date=cfg.rate_date)
    return httpd
