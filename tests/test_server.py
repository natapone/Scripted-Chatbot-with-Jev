"""Story 1.1 — hermetic suite: no network, no Jev, no `.env`. Every test passes a fake environment
and an empty env file, and the one HTTP call (the warm-up) is stubbed."""
from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path

import http.client
import json
import socket
import threading

from app import config, server
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


if __name__ == "__main__":
    unittest.main()
