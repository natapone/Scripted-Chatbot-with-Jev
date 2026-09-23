"""Story 1.6 — the S-3 replay instrument (`tests/rehearsal/replay_s3.py`), hermetic: the cases are
built from the catalogue without a network, and a pass runs against a scripted connection behind
the real `Client`."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from app import flow, jev
from tests.test_jev import FAKE_KEY, scripted
from tests.test_turn import Clock, reply

_spec = importlib.util.spec_from_file_location(
    "replay_s3", Path(__file__).resolve().parent / "rehearsal" / "replay_s3.py")
replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(replay)

FLOW = flow.load()
CAT = replay.read_catalogue()


class ReplayTests(unittest.TestCase):

    def test_cases_load_as_sessions_with_awaiting_and_history(self):
        cases = replay.load_cases(CAT)
        self.assertEqual(len(cases), 129)          # 125 from S-3 + four browse-by-roast/taste cases (Story 1.7)
        slots: dict = {}
        for c in cases:
            s = replay.build_session(c, FLOW)
            req_a = replay.turn.build_request(s, c["text"], replay.flow_for("A", FLOW))
            req_b = replay.turn.build_request(s, c["text"], replay.flow_for("B", FLOW))
            slot = (s.pending_prompt or {}).get("slot")
            slots[slot] = slots.get(slot, 0) + 1
            self.assertEqual(req_a["state"]["awaiting"], slot)
            self.assertEqual(sorted(s.live_contexts()), sorted(c["contexts"]))
            if c["shop_said"]:
                self.assertEqual(req_a["state"]["history"], [{"who": "bot", "text": c["shop_said"]}])
                self.assertEqual(req_a["state"]["shop_said"], c["shop_said"])
            else:
                self.assertEqual(req_a["state"]["history"], [])
            # B: S-3's shape — the same shop_said and questions, no awaiting, no history
            self.assertIsNone(req_b["state"]["awaiting"])
            self.assertEqual(req_b["state"]["history"], [])
            self.assertEqual(req_b["state"]["shop_said"], req_a["state"]["shop_said"])
            self.assertEqual(req_b["questions"], req_a["questions"])
        self.assertEqual({k: v for k, v in slots.items() if k not in (None, "confirmation")},
                         {"quantity": 3, "payment": 3, "promotion": 4, "delivery": 3, "brew": 2, "roast": 1})
        self.assertEqual(slots.get("confirmation"), 6)
        # the ask_quantity case whose context makes `inform` by state
        six = next(c for c in cases if c["text"].startswith("6 ถุงเลยค่ะ"))
        self.assertEqual(six["accept_intents"], ["inform", "ask_promotion", "order_product"])

    def test_pass_scores_with_accept_intents_and_voids_after_ten_failures(self):
        cases = replay.load_cases(CAT)
        six = next(c for c in cases if c["text"].startswith("6 ถุงเลยค่ะ"))    # want inform; accept ask_promotion
        greet = next(c for c in cases if c["intent"] == "greet")
        # 1: Jev says ask_promotion but the pending quantity slot is filled → the loop's inform, by state
        # 2: greet matched; 3: greet below the threshold → the loop's `none`, Jev's own still greet
        conn = scripted((200, reply("ask_promotion", 0.6, quantity="6")),
                        (200, reply("greet", 0.9)), (200, reply("greet", 0.3)))
        client = jev.Client(FAKE_KEY, connection=conn)
        s = replay.run_pass([six, greet, dict(greet, n=999)], CAT, FLOW, client, "A", clock=Clock(), echo=lambda *_: None)
        self.assertEqual(s["status"], "COMPLETE")
        r1, r2, r3 = s["records"]
        self.assertEqual((r1["loop"], r1["jev"], r1["by_state"], r1["loop_ok"], r1["jev_ok"], r1["jev_strict"]),
                         ("inform", "ask_promotion", True, True, True, False))
        self.assertEqual((r2["loop_ok"], r2["loop_strict"]), (True, True))
        self.assertEqual((r3["loop"], r3["jev"], r3["loop_ok"], r3["jev_ok"]), ("none", "greet", False, True))
        self.assertEqual((s["loop_ok"], s["jev_ok"], s["jev_strict"]), (2, 3, 2))
        self.assertEqual(r1["entities"][[e["entity"] for e in r1["entities"]].index("quantity")]["ok"], True)
        self.assertEqual(s["p50_ms"], 338)
        self.assertEqual(conn.log["sent"][0]["body"]["state"]["awaiting"], "quantity")
        self.assertNotIn(FAKE_KEY, repr(s))

        # ten failed calls in a row void the pass; the eleventh case is never sent
        dead = scripted(*[ConnectionRefusedError()] * 12)
        client = jev.Client(FAKE_KEY, connection=dead)
        s = replay.run_pass(cases[:12], CAT, FLOW, client, "B", clock=Clock(), echo=lambda *_: None)
        self.assertEqual((s["status"], s["cases"], s["failed"], client.calls), ("VOID", 10, 10, 10))
        self.assertIsNone(dead.log["sent"][0]["body"]["state"]["awaiting"])
        self.assertEqual(replay.verdict(s, s), "VOID")
        # the pre-registered rule: PASS iff A ≥ B and A ≥ 119
        a, b = {"status": "COMPLETE", "loop_ok": 120}, {"status": "COMPLETE", "loop_ok": 121}
        self.assertEqual((replay.verdict(a, b), replay.verdict(b, a), replay.verdict(dict(a, loop_ok=118), dict(b, loop_ok=100))),
                         ("FAIL", "PASS", "FAIL"))


if __name__ == "__main__":
    unittest.main()
