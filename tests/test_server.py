"""Story 1.1 — hermetic suite: no network, no Jev, no `.env`. Every test passes a fake environment
and an empty env file, and the one HTTP call (the warm-up) is stubbed."""
from __future__ import annotations

import contextlib
import io
import unittest
import unittest.mock
from pathlib import Path

import http.client
import json
import socket
import threading

from app import config, jev, server
from app.__main__ import main

FAKE_KEY = "sk-or-v1-test-key-never-real"
GOOD = {"OPENROUTER_API_KEY": FAKE_KEY, "THB_PER_USD": "34.9", "RATE_DATE": "2026-09-22"}
NO_ENV_FILE = Path("/nonexistent/.env")


def load(environ):
    return config.load(env_path=NO_ENV_FILE, environ=environ)


class ConfigTests(unittest.TestCase):
    def test_refuses_without_key(self):
        with self.assertRaises(config.ConfigError) as cm:
            load({"THB_PER_USD": "34.9", "RATE_DATE": "2026-09-22"})
        self.assertIn("OPENROUTER_API_KEY is missing", str(cm.exception))
        # the entry point turns that into a non-zero exit and one plain line, starting no server
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(environ={"THB_PER_USD": "34.9", "RATE_DATE": "2026-09-22"}, env_path=NO_ENV_FILE)
        self.assertEqual(code, 2)
        self.assertEqual(err.getvalue().count("\n"), 1)
        self.assertIn("OPENROUTER_API_KEY is missing", err.getvalue())

    def test_refuses_without_rate(self):
        for partial in ({"OPENROUTER_API_KEY": FAKE_KEY},
                        {"OPENROUTER_API_KEY": FAKE_KEY, "THB_PER_USD": "34.9"},
                        {"OPENROUTER_API_KEY": FAKE_KEY, "RATE_DATE": "2026-09-22"}):
            with self.assertRaises(config.ConfigError) as cm:
                load(partial)
            self.assertIn("exchange rate is missing", str(cm.exception))
            self.assertNotIn(FAKE_KEY, str(cm.exception))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(environ={"OPENROUTER_API_KEY": FAKE_KEY}, env_path=NO_ENV_FILE)
        self.assertEqual(code, 2)
        self.assertIn("exchange rate is missing", err.getvalue())
        self.assertNotIn(FAKE_KEY, err.getvalue())

    def test_good_config(self):
        cfg = load(GOOD)
        self.assertEqual(cfg.key, FAKE_KEY)
        self.assertEqual(cfg.thb_per_usd, 34.9)
        self.assertEqual(cfg.rate_date, "2026-09-22")
        self.assertEqual((cfg.host, cfg.port, cfg.model), ("127.0.0.1", 8765, "typesafe/jev-1.13"))
        self.assertNotIn(FAKE_KEY, repr(cfg))  # the key is not in the Config's repr
        self.assertEqual(load({**GOOD, "PORT": "8766"}).port, 8766)
        # the .env file is read the same way, quotes stripped; the environment overrides it
        env = Path(__file__).parent / "_tmp.env"
        env.write_text('# comment\nOPENROUTER_API_KEY="from-file"\nTHB_PER_USD=35\nRATE_DATE=2026-01-01\n')
        try:
            self.assertEqual(config.load(env_path=env, environ={}).key, "from-file")
            self.assertEqual(config.load(env_path=env, environ={"THB_PER_USD": "36"}).thb_per_usd, 36.0)
        finally:
            env.unlink()


