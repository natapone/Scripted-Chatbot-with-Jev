"""Story 1.3b — the served page runs on the server, not the fixtures. Hermetic: the real server on
an ephemeral loopback port serves its static files; nothing is typed, no Jev, no network. What a
browser would do with the page is proven by hand (the Story's task 04); here the page's bytes are
checked for the shape that proof relies on."""
from __future__ import annotations

import http.client
import shutil
import subprocess
import threading
import unittest
from pathlib import Path

from app import config, server

FAKE_KEY = "sk-or-v1-test-key-never-real"
GOOD = {"OPENROUTER_API_KEY": FAKE_KEY, "THB_PER_USD": "34.9", "RATE_DATE": "2026-09-22"}


class StaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = config.load(env_path=Path("/nonexistent/.env"), environ=GOOD)
        cls.httpd = server.make_server(cfg, port=0)
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
            return r.status, r.read().decode("utf-8", "replace")
        finally:
            conn.close()

    def test_shared_js_talks_to_the_server(self):
        status, js = self.get("/assets/shared.js")
        self.assertEqual(status, 200)
        # the engine path: the session from the server, a typed line and a click as POST /api/turn
        self.assertIn('fetch("/api/session?id="', js)
        self.assertIn('fetch("/api/turn"', js)
        self.assertIn('fetch("/api/session/end"', js)
        self.assertIn('fetch("/api/config"', js)
        self.assertIn("crypto.randomUUID()", js)                      # a fresh turn_id per message
        self.assertIn('sessionStorage.setItem("session_id"', js)     # the id, and nothing else
        self.assertEqual(js.count("sessionStorage.setItem("), 1)
        # the fixture engine is gone: no fixture fetch, no local act, no order form in the browser
        self.assertNotIn('fetch("assets/fixtures.json"', js)
        self.assertNotIn("fixtures.json", js)
        for gone in ("function act(", "act(entry)", "function leadNext(", "function parseSlot(", "function readback(",
                     "function totals(", "function applyPromo(", "function fitPromo(", "function recommendStep(",
                     "function helpButtons(", "const REC ", "FX.data", "const FX "):
            self.assertNotIn(gone, js, gone)
        self.assertNotIn("order:", js)
        self.assertNotIn("PROTO_FORCE_FAIL", js)
        self.assertNotIn(FAKE_KEY, js)
        # a click is the same POST with the button and its message_id; a stale one is `ignored`
        self.assertIn("button: btn", js)
        self.assertIn("message_id: id", js)
        self.assertIn('r.outcome === "ignored"', js)
        # start over ends the session, then asks for a new one; a typed เริ่มใหม่ comes back `ended`
        self.assertIn("if (r.ended)", js)
        self.assertLess(js.index('fetch("/api/session/end"'), js.index('await load("")', js.index('fetch("/api/session/end"')))
        # the composer is `judging` around every call and `ready` after, whatever happened
        self.assertEqual(js.count('setComposer("judging")'), 3)      # send, click, startOver
        self.assertEqual(js.count('finally { setComposer("ready"); }'), 3)
        if shutil.which("node"):                                     # syntax, when a node is at hand
            for name in ("shared.js", "speed.js"):
                r = subprocess.run(["node", "--check", str(server.STATIC / "assets" / name)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
