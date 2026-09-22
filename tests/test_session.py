"""Story 1.3 — the session and its store. Hermetic: snapshots go to a temp dir, never the repo's `var/`."""
from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import config, flow, session

ROOT = Path(__file__).resolve().parent.parent
FAKE_KEY = "sk-or-v1-test-key-never-real"
T0 = datetime(2026, 9, 22, 6, 41, 2, 0, tzinfo=timezone.utc)

CONTRACT_VARIABLES = {
    # § Session
    "session_id", "flow_version", "created_at", "updated_at", "turn_no", "last_turn_id",
    # § Dialogue memory
    "contexts", "focus_sku", "pending_prompt", "last_bot_message", "live_buttons", "options_shown",
    "miss_count", "promos_offered",
    # § The order form (nested as § A snapshot writes it) and the turn log
    "order", "log",
}
ORDER_FORM = {"lines", "promo_applied", "payment", "delivery_text", "recommend", "order_code", "confirmed_at"}


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def tick(self, **kw):
        self.t += timedelta(**kw)


class SessionShapeTests(unittest.TestCase):
    def test_every_contract_variable_and_only_those(self):  # Verify 3
        s = session.Session.new("x", "y", now=T0)
        keys = set(dataclasses.asdict(s))
        self.assertTrue(CONTRACT_VARIABLES <= keys, CONTRACT_VARIABLES - keys)
        self.assertEqual(keys - CONTRACT_VARIABLES, {"transcript", "raw", "last_response"})  # the three the Story adds
        self.assertEqual(set(s.order), ORDER_FORM)
        self.assertEqual(s.order["recommend"], {"brew": None, "roast": None})
        self.assertEqual((s.session_id, s.flow_version, s.turn_no, s.last_turn_id, s.miss_count), ("x", "y", 0, None, 0))
        self.assertEqual((s.created_at, s.updated_at), ("2026-09-22T06:41:02.000Z", "2026-09-22T06:41:02.000Z"))
        self.assertEqual((s.contexts, s.focus_sku, s.pending_prompt, s.last_bot_message), ({}, None, None, None))
        self.assertEqual((s.live_buttons, s.options_shown, s.promos_offered, s.log, s.transcript), ([], [], [], [], []))
        # a fresh session gets a uuid; the memory-only fields are not in the snapshot and not in the repr
        t = session.Session.new(flow_version="abc123")
        self.assertEqual(len(t.session_id), 36)
        self.assertNotIn("raw", repr(t))
        self.assertNotIn("last_response", repr(t))
        snap = t.to_snapshot()
        self.assertNotIn("raw", snap)
        self.assertNotIn("last_response", snap)
        self.assertEqual(set(snap), CONTRACT_VARIABLES | {"transcript"})
        # flow_version is the first six hex of the catalogue's sha256
        v = session.flow_version_of(flow.CATALOGUE)
        self.assertEqual(len(v), 6)
        int(v, 16)
        # the copy is deep for the state and shares the memory-only fields
        t.contexts["offer_product"] = {"expires_after_turn": 2, "params": {"sku": "DH-001"}}
        t.raw["1"] = {"request": {}, "response": {}}
        c = t.copy()
        self.assertEqual(c.to_snapshot(), t.to_snapshot())
        c.contexts["offer_product"]["params"]["sku"] = "DH-002"
        self.assertEqual(t.contexts["offer_product"]["params"]["sku"], "DH-001")
        self.assertIs(c.raw, t.raw)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.var = Path(self.tmp.name) / "var"
        self.clock = Clock()

    def store(self, ttl=1800, version="a3f9c1"):
        return session.Store(version, self.var, ttl_s=ttl, clock=self.clock)

    def test_round_trip_through_a_snapshot(self):  # AC-3 (file = state − raw), AC-6 (restore)
        st = self.store()
        s = st.new()
        self.assertFalse(self.var.exists())                       # nothing written until a commit
        self.assertIs(st.get(s.session_id), s)
        s.turn_no, s.focus_sku, s.last_turn_id = 3, "DH-001", "t3"
        s.contexts = {"offer_product": {"expires_after_turn": 5, "params": {"sku": "DH-001"}}}
        s.last_bot_message = {"id": "m4", "text": "เกอิชา ถุงละ 350 บาทค่ะ", "text_for_jev": "เกอิชา ถุงละ 350 บาทค่ะ"}
        s.live_buttons = [{"label": "เอาตัวนี้", "intent": "affirm", "params": {}, "message_id": "m4"}]
        s.log = [{"turn_no": 1, "input": {"kind": "typed", "text": "สวัสดีค่ะ"}, "outcome": "matched"}]
        s.transcript = [{"who": "bot", "id": "m1", "text": "สวัสดีค่ะ", "buttons": [], "variant": "plain", "response_id": "greet"}]
        s.raw = {"1": {"request": {"model": "x"}, "response": {"answers": {}, "key?": FAKE_KEY}}}
        s.last_response = {"outcome": "matched"}
        self.clock.tick(seconds=5)
        st.commit(s)
        path = self.var / "sessions" / f"{s.session_id}.json"
        self.assertTrue(path.is_file())
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), [path.name])   # no tmp left behind
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk, s.to_snapshot())
        self.assertNotIn("raw", on_disk)
        self.assertNotIn("last_response", on_disk)
        self.assertNotIn(FAKE_KEY, path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["updated_at"], "2026-09-22T06:41:07.000Z")   # commit stamps updated_at
        self.assertEqual(on_disk["created_at"], "2026-09-22T06:41:02.000Z")
        self.assertEqual(on_disk["contexts"]["offer_product"]["params"]["sku"], "DH-001")
        self.assertEqual(on_disk["order"]["lines"], [])
        # a new Store over the same dir (the server restarted): the state comes back minus raw
        st2 = self.store()
        self.assertFalse(st2.in_memory(s.session_id))
        r = st2.get(s.session_id)
        self.assertIsNotNone(r)
        self.assertIsNot(r, s)
        self.assertEqual(r.to_snapshot(), s.to_snapshot())
        self.assertEqual((r.raw, r.last_response), ({}, None))
        self.assertTrue(st2.in_memory(s.session_id))
        self.assertIs(st2.get(s.session_id), r)                  # loaded once, then memory
        # unknown ids, empty ids and path tricks are None, not errors
        for bad in (None, "", "nope", "../x", "a/b", ".", ".."):
            self.assertIsNone(st2.get(bad), bad)
        # one lock per session, the same object each time
        self.assertIs(st2.lock(s.session_id), st2.lock(s.session_id))
        self.assertIsNot(st2.lock(s.session_id), st2.lock("other"))

    def test_expiry_end_and_flow_version(self):  # AC-6
        st = self.store(ttl=1)
        s = st.new()
        st.commit(s)
        path = self.var / "sessions" / f"{s.session_id}.json"
        self.assertTrue(path.exists())
        self.clock.tick(seconds=1)
        self.assertIs(st.get(s.session_id), s)                   # exactly the TTL: still live
        self.clock.tick(milliseconds=1)
        self.assertIsNone(st.get(s.session_id))                  # past it: unknown
        self.assertFalse(path.exists())                          # and the snapshot is gone
        self.assertFalse(st.in_memory(s.session_id))
        # a fresh Store finds the snapshot but sees it expired, so deletes it the same way
        s2 = st.new()
        st.commit(s2)
        self.clock.tick(seconds=2)
        st3 = self.store(ttl=1)
        self.assertIsNone(st3.get(s2.session_id))
        self.assertFalse((self.var / "sessions" / f"{s2.session_id}.json").exists())
        # end deletes the file and forgets the session; ending twice is harmless
        s3 = st.new()
        st.commit(s3)
        p3 = self.var / "sessions" / f"{s3.session_id}.json"
        self.assertTrue(p3.exists())
        st.end(s3.session_id)
        st.end(s3.session_id)
        self.assertFalse(p3.exists())
        self.assertIsNone(st.get(s3.session_id))
        # a snapshot made under another flow file is ended, not restored
        s4 = st.new()
        st.commit(s4)
        st4 = self.store(ttl=1800, version="ffffff")
        self.assertIsNone(st4.get(s4.session_id))
        self.assertFalse((self.var / "sessions" / f"{s4.session_id}.json").exists())
        # a corrupt file is unknown, and updated_at that does not parse counts as expired
        (self.var / "sessions" / "bad.json").write_text("{not json", encoding="utf-8")
        self.assertIsNone(st.get("bad"))
        s5 = st.new()
        s5.updated_at = "yesterday"
        self.assertTrue(st.expired(s5))
        # nothing was ever written under the repo
        self.assertFalse((ROOT / "var").exists())

    def test_config_switches(self):  # SESSION_TTL_S / SPEND_CAP_USD / VAR_DIR
        good = {"OPENROUTER_API_KEY": FAKE_KEY, "THB_PER_USD": "34.9", "RATE_DATE": "2026-09-22"}
        no_file = Path("/nonexistent/.env")
        cfg = config.load(env_path=no_file, environ=good)
        self.assertEqual((cfg.session_ttl_s, cfg.spend_cap_usd, cfg.var_dir), (1800.0, 0.50, ROOT / "var"))
        cfg = config.load(env_path=no_file, environ={**good, "SESSION_TTL_S": "1", "SPEND_CAP_USD": "0",
                                                     "VAR_DIR": self.tmp.name})
        self.assertEqual((cfg.session_ttl_s, cfg.spend_cap_usd, cfg.var_dir), (1.0, 0.0, Path(self.tmp.name)))
        self.assertNotIn(FAKE_KEY, repr(cfg))
        for name, bad in (("SESSION_TTL_S", "x"), ("SESSION_TTL_S", "0"), ("SPEND_CAP_USD", "-1"), ("SPEND_CAP_USD", "abc")):
            with self.assertRaises(config.ConfigError) as cm:
                config.load(env_path=no_file, environ={**good, name: bad})
            self.assertIn(name, str(cm.exception))
            self.assertNotIn(FAKE_KEY, str(cm.exception))


if __name__ == "__main__":
    unittest.main()
