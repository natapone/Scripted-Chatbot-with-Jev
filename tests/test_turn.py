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


def labels(buttons):
    return [b["label"] for b in buttons]


class TextTests(unittest.TestCase):
    def test_catalogue_text_and_buttons_as_written(self):  # Scope boundary: placeholders and notes stripped
        self.assertEqual(turn.strip_text("{spoken_name} ถุงละ {price} บาทค่ะ ({size}) {if no product: ตัวไหนคะ? — then the list}"), "ถุงละ บาทค่ะ")
        self.assertEqual(turn.strip_text("ได้เลยค่ะ {echo} — then the prompt for the first empty slot"), "ได้เลยค่ะ")
        self.assertEqual(turn.strip_text("{a {nested} one} x"), "x")
        self.assertEqual(turn.strip_text("(a note only)"), "")
        self.assertEqual(turn.strip_text(FLOW.fallback["ladder"][1]), "ขอโทษด้วยน้า แอดยังไม่เข้าใจค่ะ ลองเลือกจากด้านล่างดูไหมคะ")
        self.assertEqual(turn.strip_text(FLOW.fallback["ladder"][0]), FLOW.fallback["ladder"][0])
        # fill: the product row's values go in after the strip, so a name's own parentheses survive
        p = FLOW.products["DH-001"]
        self.assertEqual(turn.fill(turn.flow_intent(FLOW, "ask_price")["response"], p), f'{p["spoken_name"]} ถุงละ {p["price"]} บาทค่ะ')
        self.assertIn("(เกอิชา ดอยหอม)", turn.fill("{name}!", p))
        self.assertEqual(turn.fill("{name} {unknown}", {"name": "x"}), "x")
        # clause: one `{marker: …}` of a response
        rec = turn.flow_intent(FLOW, "ask_recommendation")["response"]
        self.assertEqual(turn.clause(rec, "if brew unknown"), "เยี่ยมเลยค่ะ — งั้นรบกวนถามต่ออีกนิดน้า จะได้ recommend ตรงค่ะ ปกติชงแบบไหนคะ?")
        self.assertEqual(turn.clause(rec, "else if roast unknown"), "ชอบคั่วระดับไหนคะ?")
        self.assertEqual(turn.clause(rec, "nope"), "")
        # buttons: label→intent; a bare label fires the intent itself; a note is no button
        self.assertEqual(turn.buttons_of({"id": "x", "buttons": ["เอาตัวนี้→affirm", "ดอยหอม", "(of the slot)", "(a) or (b)"]}),
                         [{"label": "เอาตัวนี้", "intent": "affirm", "params": {}}, {"label": "ดอยหอม", "intent": "x", "params": {}}])
        self.assertEqual([b["intent"] for b in turn.help_buttons(FLOW)], ["ask_recommendation", "browse_catalog", "ask_promotion", "faq.shipping_fee"])
        # every intent yields a non-empty text and no `{`-placeholder unless the whole response was one
        for it in FLOW.intents:
            text = turn.strip_text(it["response"]) or it["response"]
            self.assertTrue(text, it["id"])
            if "{" in text:
                self.assertTrue(it["response"].startswith(("{", "(")), it["id"])
        with self.assertRaises(KeyError):
            turn.flow_intent(FLOW, "nope")