class ServerTests(unittest.TestCase):
    """The real server on an ephemeral port, driven with http.client — no network beyond loopback."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server(load(GOOD), port=0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path)
            r = conn.getresponse()
            return r.status, r.getheader("Content-Type") or "", r.read()
        finally:
            conn.close()

    def test_serves_index_and_assets(self):
        status, ctype, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertTrue(ctype.startswith("text/html"))
        self.assertEqual(body, (server.STATIC / "index.html").read_bytes())
        status, ctype, body = self.get("/assets/design-system.css")
        self.assertEqual(status, 200)
        self.assertTrue(ctype.startswith("text/css"))
        self.assertEqual(body, (server.STATIC / "assets" / "design-system.css").read_bytes())
        self.assertNotIn(FAKE_KEY.encode(), body)
        # the served page is the approved prototype's screen: its tokens and the model id. Story
        # 1.3b wired it — the title lost "— prototype", the mark is gone (tests/test_static.py)
        html = self.get("/")[2].decode("utf-8")
        for token in ("composer", "send", "start-over", "key-info", "avg-ms", "total-baht",
                      "total-turns", "viewer", "viewer-close", "rate", "model-status", "band-top",
                      "band-bottom"):
            self.assertIn(f'data-testid="{token}"', html, token)
        self.assertIn("jev-1.13", html)
        self.assertEqual(html, (Path(__file__).parent.parent / "prototypes" / "p-001-chat.html")
                         .read_text(encoding="utf-8").replace("<b>jev-1.13</b>", '<b id="model-id">jev-1.13</b>')
                         .replace(" — prototype</title>", "</title>"))
        js = self.get("/assets/shared.js")[2].decode("utf-8")
        self.assertIn('fetch("/api/config"', js)           # boot() asks the server for the rate
        for token in ("badge-clicked", "speed-test-open"):
            self.assertIn(token, js + self.get("/assets/speed.js")[2].decode("utf-8"), token)
        # the greeting comes from the server (tests/test_static.py), not a fixture file
        self.assertEqual(self.get("/assets/fixtures.json")[0], 404)

    def test_api_config(self):
        status, ctype, body = self.get("/api/config")
        self.assertEqual(status, 200)
        self.assertTrue(ctype.startswith("application/json"))
        self.assertEqual(json.loads(body), {"model": "typesafe/jev-1.13", "thb_per_usd": 34.9,
                                            "rate_date": "2026-09-22"})
        self.assertNotIn(FAKE_KEY.encode(), body)  # NFR1: the key never reaches the browser

    def test_api_health(self):
        status, _, body = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True})

    def test_404_and_traversal_refused(self):
        for path in ("/nope", "/api/nope", "/assets/", "/assets/missing.css", "/index.html/..",
                     "/.env", "/assets/../.env", "/assets/../../.env", "/assets/..%2F..%2F.env",
                     "/assets/%2e%2e/%2e%2e/.env", "/assets/../server.py", "/app/config.py"):
            status, _, body = self.get(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"OPENROUTER", body, path)
        self.assertIsNone(server.static_path("/assets/../../.env"))
        self.assertIsNone(server.static_path("/../.env"))

    def test_binds_localhost_only(self):
        self.assertEqual(self.httpd.socket.getsockname()[0], "127.0.0.1")
        other = server.make_server(load({**GOOD, "PORT": "0"}))  # cfg.port honoured, host fixed
        try:
            self.assertEqual(other.socket.getsockname()[0], "127.0.0.1")
        finally:
            other.server_close()
        # when this machine has a non-loopback address, the same port is closed there
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect(("10.255.255.255", 1))  # no packet is sent; picks the outbound interface
            host = probe.getsockname()[0]
            probe.close()
        except OSError:
            host = "127.0.0.1"
        if not host.startswith("127."):
            with self.assertRaises(OSError):
                socket.create_connection((host, self.port), timeout=1).close()


class FakeConnection:
    """Stands in for http.client.HTTPSConnection: records the request, returns a canned answer."""
    sent = []
    status = 200
    reply = {"answers": {"confirm": {"type": "noul", "noul": 0.99}}, "usage": {"cost": 0.00016}}

    def __init__(self, host, timeout=None):
        self.host = host

    def request(self, method, path, body=None, headers=None):
        FakeConnection.sent.append((self.host, method, path, json.loads(body), dict(headers)))

    def getresponse(self):
        outer = self

        class R:
            status = outer.status

            def read(self_):
                return json.dumps(outer.reply).encode()
        return R()

    def close(self):
        pass


class WarmUpTests(unittest.TestCase):
    def test_warm_up_stubbed(self):
        FakeConnection.sent.clear()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status = jev.warm_up(FAKE_KEY, connection=FakeConnection)
        self.assertEqual(status, 200)
        self.assertEqual(out.getvalue(), "warm-up 200\n")
        self.assertNotIn(FAKE_KEY, out.getvalue())  # NFR1: the key never in any output
        # exactly one request, the spike's shape: one noul question to jev-1.13 on /api/v1/systemone
        self.assertEqual(len(FakeConnection.sent), 1)
        host, method, path, body, headers = FakeConnection.sent[0]
        self.assertEqual((host, method, path), ("openrouter.ai", "POST", "/api/v1/systemone"))
        self.assertEqual(body["model"], "typesafe/jev-1.13")
        self.assertEqual(list(body["questions"]), ["confirm"])
        self.assertEqual(body["questions"]["confirm"]["type"], "noul")
        self.assertEqual(set(body["questions"]["confirm"]["criteria"]), {"true", "false"})
        self.assertEqual(headers["Authorization"], f"Bearer {FAKE_KEY}")  # the key goes here only
        self.assertNotIn(FAKE_KEY, json.dumps(body))
        # a connection failure is a status of 0, printed the same way, and the key is not in it
        class Down(FakeConnection):
            def request(self, *a, **k):
                raise ConnectionRefusedError("refused")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(jev.warm_up(FAKE_KEY, connection=Down), 0)
        self.assertEqual(out.getvalue(), "warm-up 0\n")
        # and the entry point prints the ready line with that status and binds 127.0.0.1
        # (serve_forever is cut short by making the server raise KeyboardInterrupt at once)
        real_make = server.make_server

        def make_and_stop(cfg, port=None):
            httpd = real_make(cfg, port=0)
            httpd.serve_forever = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
            return httpd
        out = io.StringIO()
        with unittest.mock.patch.object(server, "make_server", make_and_stop), \
                unittest.mock.patch.object(jev, "warm_up", lambda key, **kw: 200), \
                contextlib.redirect_stdout(out):
            code = main(environ={**GOOD, "PORT": "8799"}, env_path=NO_ENV_FILE)
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), "ready · warm-up 200 · http://127.0.0.1:8799")
        # a busy port is a plain refusal before any warm-up call is made
        calls = []
        err = io.StringIO()
        with socket.socket() as busy, unittest.mock.patch.object(jev, "warm_up", lambda key, **kw: calls.append(key) or 200), \
                contextlib.redirect_stderr(err):
            busy.bind(("127.0.0.1", 0)); busy.listen(1)
            code = main(environ={**GOOD, "PORT": str(busy.getsockname()[1])}, env_path=NO_ENV_FILE)
        self.assertEqual(code, 2)
        self.assertEqual(calls, [])
        self.assertIn("cannot bind http://127.0.0.1:", err.getvalue())
        self.assertNotIn(FAKE_KEY, err.getvalue())


if __name__ == "__main__":
    unittest.main()
