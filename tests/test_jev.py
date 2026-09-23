"""Story 1.2 — the Jev client. Hermetic: the connection is a fake and the clock is fixed; one test
opens a loopback connection to a dead port (127.0.0.1:1) and nothing else touches a socket."""
from __future__ import annotations

import contextlib
import http.client
import dataclasses
import io
import json
import re
import time
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import config, flow, jev, server
from app.__main__ import main

FAKE_KEY = "sk-or-v1-test-key-never-real"
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
T0 = datetime(2026, 9, 22, 6, 48, 10, 418_000, tzinfo=timezone.utc)

GOOD_REPLY = {
    "id": "gen-dec-0001",
    "answers": {
        "intent": {"type": "choice", "choice": "inform", "confidence": 0.99,
                   "probabilities": {"inform": 0.99, "order_product": 0.01}},
        "product": {"type": "choice", "choice": "not_mentioned"},
        "quantity": {"type": "choice", "choice": "1"},
        "brew": {"type": "choice", "choice": "not_mentioned"},
        "roast": {"type": "choice", "choice": "not_mentioned"},
        "payment": {"type": "choice", "choice": "not_mentioned"},
    },
    "usage": {"cost": 0.000164},
}


def fake(status=200, reply=None, raise_=None):
    """A stand-in for http.client.HTTPSConnection: records the request, returns one canned answer."""
    sent = []

    class Fake:
        def __init__(self, host, port=None, timeout=None):
            self.host, self.port, self.timeout = host, port, timeout

        def request(self, method, path, body=None, headers=None):
            if raise_:
                raise raise_
            sent.append({"host": self.host, "port": self.port, "timeout": self.timeout, "method": method,
                         "path": path, "body": json.loads(body), "headers": dict(headers)})

        def getresponse(self):
            class R:
                pass
            r = R()
            r.status = status
            r.read = lambda: json.dumps(reply).encode("utf-8") if reply is not None else b""
            return r

        def close(self):
            pass
    Fake.sent = sent
    return Fake


def ticking(*times):
    """A clock that returns the given datetimes in order."""
    it = iter(times)
    return lambda: next(it)


class AskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = flow.load().build_request("รับกี่ถุงดีคะ?", "1 ถุงค่ะ", "quantity", [], ["ask_quantity"])

    def test_ask_types_the_answer(self):  # AC-3
        conn = fake(200, GOOD_REPLY)
        a = jev.ask(FAKE_KEY, self.body, connection=conn, clock=ticking(T0, T0 + timedelta(milliseconds=338)))
        self.assertIsInstance(a, jev.JevAnswer)
        self.assertEqual((a.status, a.intent, a.confidence), (200, "inform", 0.99))
        self.assertEqual(a.probabilities, {"inform": 0.99, "order_product": 0.01})
        self.assertEqual(a.entities, {"product": "not_mentioned", "quantity": "1", "brew": "not_mentioned",
                                      "roast": "not_mentioned", "payment": "not_mentioned"})
        self.assertEqual(a.cost_usd, 0.000164)
        self.assertEqual(a.request_id, "gen-dec-0001")
        self.assertIsNone(a.error)
        self.assertEqual(a.raw, GOOD_REPLY)
        # stamps: ISO-8601 UTC with milliseconds; ms is their difference and nothing else
        self.assertEqual(a.t_sent, "2026-09-22T06:48:10.418Z")
        self.assertEqual(a.t_received, "2026-09-22T06:48:10.756Z")
        self.assertTrue(STAMP.match(a.t_sent) and STAMP.match(a.t_received))
        self.assertEqual(a.ms, 338)
        self.assertIsInstance(a.ms, int)
        sent_dt = datetime.strptime(a.t_sent, "%Y-%m-%dT%H:%M:%S.%fZ")
        recv_dt = datetime.strptime(a.t_received, "%Y-%m-%dT%H:%M:%S.%fZ")
        self.assertEqual(a.ms, round((recv_dt - sent_dt).total_seconds() * 1000))
        # a naive or non-UTC clock is stamped in UTC; a difference across a second boundary is exact
        b = jev.ask(FAKE_KEY, self.body, connection=conn,
                    clock=ticking(datetime(2026, 9, 22, 13, 48, 59, 900_500, tzinfo=timezone(timedelta(hours=7))),
                                  datetime(2026, 9, 22, 13, 49, 0, 250_000, tzinfo=timezone(timedelta(hours=7)))))
        self.assertEqual((b.t_sent, b.t_received, b.ms), ("2026-09-22T06:48:59.900Z", "2026-09-22T06:49:00.250Z", 350))
        self.assertEqual(jev.stamp(datetime(2026, 1, 2, 3, 4, 5, 6_000)), "2026-01-02T03:04:05.006Z")
        # exactly one request each, the flow's body, to OpenRouter, the key in the header only
        self.assertEqual(len(conn.sent), 2)
        req = conn.sent[0]
        self.assertEqual((req["host"], req["port"], req["method"], req["path"]),
                         ("openrouter.ai", None, "POST", "/api/v1/systemone"))
        self.assertEqual(req["timeout"], 10)
        self.assertEqual(req["body"], self.body)
        self.assertEqual(req["body"]["state"]["awaiting"], "quantity")
        self.assertEqual(req["headers"]["Authorization"], f"Bearer {FAKE_KEY}")
        self.assertNotIn(FAKE_KEY, json.dumps(req["body"]))
        # the answer is frozen
        with self.assertRaises(dataclasses.FrozenInstanceError):
            a.intent = "x"

    def test_ask_200_without_answers_is_empty(self):  # AC-4, the S-2/S-3 API fault
        for reply in ({}, {"id": "gen-x", "usage": {"cost": 0.0001}}, {"answers": {}}, {"answers": None},
                      {"error": {"message": "upstream"}}):
            a = jev.ask(FAKE_KEY, self.body, connection=fake(200, reply), clock=ticking(T0, T0 + timedelta(milliseconds=5)))
            self.assertEqual((a.status, a.error, a.intent, a.confidence), (200, "empty", None, None), reply)
            self.assertEqual(a.entities, {}, reply)
            self.assertEqual(a.ms, 5)
        a = jev.ask(FAKE_KEY, self.body, connection=fake(200, {"id": "gen-x", "usage": {"cost": 0.0001}}),
                    clock=ticking(T0, T0))
        self.assertEqual((a.cost_usd, a.request_id), (0.0001, "gen-x"))   # what came back is still kept
        # an empty body, or one that is not JSON, is the same fault
        a = jev.ask(FAKE_KEY, self.body, connection=fake(200, None), clock=ticking(T0, T0))
        self.assertEqual((a.status, a.error, a.raw), (200, "empty", {}))
        # a non-200 is `http`, with the status kept
        for status in (400, 401, 429, 500, 502):
            a = jev.ask(FAKE_KEY, self.body, connection=fake(status, {"error": {"message": "no"}}),
                        clock=ticking(T0, T0))
            self.assertEqual((a.status, a.error, a.intent), (status, "http", None), status)

    def test_ask_no_response_is_status_0(self):  # AC-4, E-002
        for exc in (ConnectionRefusedError("refused"), TimeoutError("timed out"), OSError("dns")):
            a = jev.ask(FAKE_KEY, self.body, connection=fake(raise_=exc),
                        clock=ticking(T0, T0 + timedelta(seconds=10)))
            self.assertEqual((a.status, a.error, a.intent, a.confidence), (0, type(exc).__name__, None, None))
            self.assertEqual((a.entities, a.probabilities, a.cost_usd, a.request_id), ({}, {}, 0.0, None))
            self.assertEqual(a.ms, 10_000)
            self.assertTrue(STAMP.match(a.t_sent) and STAMP.match(a.t_received))
        # the default clock is real and UTC, and stamps parse
        a = jev.ask(FAKE_KEY, self.body, connection=fake(raise_=ConnectionRefusedError()))
        self.assertTrue(STAMP.match(a.t_sent))
        self.assertGreaterEqual(a.ms, 0)
        self.assertLess(a.ms, 1000)

    def test_key_is_in_no_field_and_no_repr(self):  # NFR1
        for conn in (fake(200, GOOD_REPLY), fake(200, {}), fake(500, {"error": "x"}),
                     fake(raise_=ConnectionRefusedError(FAKE_KEY))):
            a = jev.ask(FAKE_KEY, self.body, connection=conn, clock=ticking(T0, T0))
            self.assertNotIn(FAKE_KEY, repr(a))
            self.assertNotIn(FAKE_KEY, str(a))
            self.assertNotIn("Bearer", repr(a))
            for f in dataclasses.fields(a):
                self.assertNotIn(FAKE_KEY, json.dumps(getattr(a, f.name), ensure_ascii=False, default=str), f.name)
            self.assertNotIn(FAKE_KEY, json.dumps(dataclasses.asdict(a), ensure_ascii=False, default=str))
        self.assertNotIn("raw", repr(a))   # the body is kept for the viewer, not for the log line
        self.assertNotIn("key", {f.name for f in dataclasses.fields(jev.JevAnswer)})


