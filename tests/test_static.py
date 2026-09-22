"""Story 1.3b — the served page runs on the server, not the fixtures. Hermetic: the real server on
an ephemeral loopback port serves its static files; nothing is typed, no Jev, no network. What a
browser would do with the page is proven by hand (the Story's task 04); here the page's bytes are
checked for the shape that proof relies on."""
from __future__ import annotations

import http.client
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from app import config, server

FAKE_KEY = "sk-or-v1-test-key-never-real"
GOOD = {"OPENROUTER_API_KEY": FAKE_KEY, "THB_PER_USD": "34.9", "RATE_DATE": "2026-09-22"}


class StaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()                    # snapshots go here, never under var/
        cfg = config.load(env_path=Path("/nonexistent/.env"), environ={**GOOD, "VAR_DIR": cls.tmp.name})
        cls.httpd = server.make_server(cfg, port=0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

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

    # 05_components.md's tokens for the chat screen (P-001 / W-001), by the component that owns them
    TOKENS = {
        "index.html": ("chat", "messages", "composer", "send", "start-over", "panel", "key-info", "avg-ms",
                       "total-baht", "total-turns", "viewer", "viewer-close", "viewer-sent", "viewer-back",
                       "viewer-applied", "rate", "model-status", "band-top", "band-bottom"),
        "shared.js": ("bot-${id}", "you-${youCount}", "opt-${i + 1}", "badge-clicked", "turn-${n}", "turn-${n}-intent",
                      "turn-${n}-confidence", "turn-${n}-ms", "turn-${n}-baht", "turn-${n}-usd", "turn-${n}-open",
                      "viewer-raw-request", "viewer-raw-response"),
        "speed.js": ("speed-test-open", "speed-pop", "speed-chooser", "speed-target-100", "speed-target-1000",
                     "speed-start", "speed-test", "speed-count", "speed-target", "speed-elapsed-ms", "speed-per-s",
                     "speed-correct", "speed-errors", "speed-summary"),
    }

    def test_page_carries_every_token(self):
        served = {"index.html": self.get("/")[1], "shared.js": self.get("/assets/shared.js")[1],
                  "speed.js": self.get("/assets/speed.js")[1]}
        for name, tokens in self.TOKENS.items():
            for token in tokens:
                if "$" in token:                                     # a template: the literal the page builds
                    self.assertIn(f"`{token}`", served[name], f"{token} in {name}")
                elif name == "index.html":
                    self.assertIn(f'data-testid="{token}"', served[name], f"{token} in {name}")
                else:
                    self.assertIn(f'"data-testid": "{token}"', served[name], f"{token} in {name}")
        # the figures a driver reads carry data-value; the composer its state; a button its liveness
        js = served["shared.js"]
        for figure in ("avg-ms", "total-baht", "total-turns"):
            self.assertIn(f'set("#{figure}"', js, figure)
        self.assertIn('"data-value": j?.ms', js)
        self.assertIn('"data-value": j?.cost_usd', js)
        self.assertIn('"data-live": "true"', js)
        self.assertIn('data-state="ready"', served["index.html"])

    def test_prototype_mark_gone_and_fixtures_not_served(self):
        status, html = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("<title>Beanly · Scripted Chatbot with Jev</title>", html)
        self.assertNotIn("prototype", html.split("<body>")[0])
        for name, text in (("index.html", html), ("shared.js", self.get("/assets/shared.js")[1])):
            self.assertNotIn("PROTOTYPE", text, name)
            self.assertNotIn("proto-mark", text, name)
            self.assertNotIn("FIXTURES, NOT JEV", text, name)
        status, body = self.get("/assets/fixtures.json")
        self.assertEqual(status, 404)
        self.assertFalse((server.STATIC / "assets" / "fixtures.json").exists())
        self.assertEqual(sorted(p.name for p in (server.STATIC / "assets").iterdir() if not p.name.startswith(".")),
                         ["design-system.css", "shared.js", "speed.js"])
        # the greeting and its three buttons come from the server — what the page draws first
        s = json.loads(self.get("/api/session?id=")[1])
        self.assertTrue(s["new"])
        self.assertTrue(s["transcript"][0]["text"].startswith("สวัสดีค่ะ Beanly นะคะ"))
        self.assertEqual(len(s["transcript"][0]["buttons"]), 3)
        self.assertEqual(len(s["live_buttons"]), 3)
        self.assertNotIn(FAKE_KEY, html)

    def test_speed_test_mounted_but_not_wired(self):
        status, js = self.get("/assets/speed.js")
        self.assertEqual(status, 200)
        self.assertNotIn("FX.", js)                                  # nothing to read at mount now
        self.assertNotIn("fixtures.json", js)
        self.assertIn("not wired until Epic 2", js)
        self.assertIn("function speedMount(", js)
        self.assertIn("function speedStart(", js)
        self.assertIn("function speedReset(", js)                    # start-over still resets it
        self.assertNotIn("setInterval", js)                          # no simulated run
        self.assertNotIn("S.session", js)                            # and it writes nothing to the session


if __name__ == "__main__":
    unittest.main()