class RunTurnTests(unittest.TestCase):
    def test_matched_product_info_commits_whole(self):  # AC-3 and the traced turn 1
        r = Rig(self, (200, reply("product_info", 0.95, product="DH-001", rid="gen-p")),
                (200, reply("greet", 0.9)), (200, reply("help", 0.9)), (200, reply("thanks_bye", 0.9)))
        sid = r.s.session_id
        self.assertEqual(r.s.turn_no, 0)
        self.assertEqual(r.s.transcript[0]["id"], "m1")
        self.assertEqual(labels(r.s.live_buttons), ["ช่วยแนะนำหน่อย", "ดูเมล็ดทั้งหมด", "มีโปรอะไรบ้าง"])
        self.assertTrue(all(b["message_id"] == "m1" for b in r.s.live_buttons))
        res = r.typed("เกอิชาเป็นยังไงคะ", "t1")
        s = r.state()
        self.assertEqual((res["outcome"], res["turn_no"], res["session_id"], res["ended"], res["model_status"]),
                         ("matched", 1, sid, False, "live"))
        self.assertEqual(res["you"], {"who": "you", "text": "เกอิชาเป็นยังไงคะ", "kind": "typed", "masked": False})
        self.assertEqual(len(res["bot"]), 1)
        bot = res["bot"][0]
        self.assertEqual((bot["id"], bot["variant"], bot["response_id"]), ("m3", "plain", "product_info"))
        p = FLOW.products["DH-001"]
        self.assertEqual(bot["text"], f'{p["name"]} — {p["description"]} ราคา {p["price"]} บาทค่ะ รับตัวนี้เลยไหมคะ?')
        self.assertNotIn("{", bot["text"])
        self.assertEqual(bot["buttons"], [{"label": "เอาตัวนี้", "intent": "affirm", "params": {}},
                                          {"label": "ดูตัวอื่น", "intent": "browse_catalog", "params": {}}])
        # the state: focus_sku, the context at turn_no + 2, last_bot_message, live_buttons, turn_no
        self.assertEqual(s.focus_sku, "DH-001")
        self.assertEqual(s.contexts, {"offer_product": {"expires_after_turn": 3, "params": {"sku": "DH-001"}}})
        self.assertEqual(s.last_bot_message, {"id": "m3", "text": bot["text"], "text_for_jev": bot["text"]})
        self.assertEqual(s.live_buttons, [dict(b, message_id="m3") for b in bot["buttons"]])
        self.assertEqual((s.turn_no, s.last_turn_id, s.miss_count), (1, "t1", 0))
        self.assertEqual(s.order, session.empty_order())                     # nothing of the order form
        # the log entry: the contract's shape, Jev's block, the product from Jev
        e = res["log_entry"]
        self.assertIs(e, s.log[-1]) if e is s.log[-1] else self.assertEqual(e, s.log[-1])
        self.assertEqual(list(e), ["turn_no", "turn_id", "at", "input", "contexts_before", "intents_in_scope",
                                   "jev", "outcome", "applied", "response_id", "contexts_after"])
        self.assertEqual((e["turn_no"], e["turn_id"], e["input"], e["contexts_before"], e["intents_in_scope"]),
                         (1, "t1", {"kind": "typed", "text": "เกอิชาเป็นยังไงคะ"}, [], 23))
        self.assertEqual((e["jev"]["intent"], e["jev"]["confidence"], e["jev"]["ms"], e["jev"]["cost_usd"], e["jev"]["request_id"]),
                         ("product_info", 0.95, 338, 0.000164, "gen-p"))
        self.assertLess(e["at"], e["jev"]["t_sent"])                          # `at` first, then the call
        self.assertLess(e["jev"]["t_sent"], e["jev"]["t_received"])
        self.assertTrue(e["at"].endswith("Z") and len(e["at"]) == 24)
        self.assertEqual((e["outcome"], e["applied"], e["response_id"], e["contexts_after"]),
                         ("matched", [{"set": "focus_sku", "to": "DH-001", "product_from": "jev"}], "product_info", ["offer_product"]))
        # raw: the request and the response bodies, in memory only, keyed by turn_id
        self.assertEqual(res["raw"]["request"]["state"]["customer_said"], "เกอิชาเป็นยังไงคะ")
        self.assertEqual(res["raw"]["response"]["id"], "gen-p")
        self.assertEqual(s.raw, {"t1": res["raw"]})
        # the snapshot exists and equals the state minus the memory-only fields
        snap = r.snapshot()
        self.assertEqual(snap, s.to_snapshot())
        self.assertNotIn("raw", snap)
        self.assertEqual(snap["focus_sku"], "DH-001")
        self.assertEqual(snap["log"], s.log)
        # two more turns and the context is gone; the next request's options shrink back to 23
        self.assertEqual(len(r.typed("สวัสดี", "t2")["raw"]["request"]["questions"]["intent"]["criteria"]), 25)
        self.assertEqual(r.state().contexts, {"offer_product": {"expires_after_turn": 3, "params": {"sku": "DH-001"}}})
        self.assertEqual(len(r.typed("ช่วยด้วย", "t3")["raw"]["request"]["questions"]["intent"]["criteria"]), 25)
        self.assertEqual((r.state().turn_no, r.state().contexts), (3, {}))
        self.assertEqual(len(r.typed("ขอบคุณ", "t4")["raw"]["request"]["questions"]["intent"]["criteria"]), 23)
        self.assertEqual(r.state().focus_sku, "DH-001")                     # focus stays; the context went
        self.assertEqual(r.client.calls, 4)
        self.assertEqual(r.snapshot()["turn_no"], 4)

    def test_fallback_ladder_and_a_failed_call_change_only_miss_count(self):  # AC-4, AC-2's second half
        r = Rig(self, (200, reply("none", 0.9, rid="gen-a")), (200, reply("none", 0.9, rid="gen-b")),
                (200, reply("ask_price", 0.3, rid="gen-c")),
                (200, {"id": "gen-d", "usage": {"cost": 0.0001}}), (500, {"error": "x"}),
                ConnectionRefusedError("no"), ConnectionRefusedError("no"),
                (200, reply("help", 0.9, rid="gen-e")))
        before = frozen(r.s)
        greeting_buttons = labels(r.s.live_buttons)
        res = r.typed("มีหน้าร้านไหมคะ", "t1")
        s = r.state()
        self.assertEqual((res["outcome"], res["turn_no"], res["model_status"]), ("fallback", 0, "live"))
        self.assertEqual(res["bot"][0]["text"], FLOW.fallback["ladder"][0])
        self.assertEqual((res["bot"][0]["variant"], res["bot"][0]["response_id"], res["bot"][0]["id"]), ("fallback", "fallback.1", "m3"))
        self.assertEqual(labels(res["bot"][0]["buttons"]), greeting_buttons)   # the same buttons
        self.assertEqual((s.miss_count, s.turn_no, s.last_turn_id), (1, 0, "t1"))
        self.assertEqual(frozen(s), before)                                     # byte-identical otherwise
        self.assertEqual(s.last_bot_message["id"], "m1")
        e = res["log_entry"]
        self.assertEqual((e["turn_no"], e["outcome"], e["applied"], e["jev"]["intent"], e["jev"]["request_id"], e["response_id"]),
                         (0, "fallback", [], "none", "gen-a", "fallback.1"))
        self.assertNotIn("error", e["jev"])
        self.assertEqual(r.snapshot()["miss_count"], 1)
        res = r.typed("รับสมัครพนักงานไหมครับ", "t2")
        self.assertEqual(res["bot"][0]["text"], "ขอโทษด้วยน้า แอดยังไม่เข้าใจค่ะ ลองเลือกจากด้านล่างดูไหมคะ")
        self.assertEqual(labels(res["bot"][0]["buttons"]), labels(turn.help_buttons(FLOW)))       # the help buttons
        self.assertEqual(res["bot"][0]["response_id"], "fallback.2")
        self.assertEqual((r.state().miss_count, r.state().turn_no), (2, 0))
        res = r.typed("ราคา?", "t3")                                             # below 0.45: the ladder stays on 2
        self.assertEqual((res["outcome"], res["bot"][0]["response_id"], r.state().miss_count), ("fallback", "fallback.2", 3))
        self.assertEqual(res["log_entry"]["jev"]["intent"], "ask_price")
        # the three faults: the could-not-reach line, the same buttons, model_status, the status kept
        for tid, expect_status, expect_error, expect_ms in (("t4", 200, "empty", 338), ("t5", 500, "http", 338), ("t6", 0, "ConnectionRefusedError", 338)):
            res = r.typed("x", tid)
            self.assertEqual((res["outcome"], res["model_status"], res["turn_no"]), ("model_failed", "unreachable", 0), tid)
            self.assertEqual((res["bot"][0]["text"], res["bot"][0]["variant"], res["bot"][0]["response_id"]), (turn.UNREACHABLE, "system", "system.unreachable"))
            self.assertEqual(labels(res["bot"][0]["buttons"]), greeting_buttons)
            e = res["log_entry"]
            self.assertEqual((e["outcome"], e["jev"]["status"], e["jev"]["error"], e["applied"], e["jev"]["intent"]),
                             ("model_failed", expect_status, expect_error, [], None), tid)
        self.assertEqual((r.state().miss_count, r.state().turn_no), (6, 0))
        self.assertEqual(frozen(r.state()), before)
        self.assertEqual(len(r.state().log), 6)
        # a match resets miss_count and advances
        res = r.typed("ช่วยหน่อย", "t7")
        self.assertEqual((res["outcome"], r.state().miss_count, r.state().turn_no), ("matched", 0, 1))
        self.assertEqual(res["log_entry"]["turn_no"], 1)
        # the cap: no call, the same could-not-reach line, model_status cap
        r.cap = 0
        res = r.typed("y", "t8")
        self.assertEqual((res["outcome"], res["model_status"], res["bot"][0]["response_id"]), ("cap_reached", "cap", "system.cap"))
        self.assertEqual(res["log_entry"]["jev"], {"status": 0, "error": "cap", "ms": 0, "cost_usd": 0.0})
        self.assertEqual((res["raw"]["response"], r.client.calls, r.state().miss_count), (None, 7, 1))

    def test_repeat_turn_id_stale_click_and_a_current_click(self):  # AC-5
        r = Rig(self, (200, reply("ask_price", 0.93, product="DH-001")), (200, reply("greet", 0.9)))
        res1 = r.typed("เกอิชาถุงละเท่าไหร่คะ", "t1")
        self.assertEqual((res1["outcome"], res1["bot"][0]["text"]), ("matched", "เกอิชา ถุงละ 980 บาทค่ะ"))
        self.assertEqual(labels(res1["bot"][0]["buttons"]), ["เอาตัวนี้", "ดูตัวอื่น"])
        # the same turn_id again: the stored result, Jev called once, nothing re-processed
        res2 = r.typed("เกอิชาถุงละเท่าไหร่คะ", "t1")
        self.assertEqual(dict(res2, repeat=False), dict(res1, repeat=False))
        self.assertTrue(res2["repeat"])
        self.assertNotIn("repeat", res1)
        self.assertEqual((r.client.calls, r.state().turn_no, len(r.state().log)), (1, 1, 1))
        # a click naming an older message is ignored, nothing changes, no call
        snap = r.snapshot()
        res = r.click({"label": "ช่วยแนะนำหน่อย", "intent": "ask_recommendation", "params": {}, "message_id": "m1"}, "t2")
        self.assertEqual((res["outcome"], res["turn_no"], res["you"], res["bot"], res["log_entry"], res["raw"]),
                         ("ignored", 1, None, [], None, None))
        self.assertEqual(r.snapshot(), snap)
        self.assertEqual(r.state().last_turn_id, "t1")
        # a click on a button the current message never showed is ignored too
        res = r.click({"label": "ยืนยัน", "intent": "affirm", "params": {}, "message_id": "m3"}, "t2")
        self.assertEqual(res["outcome"], "ignored")
        # a current click: turn_no +1, kind clicked, no jev block, no call, echoed as the customer's message
        res = r.click({"label": "ดูตัวอื่น", "intent": "browse_catalog", "params": {}, "message_id": "m3"}, "t3")
        self.assertEqual((res["outcome"], res["turn_no"], r.client.calls), ("matched", 2, 1))
        self.assertEqual(res["you"], {"who": "you", "text": "ดูตัวอื่น", "kind": "clicked", "masked": False})
        self.assertEqual(res["raw"], None)
        e = res["log_entry"]
        self.assertNotIn("jev", e)
        self.assertEqual((e["input"], e["turn_no"], e["turn_id"], e["outcome"], e["response_id"], e["contexts_before"]),
                         ({"kind": "clicked", "text": "ดูตัวอื่น"}, 2, "t3", "matched", "browse_catalog", ["offer_product"]))
        self.assertTrue(e["at"].endswith("Z"))
        self.assertEqual(res["bot"][0]["text"], "ตอนนี้ Beanly มี 10 ตัวจาก 3 โรงคั่วค่ะ — ดอยหอม คั่วบ้านนา และเมล็ดเมือง อยากดูของโรงคั่วไหนคะ? หรือพิมพ์ชื่อตัวที่สนใจมาได้เลยน้า")
        self.assertEqual(res["bot"][0]["buttons"], [{"label": "ดอยหอม", "intent": "browse_catalog", "params": {}},
                                                    {"label": "คั่วบ้านนา", "intent": "browse_catalog", "params": {}},
                                                    {"label": "เมล็ดเมือง", "intent": "browse_catalog", "params": {}}])
        self.assertEqual(r.state().transcript[-2]["who"], "you")
        self.assertEqual(r.snapshot()["turn_no"], 2)
        # a click with params carries them as the entities: the greeting's first button asks how they brew
        r2 = Rig(self)
        res = r2.click({"label": "ช่วยแนะนำหน่อย", "intent": "ask_recommendation", "params": {}, "message_id": "m1"}, "c1")
        self.assertEqual(res["bot"][0]["text"], "เยี่ยมเลยค่ะ — งั้นรบกวนถามต่ออีกนิดน้า จะได้ recommend ตรงค่ะ ปกติชงแบบไหนคะ?")
        self.assertEqual([b["params"] for b in res["bot"][0]["buttons"]], [{"brew": "espresso_milk"}, {"brew": "filter"}, {"brew": "cold_brew"}])
        self.assertEqual(r2.state().pending_prompt, {"slot": "brew", "context": "ask_brew", "params": {}, "message_id": "m3"})
        self.assertEqual(r2.state().contexts, {"ask_brew": {"expires_after_turn": 3, "params": {}}})
        res = r2.click({"label": "ดริป pour-over เฟรนช์เพรส โมก้าพอต หรือกาแฟดำแบบ filter", "intent": "inform", "params": {"brew": "filter"}, "message_id": "m3"}, "c2")
        self.assertEqual((res["outcome"], res["log_entry"]["applied"]), ("matched", [{"set": "brew", "to": "filter"}]))
        self.assertEqual(r2.state().order["recommend"], {"brew": None, "roast": None})   # written by Story 1.4, not here
        # bad requests
        for kw in ({"text": ""}, {"text": "x", "button": {}}, {}):
            with self.assertRaises(turn.TurnError) as cm:
                turn.run_turn(r.store, FLOW, r.client, r.s.session_id, "t9", **kw)
            self.assertEqual(cm.exception.status, 400)
        with self.assertRaises(turn.TurnError) as cm:
            r.typed("x", "t9", sid="nope")
        self.assertEqual(cm.exception.status, 404)
        with self.assertRaises(turn.TurnError):
            turn.run_turn(r.store, FLOW, r.client, r.s.session_id, "", text="x")

    def test_resume_after_a_prepared_answer_and_start_over(self):  # traced turn 3; contract § Lifecycle
        r = Rig(self, (200, reply("ask_price", 0.93, product="DH-001")), (200, reply("faq.shipping_fee", 0.97)),
                (200, reply("faq.grinding", 0.97)), (200, reply("start_over", 0.95)))
        r.typed("เกอิชาถุงละเท่าไหร่คะ", "t1")
        # turn 2 is Story 1.4's (affirm takes the product and asks the quantity); its outcome is staged here
        s = r.state()
        say(s, "รับกี่ถุงดีคะ?", [turn.button("1 ถุง", "inform", {"quantity": "1"}), turn.button("2 ถุง", "inform", {"quantity": "2"})], response_id="inform")
        s.pending_prompt = {"slot": "quantity", "context": "ask_quantity", "params": {"sku": "DH-001"}, "message_id": s.last_bot_message["id"]}
        s.contexts = {"ask_quantity": {"expires_after_turn": 4, "params": {"sku": "DH-001"}}}
        s.turn_no, s.last_turn_id = 2, "t2"
        r.store.commit(s)
        asked_id = s.last_bot_message["id"]
        # turn 3: a question interrupts; the FAQ answers (its text is Story 1.4's), then the question is asked again
        res = r.typed("ค่าส่งเท่าไหร่คะ", "t3")
        s = r.state()
        self.assertEqual((res["outcome"], res["turn_no"], len(res["bot"])), ("matched", 3, 2))
        self.assertEqual((res["bot"][0]["response_id"], res["bot"][0]["text"]), ("faq.shipping_fee", "{FAQ-01.answer}"))
        self.assertEqual((res["bot"][1]["response_id"], res["bot"][1]["text"]), ("resume:quantity", "รับกี่ถุงดีคะ?"))
        self.assertEqual(labels(res["bot"][1]["buttons"]), ["1 ถุง", "2 ถุง"])
        self.assertNotEqual(res["bot"][1]["id"], asked_id)
        self.assertEqual(s.contexts, {"ask_quantity": {"expires_after_turn": 5, "params": {"sku": "DH-001"}}})
        self.assertEqual(s.pending_prompt["message_id"], res["bot"][1]["id"])
        self.assertEqual(s.last_bot_message["text"], "รับกี่ถุงดีคะ?")             # names no product
        self.assertEqual(s.live_buttons[0]["message_id"], res["bot"][1]["id"])
        self.assertEqual(res["log_entry"]["contexts_after"], ["ask_quantity"])
        self.assertEqual(res["log_entry"]["applied"], [])
        self.assertEqual(res["raw"]["request"]["state"]["awaiting"], "quantity")
        # turn 4: another; the context is re-armed to 6 (the traced table), and grinding keeps its SOP line
        res = r.typed("บดให้ได้ไหมคะ", "t4")
        self.assertEqual(res["bot"][0]["text"], "กาแฟดีต้องคู่ grind ที่ตรงเสมอค่ะ")
        self.assertEqual(r.state().contexts["ask_quantity"]["expires_after_turn"], 6)
        self.assertEqual(r.state().turn_no, 4)
        # start_over: the old snapshot is deleted, a new id issued, the greeting returned
        old = r.s.session_id
        old_path = r.var / "sessions" / f"{old}.json"
        self.assertTrue(old_path.exists())
        res = r.typed("เริ่มใหม่", "t5")
        self.assertTrue(res["ended"])
        self.assertNotEqual(res["session_id"], old)
        self.assertEqual((res["turn_no"], res["outcome"], res["bot"][0]["response_id"], res["bot"][0]["id"]), (0, "matched", "greet", "m1"))
        self.assertEqual(labels(res["bot"][0]["buttons"]), ["ช่วยแนะนำหน่อย", "ดูเมล็ดทั้งหมด", "มีโปรอะไรบ้าง"])
        self.assertEqual(res["log_entry"]["response_id"], "start_over")
        self.assertFalse(old_path.exists())
        self.assertIsNone(r.store.get(old))
        new = r.store.get(res["session_id"])
        self.assertEqual((new.turn_no, new.contexts, new.focus_sku, new.log), (0, {}, None, []))
        self.assertTrue((r.var / "sessions" / f"{new.session_id}.json").exists())
        # the click path ends it the same way
        res = r.click({"label": "เริ่มใหม่", "intent": "start_over", "params": {}, "message_id": "m1"}, "c1", sid=new.session_id)
        self.assertEqual(res["outcome"], "ignored")                   # not one of the greeting's buttons
        say(new, "ขอบคุณค่ะ", [turn.button("เริ่มใหม่", "start_over")], response_id="thanks_bye")
        r.store.commit(new)
        res = r.click({"label": "เริ่มใหม่", "intent": "start_over", "params": {}, "message_id": "m2"}, "c2", sid=new.session_id)
        self.assertTrue(res["ended"])
        self.assertNotEqual(res["session_id"], new.session_id)
        self.assertIsNone(r.store.get(new.session_id))
        self.assertEqual(res["you"]["kind"], "clicked")

    def test_delivery_details_are_masked_everywhere_but_the_bubble(self):  # AC-7
        r = Rig(self, (200, reply("give_delivery_details", 0.98)), (200, reply("faq.shipping_fee", 0.9)))
        s = r.s
        s.contexts = {"ask_delivery": {"expires_after_turn": 2, "params": {}}}
        r.store.commit(s)
        res = r.typed(ADDRESS, "t1")
        s = r.state()
        self.assertEqual((res["outcome"], res["you"]["masked"], res["you"]["text"]), ("matched", True, ADDRESS))
        self.assertEqual(res["log_entry"]["input"], {"kind": "typed", "text": turn.MASK_FOR_LOG})
        self.assertNotIn(ADDRESS, json.dumps(s.log, ensure_ascii=False))
        self.assertNotIn("081-000-0000", json.dumps(s.log, ensure_ascii=False))
        self.assertEqual(res["raw"]["request"]["state"]["customer_said"], ADDRESS)   # once, on its own turn
        # the next turn's history carries the placeholder, never the text
        res = r.typed("ค่าส่งเท่าไหร่คะ", "t2")
        hist = res["raw"]["request"]["state"]["history"]
        self.assertIn({"who": "customer", "text": turn.MASK_FOR_JEV}, hist)
        self.assertNotIn(ADDRESS, json.dumps(res["raw"]["request"], ensure_ascii=False))
        self.assertNotIn(ADDRESS, json.dumps(r.state().log, ensure_ascii=False))
        # text_for_jev masks a read-back that shows the address (Story 1.4 writes both; the mask is here)
        s = r.state()
        s.order["delivery_text"] = ADDRESS
        say(s, f"ส่งไปที่ {ADDRESS} ยืนยันไหมคะ?", [], variant="read-back", response_id="read-back")
        self.assertEqual(s.last_bot_message["text_for_jev"], f"ส่งไปที่ {turn.MASK_FOR_JEV} ยืนยันไหมคะ?")
        self.assertIn(ADDRESS, s.last_bot_message["text"])
        self.assertNotIn(ADDRESS, json.dumps(turn.build_request(s, "ยืนยันค่ะ", FLOW), ensure_ascii=False))
        # the key is nowhere in a session, a snapshot, a log entry or a response
        blob = json.dumps([s.to_snapshot(), res, s.raw], ensure_ascii=False, default=str)
        self.assertNotIn(FAKE_KEY, blob)
        self.assertNotIn(FAKE_KEY, r.snapshot().__repr__())


say = turn.say


if __name__ == "__main__":
    unittest.main()