class DeadAddressTests(unittest.TestCase):
    def test_dead_port_fails_fast(self):  # AC-5's switch: the one loopback connection in the suite
        t0 = time.perf_counter()
        a = jev.ask(FAKE_KEY, {"model": "typesafe/jev-1.13", "state": {}, "questions": {}}, host="127.0.0.1:1")
        elapsed = time.perf_counter() - t0
        self.assertEqual((a.status, a.error, a.intent), (0, "ConnectionRefusedError", None))
        self.assertLess(elapsed, 1.0)
        self.assertLess(a.ms, 1000)
        self.assertEqual(jev.post(FAKE_KEY, {}, host="127.0.0.1:1"), (0, {"error": "ConnectionRefusedError"}))
        # the host string carries the port; a bare host uses the class's default port
        conn = fake(200, GOOD_REPLY)
        jev.post(FAKE_KEY, {}, conn, host="example.test:8443", timeout=3)
        self.assertEqual((conn.sent[0]["host"], conn.sent[0]["port"], conn.sent[0]["timeout"]), ("example.test", 8443, 3))
        jev.post(FAKE_KEY, {}, conn)
        self.assertEqual((conn.sent[1]["host"], conn.sent[1]["port"], conn.sent[1]["timeout"]), ("openrouter.ai", None, 10))


class ConfigSwitchTests(unittest.TestCase):
    """JEV_HOST / JEV_TIMEOUT — rehearsal only. Absent, nothing differs from Story 1.1."""

    GOOD = {"OPENROUTER_API_KEY": FAKE_KEY, "THB_PER_USD": "34.9", "RATE_DATE": "2026-09-22"}
    NO_ENV_FILE = Path("/nonexistent/.env")

    def load(self, environ):
        return config.load(env_path=self.NO_ENV_FILE, environ=environ)

    def test_switch_is_optional_and_reaches_the_warm_up(self):  # AC-5
        cfg = self.load(self.GOOD)
        self.assertEqual((cfg.jev_host, cfg.jev_timeout), ("openrouter.ai", 10.0))
        self.assertEqual((jev.HOST, jev.TIMEOUT), ("openrouter.ai", 10))
        cfg = self.load({**self.GOOD, "JEV_HOST": "127.0.0.1:1", "JEV_TIMEOUT": "2"})
        self.assertEqual((cfg.jev_host, cfg.jev_timeout), ("127.0.0.1:1", 2.0))
        self.assertNotIn(FAKE_KEY, repr(cfg))
        for bad in ("x", "0", "-1"):
            with self.assertRaises(config.ConfigError) as cm:
                self.load({**self.GOOD, "JEV_TIMEOUT": bad})
            self.assertIn("JEV_TIMEOUT", str(cm.exception))
            self.assertNotIn(FAKE_KEY, str(cm.exception))
        # the entry point hands the Config's host to the warm-up: a dead port is `warm-up 0`, fast,
        # and the ready line still prints — the server is up (serve_forever cut short at once)
        real_make = server.make_server

        def make_and_stop(cfg, port=None):
            httpd = real_make(cfg, port=0)
            httpd.serve_forever = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
            return httpd
        seen = []

        def spy(key, connection=None, **kw):
            seen.append(kw)
            return 0
        out = io.StringIO()
        with unittest.mock.patch.object(server, "make_server", make_and_stop), \
                unittest.mock.patch.object(jev, "warm_up", spy), contextlib.redirect_stdout(out):
            code = main(environ={**self.GOOD, "PORT": "8768", "JEV_HOST": "127.0.0.1:1"}, env_path=self.NO_ENV_FILE)
        self.assertEqual(code, 0)
        # Story 1.3: the warm-up also goes through the server's kept-alive client, built on the same host
        self.assertEqual(len(seen), 1)
        self.assertEqual((seen[0]["host"], seen[0]["timeout"]), ("127.0.0.1:1", 10.0))
        self.assertIsInstance(seen[0]["client"], jev.Client)
        self.assertEqual((seen[0]["client"].host, seen[0]["client"].timeout), ("127.0.0.1:1", 10.0))
        self.assertEqual(out.getvalue().strip(), "ready · warm-up 0 · http://127.0.0.1:8768")
        seen.clear()
        with unittest.mock.patch.object(server, "make_server", make_and_stop), \
                unittest.mock.patch.object(jev, "warm_up", spy), contextlib.redirect_stdout(io.StringIO()):
            main(environ={**self.GOOD, "PORT": "8768"}, env_path=self.NO_ENV_FILE)
        self.assertEqual((seen[0]["host"], seen[0]["timeout"]), ("openrouter.ai", 10.0))   # without the variable: 1.1's call
        self.assertEqual(seen[0]["client"].host, "openrouter.ai")
        # the real warm-up against the dead port: status 0, printed the same way, under a second
        t0 = time.perf_counter()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(jev.warm_up(FAKE_KEY, host="127.0.0.1:1", timeout=2), 0)
        self.assertLess(time.perf_counter() - t0, 1.0)
        self.assertEqual(out.getvalue(), "warm-up 0\n")


