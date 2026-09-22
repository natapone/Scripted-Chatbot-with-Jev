"""Story 1.3 — the turn loop. Hermetic: Jev is a scripted connection behind the real `Client`
(no socket), the clock is fixed, snapshots go to a temp dir."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import flow, jev, session, turn
from tests.test_jev import FAKE_KEY, scripted

T0 = datetime(2026, 9, 22, 6, 48, 10, 0, tzinfo=timezone.utc)
FLOW = flow.load()
ADDRESS = "สมชาย ใจดี 123/4 ซอยสุขุมวิท 50 คลองเตย กรุงเทพ 10110 โทร 081-000-0000"


def reply(intent="greet", confidence=0.97, cost=0.000164, rid="gen-1", **entities):
    """A well-formed Jev answer: the intent plus the five entity answers (not_mentioned unless given)."""
    answers = {"intent": {"type": "choice", "choice": intent, "confidence": confidence,
                          "probabilities": {intent: confidence}}}
    for name in ("product", "quantity", "brew", "roast", "payment"):
        answers[name] = {"type": "choice", "choice": entities.get(name, "not_mentioned")}
    return {"id": rid, "answers": answers, "usage": {"cost": cost}}


class Clock:
    """Advances by `step` per call, so t_sent/t_received differ by a fixed ms."""
    def __init__(self, t=T0, step_ms=338):
        self.t, self.step = t, timedelta(milliseconds=step_ms)

    def __call__(self):
        t = self.t
        self.t += self.step
        return t


class Rig:
    """A store in a temp dir, a fresh session with the greeting, and a client scripted with replies."""
    def __init__(self, test, *steps, ttl=1800, cap=0.50):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.var = Path(self.tmp.name)
        self.clock = Clock()
        self.conn = scripted(*steps)
        self.client = jev.Client(FAKE_KEY, connection=self.conn)
        self.store = session.Store("abc123", self.var, ttl_s=ttl, clock=self.clock)
        self.cap = cap
        self.s = turn.new_session(self.store, FLOW)

    def typed(self, text, tid, sid=None):
        return turn.run_turn(self.store, FLOW, self.client, sid or self.s.session_id, tid, text=text,
                             spend_cap_usd=self.cap, clock=self.clock)

    def click(self, button, tid, sid=None):
        return turn.run_turn(self.store, FLOW, self.client, sid or self.s.session_id, tid, button=button,
                             spend_cap_usd=self.cap, clock=self.clock)

    def state(self, sid=None):
        return self.store.get(sid or self.s.session_id)

    def snapshot(self, sid=None):
        return json.loads((self.var / "sessions" / f"{sid or self.s.session_id}.json").read_text(encoding="utf-8"))


def frozen(s: session.Session) -> dict:
    """The state a miss may not touch: everything but the log, the transcript, miss_count, the
    turn-id/response bookkeeping and the timestamp."""
    d = s.to_snapshot()
    for k in ("log", "transcript", "miss_count", "last_turn_id", "updated_at"):
        d.pop(k)
    return d


class ClassifyTests(unittest.TestCase):
    def test_request_from_the_session(self):  # AC-1
        r = Rig(self, (200, reply("ask_price", 0.93, product="DH-001")))
        s = r.s
        greeting = FLOW.intents[0]["response"]
        self.assertEqual(s.last_bot_message["text"], greeting)
        # a session that has been going: four typed turns and a pending slot under ask_quantity
        s.transcript += [{"who": "you", "text": "ขอดูเมล็ดหน่อย", "kind": "typed", "masked": False},
                         {"who": "bot", "id": "m2", "text": "มี 10 ตัวค่ะ", "buttons": [], "variant": "plain", "response_id": "browse_catalog"},
                         {"who": "you", "text": "เกอิชา", "kind": "typed", "masked": False},
                         {"who": "bot", "id": "m3", "text": "เกอิชา 980 บาทค่ะ", "buttons": [], "variant": "plain", "response_id": "ask_price"},
                         {"who": "you", "text": "เอาค่ะ", "kind": "typed", "masked": False},
                         {"who": "bot", "id": "m4", "text": "รับกี่ถุงดีคะ?", "buttons": [], "variant": "plain", "response_id": "inform"},
                         {"who": "you", "text": ADDRESS, "kind": "typed", "masked": True},
                         {"who": "bot", "id": "m5", "text": f"ส่งไปที่ {ADDRESS} นะคะ รับกี่ถุงดีคะ?", "buttons": [], "variant": "read-back", "response_id": "give_delivery_details"},
                         {"who": "you", "text": "ค่าส่งเท่าไหร่คะ", "kind": "typed", "masked": False},
                         {"who": "bot", "id": "m6", "text": "ค่าส่ง 50 บาทค่ะ", "buttons": [], "variant": "plain", "response_id": "faq.shipping_fee"}]
        s.order["delivery_text"] = ADDRESS
        s.last_bot_message = {"id": "m6", "text": f"ค่าส่ง 50 บาทค่ะ ส่งไป {ADDRESS}", "text_for_jev": f"ค่าส่ง 50 บาทค่ะ ส่งไป {turn.MASK_FOR_JEV}"}
        s.pending_prompt = {"slot": "quantity", "context": "ask_quantity", "params": {"sku": "DH-001"}, "message_id": "m4"}
        s.contexts = {"ask_quantity": {"expires_after_turn": 7, "params": {"sku": "DH-001"}}}
        s.turn_no = 5
        v = turn.classify(s, "1 ถุงค่ะ", FLOW, r.client, spend_cap_usd=0.50, clock=r.clock)
        req = v.request
        self.assertEqual(sorted(req), ["model", "questions", "state"])
        self.assertEqual(req["state"]["shop_said"], s.last_bot_message["text_for_jev"])
        self.assertEqual(req["state"]["customer_said"], "1 ถุงค่ะ")
        self.assertEqual(req["state"]["awaiting"], "quantity")
        # the last four turns, customer and bot, the delivery details masked both ways
        self.assertEqual(req["state"]["history"], [
            {"who": "customer", "text": "เกอิชา"}, {"who": "bot", "text": "เกอิชา 980 บาทค่ะ"},
            {"who": "customer", "text": "เอาค่ะ"}, {"who": "bot", "text": "รับกี่ถุงดีคะ?"},
            {"who": "customer", "text": turn.MASK_FOR_JEV}, {"who": "bot", "text": f"ส่งไปที่ {turn.MASK_FOR_JEV} นะคะ รับกี่ถุงดีคะ?"},
            {"who": "customer", "text": "ค่าส่งเท่าไหร่คะ"}, {"who": "bot", "text": "ค่าส่ง 50 บาทค่ะ"}])
        self.assertNotIn(ADDRESS, json.dumps(req, ensure_ascii=False))
        self.assertNotIn("081-000-0000", json.dumps(req, ensure_ascii=False))
        # the intent options: the 22 globals + none (ask_quantity brings nothing in) …
        self.assertEqual(len(req["questions"]["intent"]["criteria"]), 23)
        self.assertEqual(list(req["questions"]["intent"]["criteria"])[-1], "none")
        # … and under offer_product: + affirm, deny
        s.contexts = {"offer_product": {"expires_after_turn": 7, "params": {"sku": "DH-001"}}}
        crit = turn.build_request(s, "เอาค่ะ", FLOW)["questions"]["intent"]["criteria"]
        self.assertEqual(len(crit), 25)
        self.assertIn("affirm", crit)
        # what was sent is what was built, with the key in the header only
        sent = r.conn.log["sent"][0]
        self.assertEqual(sent["body"], req)
        self.assertNotIn(FAKE_KEY, json.dumps(req))
        # a fresh session: the greeting is the shop's last message, no awaiting, history = the greeting
        fresh = Rig(self).s
        req = turn.build_request(fresh, "สวัสดีค่ะ", FLOW)
        self.assertEqual(req["state"], {"shop_said": greeting, "customer_said": "สวัสดีค่ะ", "awaiting": None,
                                        "history": [{"who": "bot", "text": greeting}]})
        # with fewer than four turns everything is sent; with more, exactly four customer turns
        self.assertEqual(sum(1 for h in turn.history(s) if h["who"] == "customer"), 4)
        self.assertEqual(turn.history(fresh), [{"who": "bot", "text": greeting}])
        # mask(): the details, and only the details, become the placeholder
        self.assertEqual(turn.mask(f"ส่งไป {ADDRESS} ค่ะ", ADDRESS), f"ส่งไป {turn.MASK_FOR_JEV} ค่ะ")
        self.assertEqual(turn.mask("ค่าส่ง 50 บาท", ADDRESS), "ค่าส่ง 50 บาท")
        self.assertEqual(turn.mask("ค่าส่ง 50 บาท", None), "ค่าส่ง 50 บาท")
        self.assertEqual(turn.mask(None, ADDRESS), "")

    def test_state_before_the_classifier_and_the_threshold(self):  # AC-2
        r = Rig(self, (200, reply("none", 0.91, quantity="1")),            # a bare "1 ถุงค่ะ" under ask_quantity
                (200, reply("faq.shipping_fee", 0.88, quantity="2")),   # anything else with the slot filled
                (200, reply("ask_price", 0.44, product="DH-001")),      # below 0.45
                (200, reply("affirm", 0.49)),                           # 0.49 matches: เอาค่ะ
                (200, reply("none", 0.95)),
                (200, reply("affirm", 0.99)),                           # not in scope without a context
                (200, {"id": "gen-e", "usage": {"cost": 0.0001}}),      # 200 with no answers
                (500, {"error": "x"}),
                ConnectionRefusedError("no"), ConnectionRefusedError("no"))   # status 0 (the used connection retries once)
        s = r.s
        s.pending_prompt = {"slot": "quantity", "context": "ask_quantity", "params": {"sku": "DH-001"}, "message_id": "m1"}
        s.contexts = {"ask_quantity": {"expires_after_turn": 3, "params": {"sku": "DH-001"}}}
        v = turn.classify(s, "1 ถุงค่ะ", FLOW, r.client, spend_cap_usd=0.50, clock=r.clock)
        self.assertEqual((v.outcome, v.intent, v.by_state), ("matched", "inform", True))
        self.assertEqual((v.answer.intent, v.answer.confidence), ("none", 0.91))    # Jev's real answer kept
        self.assertEqual((v.sku, v.product_from), ("DH-001", "context:ask_quantity"))
        self.assertEqual(v.entities["quantity"], "1")
        block = turn.jev_block(v.answer, v.by_state)
        self.assertEqual((block["intent"], block["confidence"], block["by_state"]), ("none", 0.91, True))
        self.assertEqual(sorted(block), sorted(["status", "intent", "confidence", "entities", "t_sent", "t_received",
                                               "ms", "cost_usd", "request_id", "by_state"]))
        self.assertEqual((block["ms"], block["cost_usd"], block["request_id"], block["status"]), (338, 0.000164, "gen-1", 200))
        v = turn.classify(s, "2 ถุง ค่าส่งเท่าไหร่", FLOW, r.client, spend_cap_usd=0.50, clock=r.clock)
        self.assertEqual((v.outcome, v.intent, v.by_state, v.answer.intent), ("matched", "inform", True, "faq.shipping_fee"))
        # no pending slot: the threshold decides
        s.pending_prompt, s.contexts = None, {}
        v = turn.classify(s, "เกอิชาเท่าไหร่", FLOW, r.client, spend_cap_usd=0.50, clock=r.clock)
        self.assertEqual((v.outcome, v.intent, v.answer.intent, v.answer.confidence), ("fallback", None, "ask_price", 0.44))
        s.contexts = {"offer_product": {"expires_after_turn": 3, "params": {"sku": "DH-001"}}}
        v = turn.classify(s, "เอาค่ะ", FLOW, r.client, spend_cap_usd=0.50, clock=r.clock)
        self.assertEqual((v.outcome, v.intent, v.by_state), ("matched", "affirm", False))
        self.assertEqual((v.sku, v.product_from), ("DH-001", "context:offer_product"))
        v = turn.classify(s, "ฝนตกไหม", FLOW, r.client, spend_cap_usd=0.50, clock=r.clock)
        self.assertEqual((v.outcome, v.intent, v.answer.intent), ("fallback", None, "none"))
        s.contexts = {}
        v = turn.classify(s, "เอาค่ะ", FLOW, r.client, spend_cap_usd=0.50, clock=r.clock)
        self.assertEqual((v.outcome, v.answer.intent), ("fallback", "affirm"))          # affirm is not in scope
        # the three faults: 200 without answers, no response, a non-200
        for expect_status, expect_error in ((200, "empty"), (500, "http"), (0, "ConnectionRefusedError")):
            v = turn.classify(s, "x", FLOW, r.client, spend_cap_usd=0.50, clock=r.clock)
            self.assertEqual((v.outcome, v.intent, v.answer.status, v.answer.error), ("model_failed", None, expect_status, expect_error))
            self.assertEqual(turn.jev_block(v.answer)["error"], expect_error)
            self.assertEqual(turn.jev_block(v.answer)["status"], expect_status)
        self.assertEqual(r.client.calls, 9)
        # product resolution: Jev's product beats the context beats focus_sku
        s.focus_sku = "DH-003"
        self.assertEqual(turn.resolve_product(s, {"product": "not_mentioned"}), ("DH-003", "focus_sku"))
        self.assertEqual(turn.resolve_product(s, {"product": "KBN-001"}), ("KBN-001", "jev"))
        s.contexts = {"ask_quantity": {"expires_after_turn": 3, "params": {"sku": "DH-001"}}}
        self.assertEqual(turn.resolve_product(s, {}), ("DH-001", "context:ask_quantity"))
        s.contexts, s.focus_sku = {}, None
        self.assertEqual(turn.resolve_product(s, {"product": "not_mentioned"}), (None, None))

    def test_cap_before_the_call(self):  # AC-2, the cap
        r = Rig(self, (200, reply("greet")))
        v = turn.classify(r.s, "สวัสดีค่ะ", FLOW, r.client, spend_cap_usd=0, clock=r.clock)
        self.assertEqual((v.outcome, v.answer, v.intent), ("cap_reached", None, None))
        self.assertEqual((r.client.calls, r.conn.log["opened"]), (0, 0))       # no call went out
        self.assertEqual(sorted(v.request), ["model", "questions", "state"])   # the request was still built
        # the cap is the client's own spend: at 0.50 the same call goes through; at (spent) it does not
        v = turn.classify(r.s, "สวัสดีค่ะ", FLOW, r.client, spend_cap_usd=0.50, clock=r.clock)
        self.assertEqual((v.outcome, v.intent, r.client.calls), ("matched", "greet", 1))
        self.assertAlmostEqual(r.client.spent_usd, 0.000164)
        v = turn.classify(r.s, "สวัสดีค่ะ", FLOW, r.client, spend_cap_usd=0.000164, clock=r.clock)
        self.assertEqual((v.outcome, r.client.calls), ("cap_reached", 1))
        # a cap entry in the log has a jev block that says so, no call, no cost
        e = turn.log_entry(r.s, FLOW, turn_no=0, turn_id="t1", at="2026-09-22T06:48:10.000Z", kind="typed",
                           text="สวัสดีค่ะ", outcome="cap_reached", verdict=v, response_id="system.cap")
        self.assertEqual(e["jev"], {"status": 0, "error": "cap", "ms": 0, "cost_usd": 0.0})
        self.assertEqual((e["outcome"], e["applied"], e["turn_no"], e["intents_in_scope"]), ("cap_reached", [], 0, 23))
        self.assertEqual(sorted(e), sorted(["turn_no", "turn_id", "at", "input", "contexts_before", "intents_in_scope",
                                            "jev", "outcome", "applied", "response_id", "contexts_after"]))


if __name__ == "__main__":
    unittest.main()
