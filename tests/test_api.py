"""Story 1.3 — the conversation over HTTP. Loopback on an ephemeral port; the Jev client rides a
scripted fake connection (no socket to the outside); snapshots in a temp dir."""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from app import config, flow, jev, server, session
from tests.test_jev import FAKE_KEY, scripted
from tests.test_turn import reply

FLOW = flow.load()
GOOD = {"OPENROUTER_API_KEY": FAKE_KEY, "THB_PER_USD": "34.9", "RATE_DATE": "2026-09-22"}


class Api:
    """One server on 127.0.0.1:0 over a store in `var`, the client scripted with `steps`."""
    def __init__(self, test, var: Path, *steps, ttl="1800"):
        cfg = config.load(env_path=Path("/nonexistent/.env"),
                          environ={**GOOD, "VAR_DIR": str(var), "SESSION_TTL_S": ttl})
        self.conn = scripted(*steps)
        self.client = jev.Client(FAKE_KEY, connection=self.conn)
        self.store = session.Store(session.flow_version_of(flow.CATALOGUE), cfg.var_dir, ttl_s=cfg.session_ttl_s)
        self.httpd = server.make_server(cfg, port=0, flow=FLOW, store=self.store, client=self.client)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        test.addCleanup(self.stop)
        self.bodies = []                                   # every response body, for the key check

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def call(self, method, path, body=None, raw: bytes | None = None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = raw if raw is not None else (json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None)
        h = {"Content-Type": "application/json"} if payload is not None else {}
        h.update(headers or {})
        c.request(method, path, body=payload, headers=h)
        r = c.getresponse()
        text = r.read().decode("utf-8")
        c.close()
        self.bodies.append(text)
        try:
            return r.status, json.loads(text)
        except ValueError:
            return r.status, text

    def get_session(self, sid=""):
        return self.call("GET", f"/api/session?id={sid}")

    def turn(self, sid, tid, text=None, button=None):
        body = {"session_id": sid, "turn_id": tid}
        if text is not None:
            body["text"] = text
        if button is not None:
            body["button"] = button
        return self.call("POST", "/api/turn", body)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.var = Path(self.tmp.name) / "var"

    def test_session_typed_turn_click_and_repeat(self):  # AC-1/AC-5 over HTTP; the Story's Verify 2
        api = Api(self, self.var, (200, reply("ask_price", 0.93, product="DH-001", rid="gen-1")))
        status, s = api.get_session()
        self.assertEqual(status, 200)
        self.assertEqual(sorted(s), ["live_buttons", "log", "new", "raw", "session_id", "transcript", "turn_no"])
        self.assertTrue(s["new"])
        sid = s["session_id"]
        self.assertEqual(len(sid), 36)
        self.assertEqual((s["turn_no"], s["log"], s["raw"]), (0, [], {}))
        self.assertEqual(len(s["transcript"]), 1)
        g = s["transcript"][0]
        self.assertEqual((g["who"], g["id"], g["response_id"], g["variant"]), ("bot", "m1", "greet", "plain"))
        self.assertTrue(g["text"].startswith("สวัสดีค่ะ Beanly"))
        self.assertEqual([b["label"] for b in g["buttons"]], ["ช่วยแนะนำหน่อย", "ดูเมล็ดทั้งหมด", "มีโปรอะไรบ้าง"])
        self.assertEqual(s["live_buttons"], [dict(b, message_id="m1") for b in g["buttons"]])
        self.assertTrue((self.var / "sessions" / f"{sid}.json").is_file())
        # the same id again: not new, the same transcript
        status, again = api.get_session(sid)
        self.assertEqual((status, again["new"], again["session_id"], again["transcript"]), (200, False, sid, s["transcript"]))
        # a typed turn end to end
        status, t = api.turn(sid, "t1", text="เกอิชาถุงละเท่าไหร่คะ")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(t), ["bot", "ended", "log_entry", "model_status", "outcome", "raw", "session_id", "turn_no", "you"])
        self.assertEqual((t["outcome"], t["turn_no"], t["model_status"], t["ended"], t["session_id"]), ("matched", 1, "live", False, sid))
        self.assertEqual(t["you"], {"who": "you", "text": "เกอิชาถุงละเท่าไหร่คะ", "kind": "typed", "masked": False})
        self.assertEqual(t["bot"][0]["text"], "เกอิชา ถุงละ 980 บาทค่ะ")
        self.assertEqual([b["label"] for b in t["bot"][0]["buttons"]], ["เอาตัวนี้", "ดูตัวอื่น"])
        self.assertEqual((t["log_entry"]["jev"]["intent"], t["log_entry"]["jev"]["request_id"], t["log_entry"]["outcome"]), ("ask_price", "gen-1", "matched"))
        self.assertIsInstance(t["log_entry"]["jev"]["ms"], int)
        self.assertEqual(t["raw"]["request"]["state"]["customer_said"], "เกอิชาถุงละเท่าไหร่คะ")
        self.assertEqual(t["raw"]["response"]["id"], "gen-1")
        self.assertEqual(api.client.calls, 1)
        # the repeat: the same body, Jev not called again
        status, t2 = api.turn(sid, "t1", text="เกอิชาถุงละเท่าไหร่คะ")
        self.assertEqual((status, t2["repeat"], api.client.calls), (200, True, 1))
        self.assertEqual(dict(t2, repeat=None), dict(t, repeat=None))
        # a click: no call, turn_no 2; a stale one: ignored
        status, c = api.turn(sid, "t2", button={"label": "ดูตัวอื่น", "intent": "browse_catalog", "params": {}, "message_id": "m3"})
        self.assertEqual((status, c["outcome"], c["turn_no"], c["you"]["kind"], api.client.calls), (200, "matched", 2, "clicked", 1))
        self.assertNotIn("jev", c["log_entry"])
        status, c = api.turn(sid, "t3", button={"label": "ดูตัวอื่น", "intent": "browse_catalog", "params": {}, "message_id": "m3"})
        self.assertEqual((status, c["outcome"], c["turn_no"]), (200, "ignored", 2))
        # the session view now: transcript of five bubbles, log of two, raw of one, the clickable buttons
        status, s = api.get_session(sid)
        self.assertEqual((s["turn_no"], len(s["transcript"]), len(s["log"]), list(s["raw"])), (2, 5, 2, ["t1"]))
        self.assertEqual([b["who"] for b in s["transcript"]], ["bot", "you", "bot", "you", "bot"])
        self.assertEqual(s["live_buttons"][0]["message_id"], "m5")
        self.assertEqual([b["label"] for b in s["live_buttons"]], ["ดอยหอม", "คั่วบ้านนา", "เมล็ดเมือง"])
        # errors are JSON with a status: bad bodies, a missing/unknown session, a bounded body
        self.assertEqual(api.call("POST", "/api/turn", raw=b"{not json")[0], 400)
        self.assertEqual(api.call("POST", "/api/turn", raw=b"[1,2]")[0], 400)
        self.assertEqual(api.call("POST", "/api/turn", raw=b"")[0], 400)
        self.assertEqual(api.turn("", "t9", text="x")[0], 400)
        self.assertEqual(api.turn("nope", "t9", text="x")[0], 404)
        self.assertEqual(api.turn(sid, "t9", text="")[0], 400)
        self.assertEqual(api.turn(sid, "", text="x")[0], 400)
        self.assertEqual(api.turn(sid, "t9")[0], 400)
        status, e = api.turn(sid, "t9", text="x", button={})
        self.assertEqual((status, list(e)), (400, ["error"]))
        big = json.dumps({"session_id": sid, "turn_id": "t9", "text": "x" * 70_000}).encode()
        self.assertEqual(api.call("POST", "/api/turn", raw=big)[0], 413)
        self.assertEqual(api.call("POST", "/api/nope", body={})[0], 404)
        self.assertEqual(api.call("GET", "/api/turn")[0], 404)
        self.assertEqual(api.client.calls, 1)
        # the key is in no response body; /api/config still has only its three fields
        self.assertEqual(api.call("GET", "/api/config")[1], {"model": "typesafe/jev-1.13", "thb_per_usd": 34.9, "rate_date": "2026-09-22"})
        for body in api.bodies:
            self.assertNotIn(FAKE_KEY, body)
            self.assertNotIn("Bearer", body)
        self.assertNotIn(FAKE_KEY, (self.var / "sessions" / f"{sid}.json").read_text(encoding="utf-8"))

    def test_restore_after_restart_expiry_and_end(self):  # AC-6, the server half
        api = Api(self, self.var, (200, reply("ask_price", 0.93, product="DH-001", rid="gen-1")),
                  (200, reply("faq.shipping_fee", 0.9, rid="gen-2")))
        sid = api.get_session()[1]["session_id"]
        t1 = api.turn(sid, "t1", text="เกอิชาถุงละเท่าไหร่คะ")[1]
        before = api.get_session(sid)[1]
        self.assertEqual(list(before["raw"]), ["t1"])
        api.stop()
        # a new server over the same var_dir: the transcript, the buttons and the log return; raw is empty
        api2 = Api(self, self.var, (200, reply("faq.shipping_fee", 0.9, rid="gen-2")))
        status, after = api2.get_session(sid)
        self.assertEqual(status, 200)
        self.assertFalse(after["new"])
        self.assertEqual((after["session_id"], after["turn_no"]), (sid, 1))
        self.assertEqual(after["transcript"], before["transcript"])
        self.assertEqual(after["live_buttons"], before["live_buttons"])
        self.assertEqual(after["log"], before["log"])
        self.assertEqual(after["raw"], {})
        # and the next turn continues: the request is built from the restored state
        status, t2 = api2.turn(sid, "t2", text="ค่าส่งเท่าไหร่คะ")
        self.assertEqual((status, t2["outcome"], t2["turn_no"]), (200, "matched", 2))
        self.assertEqual(t2["raw"]["request"]["state"]["shop_said"], t1["bot"][0]["text"])
        self.assertEqual(len(t2["raw"]["request"]["questions"]["intent"]["criteria"]), 25)   # offer_product still live
        self.assertEqual(t2["raw"]["request"]["state"]["history"][-2:],
                         [{"who": "customer", "text": "เกอิชาถุงละเท่าไหร่คะ"}, {"who": "bot", "text": t1["bot"][0]["text"]}])
        # a repeated turn_id after a restart is not re-processed either
        api2.stop()
        api3 = Api(self, self.var)
        status, r = api3.turn(sid, "t2", text="ค่าส่งเท่าไหร่คะ")
        self.assertEqual((status, r["outcome"], r["turn_no"], r["log_entry"]["turn_id"], api3.client.calls), (200, "repeat", 2, "t2", 0))
        # end: the snapshot goes, the id is unknown, GET makes a new session
        path = self.var / "sessions" / f"{sid}.json"
        self.assertTrue(path.exists())
        self.assertEqual(api3.call("POST", "/api/session/end", {"session_id": sid}), (200, {"ended": True, "session_id": sid}))
        self.assertFalse(path.exists())
        self.assertEqual(api3.call("POST", "/api/session/end", {"session_id": sid})[1]["ended"], False)
        self.assertEqual(api3.call("POST", "/api/session/end", {})[0], 400)
        status, fresh = api3.get_session(sid)
        self.assertTrue(fresh["new"])
        self.assertNotEqual(fresh["session_id"], sid)
        api3.stop()
        # SESSION_TTL_S=1: after the wait the id is unknown and a new session comes back
        api4 = Api(self, self.var, ttl="1")
        sid4 = api4.get_session()[1]["session_id"]
        self.assertFalse(api4.get_session(sid4)[1]["new"])
        import time
        time.sleep(1.2)
        status, s = api4.get_session(sid4)
        self.assertTrue(s["new"])
        self.assertNotEqual(s["session_id"], sid4)
        self.assertFalse((self.var / "sessions" / f"{sid4}.json").exists())
        for a in (api, api2, api3, api4):
            for body in a.bodies:
                self.assertNotIn(FAKE_KEY, body)

    def test_make_server_builds_its_own_parts(self):
        cfg = config.load(env_path=Path("/nonexistent/.env"), environ={**GOOD, "VAR_DIR": str(self.var), "JEV_HOST": "127.0.0.1:1"})
        httpd = server.make_server(cfg, port=0)
        try:
            self.assertEqual(len(httpd.flow.intents), 26)
            self.assertEqual(httpd.store.dir, self.var / "sessions")
            self.assertEqual(httpd.store.flow_version, session.flow_version_of(flow.CATALOGUE))
            self.assertEqual((httpd.client.host, httpd.client.timeout, httpd.client.calls), ("127.0.0.1:1", 10.0, 0))
            self.assertNotIn(FAKE_KEY, repr(httpd.client))
            self.assertFalse(self.var.exists())                     # nothing written by building it
        finally:
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