def scripted(*steps):
    """A connection class for the kept-alive Client: each instantiation is one connection; each
    request takes the next step — a (status, reply) pair, or an exception to raise. `opened`
    counts connections, `sent` the bodies, in order."""
    it = iter(steps)
    log = {"opened": 0, "sent": [], "closed": 0}

    class Conn:
        def __init__(self, host, port=None, timeout=None):
            log["opened"] += 1
            self.host, self.port, self.timeout = host, port, timeout

        def request(self, method, path, body=None, headers=None):
            step = next(it)
            log["sent"].append({"body": json.loads(body), "headers": dict(headers), "host": self.host,
                                "port": self.port, "timeout": self.timeout})
            if isinstance(step, BaseException):
                raise step
            self._step = step

        def getresponse(self):
            status, reply = self._step

            class R:
                pass
            r = R()
            r.status = status
            r.read = lambda: json.dumps(reply).encode("utf-8") if reply is not None else b""
            return r

        def close(self):
            log["closed"] += 1
    Conn.log = log
    return Conn


class ClientTests(unittest.TestCase):
    """Story 1.3 — the kept-alive connection (F-3)."""

    def test_keeps_one_connection_and_counts(self):
        body = {"model": "typesafe/jev-1.13", "state": {}, "questions": {}}
        conn = scripted((200, GOOD_REPLY), (200, GOOD_REPLY), (200, {"id": "gen-2", "usage": {"cost": 0.0002}}))
        c = jev.Client(FAKE_KEY, host="example.test:8443", timeout=7, connection=conn)
        self.assertEqual((c.calls, c.spent_usd), (0, 0.0))
        self.assertEqual(c.post(body), (200, GOOD_REPLY))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(jev.warm_up(FAKE_KEY, client=c), 200)  # the warm-up rides the same connection
        a = jev.ask(None, body, client=c, clock=ticking(T0, T0 + timedelta(milliseconds=12)))
        self.assertEqual((a.status, a.error, a.ms, a.cost_usd, a.request_id), (200, "empty", 12, 0.0002, "gen-2"))
        self.assertEqual(conn.log["opened"], 1)                       # three calls, one connection
        self.assertEqual(conn.log["closed"], 0)
        self.assertEqual(c.calls, 3)
        self.assertAlmostEqual(c.spent_usd, 0.000164 * 2 + 0.0002)
        self.assertEqual([s["body"] for s in conn.log["sent"]], [body, jev.WARM_UP_BODY, body])
        s = conn.log["sent"][0]
        self.assertEqual((s["host"], s["port"], s["timeout"]), ("example.test", 8443, 7))
        self.assertEqual(s["headers"]["Authorization"], f"Bearer {FAKE_KEY}")
        # the key is in the headers only: not in the repr, not in any public attribute
        self.assertNotIn(FAKE_KEY, repr(c))
        self.assertNotIn("Bearer", repr(c))
        self.assertIn("calls=3", repr(c))
        for name in ("host", "timeout", "spent_usd", "calls"):
            self.assertNotIn(FAKE_KEY, str(getattr(c, name)))
        c.close()
        self.assertEqual(conn.log["closed"], 1)

    def test_reconnects_after_a_failure(self):
        body = {"model": "typesafe/jev-1.13", "state": {}, "questions": {}}
        # a connection that dies after serving one call: the next call retries once on a new one
        conn = scripted((200, GOOD_REPLY), http.client.RemoteDisconnected("gone"), (200, GOOD_REPLY),
                        ConnectionRefusedError("no"), ConnectionRefusedError("no"), ConnectionRefusedError("no"),
                        (200, GOOD_REPLY))
        c = jev.Client(FAKE_KEY, connection=conn)
        self.assertEqual(c.post(body)[0], 200)
        self.assertEqual(c.post(body), (200, GOOD_REPLY))            # the retry, transparent: one call
        self.assertEqual((conn.log["opened"], c.calls), (2, 2))
        # a used connection that fails and whose retry fails too is status 0 (two attempts, one call) …
        self.assertEqual(c.post(body), (0, {"error": "ConnectionRefusedError"}))
        self.assertEqual((conn.log["opened"], c.calls), (3, 3))
        self.assertIsNone(c._conn)
        # … a fresh connection that fails is status 0 after one attempt (no retry); then it recovers
        self.assertEqual(c.post(body), (0, {"error": "ConnectionRefusedError"}))
        self.assertEqual((conn.log["opened"], c.calls), (4, 4))
        self.assertEqual(c.post(body), (200, GOOD_REPLY))
        self.assertEqual((conn.log["opened"], c.calls), (5, 5))
        self.assertAlmostEqual(c.spent_usd, 0.000164 * 3)
        # through ask(): status 0 and the class name, stamps set, never the key
        conn2 = scripted(TimeoutError("slow"))
        a = jev.ask(None, body, client=jev.Client(FAKE_KEY, connection=conn2), clock=ticking(T0, T0 + timedelta(seconds=10)))
        self.assertEqual((a.status, a.error, a.intent, a.ms), (0, "TimeoutError", None, 10_000))
        self.assertNotIn(FAKE_KEY, json.dumps(dataclasses.asdict(a), ensure_ascii=False, default=str))
        # the real thing against a dead port: 0, fast, the connection dropped for the next attempt
        t0 = time.perf_counter()
        c = jev.Client(FAKE_KEY, host="127.0.0.1:1", timeout=2)
        self.assertEqual(c.post(body), (0, {"error": "ConnectionRefusedError"}))
        self.assertLess(time.perf_counter() - t0, 1.0)
        self.assertIsNone(c._conn)

    def test_sibling_shares_the_meter_and_never_retries(self):
        """Story 2.1 (F-9): the speed test's pool — a timed-out or dropped call is one failed call,
        not a retry, and every call counts on the server's client, which the spend cap reads."""
        body = {"model": "typesafe/jev-1.13", "state": {}, "questions": {}}
        parent_conn = scripted((200, GOOD_REPLY))
        parent = jev.Client(FAKE_KEY, host="example.test", timeout=10, connection=parent_conn)
        parent.post(body)
        conn = scripted((200, GOOD_REPLY), TimeoutError("slow"), (200, GOOD_REPLY))
        parent._connection = conn            # the sibling opens its connections from the same class
        sib = parent.sibling(timeout=5)
        self.assertEqual((sib.host, sib.timeout, sib.retry, parent.retry), ("example.test", 5, False, True))
        self.assertEqual(sib.post(body)[0], 200)
        # a used connection times out: one attempt, status 0, no second request on a new connection
        self.assertEqual(sib.post(body), (0, {"error": "TimeoutError"}))
        self.assertEqual((conn.log["opened"], len(conn.log["sent"])), (1, 2))
        self.assertEqual(sib.post(body)[0], 200)
        self.assertEqual(conn.log["sent"][0]["timeout"], 5)
        self.assertEqual(conn.log["sent"][0]["headers"]["Authorization"], f"Bearer {FAKE_KEY}")
        # one meter: the parent counts the sibling's three calls and two costs
        self.assertEqual((parent.calls, sib.calls), (4, 4))
        self.assertAlmostEqual(parent.spent_usd, 0.000164 * 3)
        self.assertNotIn(FAKE_KEY, repr(sib))


if __name__ == "__main__":
    unittest.main()
