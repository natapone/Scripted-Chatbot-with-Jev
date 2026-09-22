"""Story 1.3 — the turn loop; Story 1.4 — the order form and the responses (`LeadTests`,
`OrderTests`). Hermetic: Jev is a scripted connection behind the real `Client` (no socket), the
clock is fixed, snapshots go to a temp dir."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import flow, jev, order, session, turn
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
        self.assertEqual((res["outcome"], res["log_entry"]["applied"]), ("matched", [{"set": "recommend.brew", "to": "filter"}]))
        self.assertEqual(r2.state().order["recommend"], {"brew": "filter", "roast": None})   # Story 1.4 writes it; the roast is asked next
        self.assertEqual(res["bot"][0]["text"], "ชอบคั่วระดับไหนคะ?")
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
        self.assertEqual((res["bot"][0]["response_id"], res["bot"][0]["text"]), ("faq.shipping_fee", "ค่าส่ง 100 บาททั่วประเทศ ส่งฟรีเมื่อสั่งครบ 5 ถุงขึ้นไป จัดส่ง 2-3 วันทำการ"))   # Story 1.4: the CSV answer
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
        self.assertTrue(res["bot"][0]["text"].endswith(" กาแฟดีต้องคู่ grind ที่ตรงเสมอค่ะ"))   # Story 1.4: FAQ-06's answer + the SOP line
        self.assertTrue(res["bot"][0]["text"].startswith("มีค่ะ"))
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



class LeadTests(unittest.TestCase):
    """Story 1.4 task 02 — `lead()` asks for the first empty slot in the SOP's order."""

    def test_lead_from_an_empty_form_to_the_read_back(self):  # conversation-flow § The order form
        r = Rig(self)
        s = r.s
        # an empty form: the lead recommends — brew first, then roast, then the pair from the table
        turn.lead(s, FLOW, 1)
        self.assertEqual(s.transcript[-1]["text"], "เยี่ยมเลยค่ะ — งั้นรบกวนถามต่ออีกนิดน้า จะได้ recommend ตรงค่ะ ปกติชงแบบไหนคะ?")
        self.assertEqual([b["params"] for b in s.transcript[-1]["buttons"]], [{"brew": "espresso_milk"}, {"brew": "filter"}, {"brew": "cold_brew"}])
        self.assertEqual((s.pending_prompt["slot"], s.pending_prompt["context"], list(s.contexts)), ("brew", "ask_brew", ["ask_brew"]))
        s.order["recommend"]["brew"] = "filter"
        turn.lead(s, FLOW, 2)
        self.assertEqual(s.transcript[-1]["text"], "ชอบคั่วระดับไหนคะ?")
        self.assertEqual([b["params"]["roast"] for b in s.transcript[-1]["buttons"]], ["light", "medium", "dark", "decaf"])
        self.assertEqual(s.pending_prompt["slot"], "roast")
        s.order["recommend"]["roast"] = "light"
        turn.lead(s, FLOW, 3)
        pair = s.transcript[-1]
        self.assertEqual(pair["text"], "story bean ก่อนนะคะ — ตัวแรก เกอิชา: คั่วอ่อน · ดอกไม้ มะลิ พีช · บอดี้เบา อีกตัว วอชด์ อาราบิก้า: คั่วอ่อน · ส้ม มะนาว ชาเขียว · สะอาด สดชื่น สนใจตัวไหนคะ?")
        self.assertEqual(pair["buttons"], [{"label": "เกอิชา", "intent": "select_option", "params": {"product": "DH-001"}},
                                           {"label": "วอชด์ อาราบิก้า", "intent": "select_option", "params": {"product": "MM-001"}},
                                           {"label": "ดูตัวอื่น", "intent": "browse_catalog", "params": {}}])
        self.assertEqual((s.options_shown, s.contexts["options_shown"]["params"], s.pending_prompt), (["DH-001", "MM-001"], {"skus": ["DH-001", "MM-001"]}, None))
        self.assertEqual(s.order["recommend"], {"brew": None, "roast": None})           # cleared once given
        # with `recommend=False` an empty form waits (ask_promotion, view_order)
        n = len(s.transcript)
        turn.lead(s, FLOW, 4, recommend=False)
        self.assertEqual(len(s.transcript), n)
        # a line with no quantity: the quantity question with its four buttons and the context's sku
        s.order["lines"] = [{"sku": "DH-001", "qty": None, "added_by": "customer"}]
        turn.lead(s, FLOW, 4)
        q = s.transcript[-1]
        self.assertEqual((q["text"], q["response_id"], q["variant"]), ("รับกี่ถุงดีคะ? สั่งครบ 5 ถุงส่งฟรีน้า", "ask_quantity", "plain"))
        self.assertEqual(q["buttons"], [{"label": f"{n} ถุง", "intent": "inform", "params": {"quantity": str(n)}} for n in (1, 2, 3, 5)])
        self.assertEqual(s.contexts["ask_quantity"], {"expires_after_turn": 6, "params": {"sku": "DH-001"}})
        self.assertEqual(s.pending_prompt, {"slot": "quantity", "context": "ask_quantity", "params": {"sku": "DH-001"}, "message_id": q["id"]})
        self.assertEqual(s.last_bot_message["id"], q["id"])
        self.assertEqual(s.live_buttons[0]["message_id"], q["id"])
        # quantity filled: the one promotion that fits, offered once, with exactly its effect
        s.order["lines"][0]["qty"] = 1
        turn.lead(s, FLOW, 5)
        pr = s.transcript[-1]
        self.assertEqual(pr["text"], "ซื้อเกอิชาคู่กับเนเชอรัล แอนแอโรบิก รับส่วนลด 80 บาท สำหรับคอกาแฟคั่วอ่อน สนใจไหมคะ? ไม่ urgent น้า ลองดูก่อนได้")
        self.assertEqual(labels(pr["buttons"]), ["เพิ่มเนเชอรัล แอนแอโรบิก", "ไม่เป็นไร เอาเท่าเดิม"])
        self.assertEqual([b["intent"] for b in pr["buttons"]], ["affirm", "deny"])
        self.assertEqual(s.contexts["offer_promo"]["params"], {"promo_id": "PROMO-02", "effect": {"add_line": "DH-003"}})
        self.assertEqual((s.promos_offered, s.pending_prompt["slot"], pr["response_id"]), (["PROMO-02"], "promotion", "promo.offer"))
        # offered once: the next lead moves on to payment, with the fee
        turn.lead(s, FLOW, 6)
        pay = s.transcript[-1]
        self.assertEqual(pay["text"], "ค่าส่ง 100 บาท ค่ะ ชำระแบบไหนสะดวกคะ? โอนผ่านบัญชีธนาคาร หรือเก็บเงินปลายทาง (มีค่าบริการเพิ่ม 30 บาท)")
        self.assertEqual(pay["buttons"], [{"label": "โอนผ่านธนาคาร", "intent": "inform", "params": {"payment": "transfer"}},
                                          {"label": "เก็บเงินปลายทาง", "intent": "inform", "params": {"payment": "cod"}}])
        self.assertEqual((s.pending_prompt["slot"], s.pending_prompt["context"]), ("payment", "ask_payment"))
        self.assertEqual(s.promos_offered, ["PROMO-02"])
        s.order["lines"][0]["qty"] = 5                                               # five bags: the fee reads ฟรี
        turn.lead(s, FLOW, 6)
        self.assertTrue(s.transcript[-1]["text"].startswith("ค่าส่ง ฟรี ค่ะ"))
        s.order["lines"][0]["qty"] = 1
        # payment set: the delivery question with the sample button
        s.order["payment"] = "cod"
        turn.lead(s, FLOW, 7)
        d = s.transcript[-1]
        self.assertEqual(d["text"], "รบกวนขอชื่อ ที่อยู่ และเบอร์โทรสำหรับจัดส่งค่ะ — เดโมนี้ไม่ส่งของจริง ใช้ข้อมูลสมมติได้เลยน้า")
        self.assertEqual(d["buttons"], [{"label": "ใช้ข้อมูลตัวอย่าง", "intent": "give_delivery_details", "params": {"sample": True}}])
        self.assertEqual((s.pending_prompt["slot"], list(s.contexts)[-1]), ("delivery", "ask_delivery"))
        # delivery set: the read-back as data, the hash in the context, the address masked for Jev
        s.order["delivery_text"] = ADDRESS
        turn.lead(s, FLOW, 8)
        rb = s.transcript[-1]
        self.assertEqual((rb["variant"], rb["response_id"], labels(rb["buttons"])), ("read-back", "confirm", ["ยืนยัน", "ขอแก้ไข"]))
        self.assertEqual([b["intent"] for b in rb["buttons"]], ["affirm", "deny"])
        self.assertEqual(rb["readback"]["rows"], [["เกอิชา × 1 ถุง", "980 บาท"], ["ค่าส่ง", "100 บาท"], ["ค่าบริการเก็บเงินปลายทาง", "30 บาท"], ["รวม", "1,110 บาท"]])
        self.assertEqual((rb["readback"]["total"], rb["readback"]["delivery_text"], rb["readback"]["lead"]), (1110, ADDRESS, "สรุปออเดอร์ค่ะ"))
        self.assertTrue(rb["text"].startswith("สรุปออเดอร์ค่ะ\nเกอิชา × 1 ถุง — 980 บาท"))
        self.assertIn(ADDRESS, rb["text"])
        self.assertIn("รบกวนคุณพี่ตรวจรายการอีกครั้ง แล้วยืนยันให้แอดน้า 🙏🏻", rb["text"])
        self.assertNotIn(ADDRESS, s.last_bot_message["text_for_jev"])
        self.assertIn(turn.MASK_FOR_JEV, s.last_bot_message["text_for_jev"])
        h = s.contexts["confirm_order"]["params"]["order_hash"]
        self.assertEqual(h, order.order_hash(s.order))
        self.assertEqual(s.pending_prompt, {"slot": "confirmation", "context": "confirm_order", "params": {"order_hash": h}, "message_id": rb["id"]})
        # a confirmed order is terminal: the lead asks nothing
        s.order["order_code"] = "BEAN-2609-0009"
        n = len(s.transcript)
        turn.lead(s, FLOW, 9)
        self.assertEqual(len(s.transcript), n)
        # the snapshot carries the read-back's data and round-trips
        r.store.commit(s)
        snap = r.snapshot()
        self.assertEqual(snap["transcript"][-1]["readback"]["total"], 1110)
        self.assertNotIn("readback", snap["transcript"][0])                            # only a read-back bubble has it

    def test_resume_after_a_faq_re_asks_with_the_grid(self):  # contract § Traced turn 3; walk § 3.2
        r = Rig(self, (200, reply("faq.shipping_fee", 0.97)), (200, reply("faq.payment_methods", 0.9)))
        s = r.s
        s.order["lines"] = [{"sku": "DH-001", "qty": 1, "added_by": "customer"}]
        s.order["payment"], s.order["delivery_text"] = "cod", ADDRESS
        s.promos_offered = ["PROMO-02"]                                                 # declined earlier
        turn.lead(s, FLOW, 1)                                                          # the read-back is pending
        s.turn_no, s.last_turn_id = 1, "t0"
        r.store.commit(s)
        rb_id = s.last_bot_message["id"]
        res = r.typed("ค่าส่งเท่าไหร่คะ", "t1")
        self.assertEqual((res["outcome"], len(res["bot"])), ("matched", 2))
        self.assertEqual((res["bot"][0]["response_id"], res["bot"][0]["buttons"]), ("faq.shipping_fee", []))
        again = res["bot"][1]
        self.assertEqual((again["response_id"], again["variant"], labels(again["buttons"])), ("resume:confirmation", "read-back", ["ยืนยัน", "ขอแก้ไข"]))
        self.assertEqual(again["readback"]["total"], 1110)
        self.assertNotEqual(again["id"], rb_id)
        s = r.state()
        self.assertEqual(s.contexts["confirm_order"]["expires_after_turn"], 4)         # re-armed: 2 + lifespan 2
        self.assertEqual(s.pending_prompt["message_id"], again["id"])
        self.assertEqual(s.order["lines"][0]["qty"], 1)                                 # a FAQ writes nothing
        self.assertEqual(res["log_entry"]["applied"], [])
        self.assertNotIn(ADDRESS, json.dumps(res["raw"]["request"], ensure_ascii=False))   # shop_said is masked
        self.assertEqual(res["raw"]["request"]["state"]["awaiting"], "confirmation")
        # a FAQ with nothing pending answers and waits
        s.pending_prompt = None
        r.store.commit(s)
        res = r.typed("จ่ายยังไงได้บ้าง", "t2")
        self.assertEqual(len(res["bot"]), 1)
        self.assertTrue(res["bot"][0]["text"].startswith("รับชำระ 2 แบบ"))



def blob(*things) -> str:
    return json.dumps(things, ensure_ascii=False, default=str)


class OrderTests(unittest.TestCase):
    """Story 1.4 task 03 — the order intents, driven through `run_turn` with stubbed verdicts."""

    def test_the_traced_conversation(self):  # AC-1: contract § Traced, turns 1–10; AC-6's NFR10 half
        r = Rig(self, (200, reply("ask_price", 0.93, product="DH-001")),
                (200, reply("affirm", 0.88)),
                (200, reply("faq.shipping_fee", 0.97)),
                (200, reply("faq.grinding", 0.96)),
                (200, reply("none", 0.91, quantity="1")),                 # a bare 1 ถุงค่ะ: by state
                (200, reply("affirm", 0.9)),
                (200, reply("faq.payment_methods", 0.7, payment="cod")),  # the question — the pending slot makes it inform
                (200, reply("give_delivery_details", 0.98)),
                (200, reply("change_order", 0.95, product="DH-001", quantity="2")),
                (200, reply("affirm", 0.97)),
                (200, reply("order_product", 0.9, product="KBN-001", quantity="2")))
        res = r.typed("เกอิชาถุงละเท่าไหร่คะ", "t1")
        s = r.state()
        self.assertEqual((s.focus_sku, s.contexts), ("DH-001", {"offer_product": {"expires_after_turn": 3, "params": {"sku": "DH-001"}}}))
        self.assertEqual(s.order["lines"], [])
        # 2: เอาค่ะ takes the product from the context; the quantity is asked
        res = r.typed("เอาค่ะ", "t2")
        s = r.state()
        self.assertEqual(s.order["lines"], [{"sku": "DH-001", "qty": None, "added_by": "customer"}])
        self.assertEqual(res["log_entry"]["applied"], [{"set": "lines[DH-001]", "to": None, "product_from": "context:offer_product"}])
        self.assertEqual(res["bot"][0]["text"], "รับกี่ถุงดีคะ? สั่งครบ 5 ถุงส่งฟรีน้า")
        self.assertEqual(labels(res["bot"][0]["buttons"]), ["1 ถุง", "2 ถุง", "3 ถุง", "5 ถุง"])
        self.assertEqual(s.contexts, {"ask_quantity": {"expires_after_turn": 4, "params": {"sku": "DH-001"}}})
        self.assertEqual((s.pending_prompt["slot"], s.pending_prompt["context"], s.pending_prompt["params"]), ("quantity", "ask_quantity", {"sku": "DH-001"}))
        # 3, 4: two questions interrupt; the quantity is asked again each time, the context re-armed
        res = r.typed("ค่าส่งเท่าไหร่คะ", "t3")
        self.assertEqual([b["response_id"] for b in res["bot"]], ["faq.shipping_fee", "resume:quantity"])
        self.assertEqual(res["bot"][1]["text"], "รับกี่ถุงดีคะ? สั่งครบ 5 ถุงส่งฟรีน้า")           # names no product
        self.assertEqual(labels(res["bot"][1]["buttons"]), ["1 ถุง", "2 ถุง", "3 ถุง", "5 ถุง"])
        self.assertEqual(r.state().contexts["ask_quantity"]["expires_after_turn"], 5)
        self.assertEqual(r.state().order["lines"][0]["qty"], None)
        res = r.typed("ที่บ้านไม่มีเครื่องบด บดให้ได้ไหมคะ", "t4")
        self.assertEqual(r.state().contexts["ask_quantity"]["expires_after_turn"], 6)
        self.assertEqual(res["raw"]["request"]["state"]["awaiting"], "quantity")
        # 5: 1 ถุงค่ะ — Jev said none; the pending slot makes it inform; the sku is the context's
        res = r.typed("1 ถุงค่ะ", "t5")
        s = r.state()
        self.assertEqual((res["outcome"], res["log_entry"]["jev"]["by_state"], res["log_entry"]["jev"]["intent"]), ("matched", True, "none"))
        self.assertEqual(res["log_entry"]["applied"], [{"set": "lines[DH-001].qty", "to": 1, "product_from": "context:ask_quantity"}])
        self.assertEqual(s.order["lines"], [{"sku": "DH-001", "qty": 1, "added_by": "customer"}])
        self.assertEqual((s.promos_offered, s.pending_prompt["slot"]), (["PROMO-02"], "promotion"))
        self.assertEqual(s.contexts, {"offer_promo": {"expires_after_turn": 7, "params": {"promo_id": "PROMO-02", "effect": {"add_line": "DH-003"}}}})
        self.assertEqual(res["bot"][0]["response_id"], "promo.offer")
        self.assertEqual(labels(res["bot"][0]["buttons"]), ["เพิ่มเนเชอรัล แอนแอโรบิก", "ไม่เป็นไร เอาเท่าเดิม"])
        # 6: สนใจค่ะ applies exactly the offered effect
        res = r.typed("สนใจค่ะ", "t6")
        s = r.state()
        self.assertEqual(s.order["lines"], [{"sku": "DH-001", "qty": 1, "added_by": "customer"}, {"sku": "DH-003", "qty": 1, "added_by": "PROMO-02"}])
        self.assertEqual(s.order["promo_applied"], "PROMO-02")
        self.assertEqual(res["log_entry"]["applied"], [{"set": "lines[DH-003]", "to": 1, "product_from": "PROMO-02"}, {"set": "promo_applied", "to": "PROMO-02"}])
        self.assertEqual([b["response_id"] for b in res["bot"]], ["promo.taken", "ask_payment"])
        self.assertEqual(res["bot"][0]["text"], "ได้เลยค่ะ ใส่ให้แล้วนะคะ")
        self.assertEqual(s.contexts, {"ask_payment": {"expires_after_turn": 8, "params": {}}})
        # 7: the question carries payment cod; the pending slot fills it
        res = r.typed("เก็บปลายทางได้ไหมคะ", "t7")
        s = r.state()
        self.assertEqual((res["log_entry"]["jev"]["by_state"], s.order["payment"]), (True, "cod"))
        self.assertEqual(res["log_entry"]["applied"], [{"set": "payment", "to": "cod"}])
        self.assertEqual(list(s.contexts), ["ask_delivery"])
        self.assertEqual(s.contexts["ask_delivery"]["expires_after_turn"], 9)
        self.assertEqual(res["bot"][0]["buttons"][0]["label"], "ใช้ข้อมูลตัวอย่าง")
        # 8: the address — kept exactly, logged as [delivery details], read back, masked for Jev
        res = r.typed(ADDRESS, "t8")
        s = r.state()
        self.assertEqual((res["you"]["masked"], s.order["delivery_text"]), (True, ADDRESS))
        self.assertEqual(res["log_entry"]["input"]["text"], "[delivery details]")
        self.assertEqual(res["log_entry"]["applied"], [{"set": "delivery_text", "to": "[kept as typed]"}])
        rb = res["bot"][0]
        self.assertEqual((rb["variant"], rb["response_id"]), ("read-back", "confirm"))
        self.assertEqual(rb["readback"]["rows"], [["เกอิชา × 1 ถุง", "980 บาท"], ["เนเชอรัล แอนแอโรบิก × 1 ถุง", "520 บาท"],
                                                   ["ส่วนลด ชุดชิมคั่วอ่อน", "−80 บาท"], ["ค่าส่ง", "100 บาท"],
                                                   ["ค่าบริการเก็บเงินปลายทาง", "30 บาท"], ["รวม", "1,550 บาท"]])
        self.assertEqual(rb["readback"]["delivery_text"], ADDRESS)
        hash_a = s.contexts["confirm_order"]["params"]["order_hash"]
        self.assertEqual(s.contexts["confirm_order"]["expires_after_turn"], 10)
        self.assertEqual(s.last_bot_message["text_for_jev"].count(turn.MASK_FOR_JEV), 1)
        self.assertNotIn(ADDRESS, s.last_bot_message["text_for_jev"])
        # 9: a change names the product and the quantity: the line updated, the promotion still fits, read back again
        res = r.typed("ขอเปลี่ยนเกอิชาเป็น 2 ถุงค่ะ", "t9")
        s = r.state()
        self.assertEqual(s.order["lines"], [{"sku": "DH-001", "qty": 2, "added_by": "customer"}, {"sku": "DH-003", "qty": 1, "added_by": "PROMO-02"}])
        self.assertEqual(s.order["promo_applied"], "PROMO-02")
        self.assertEqual(res["log_entry"]["applied"], [{"set": "lines[DH-001].qty", "to": 2, "product_from": "jev"}])
        self.assertEqual([b["response_id"] for b in res["bot"]], ["change_order", "confirm"])
        self.assertEqual(res["bot"][1]["readback"]["total"], 980 * 2 + 520 - 80 + 100 + 30)
        hash_b = s.contexts["confirm_order"]["params"]["order_hash"]
        self.assertNotEqual(hash_a, hash_b)
        self.assertEqual(s.contexts["confirm_order"]["expires_after_turn"], 11)
        self.assertNotIn(ADDRESS, json.dumps(res["raw"]["request"], ensure_ascii=False))
        self.assertIn(turn.MASK_FOR_JEV, res["raw"]["request"]["state"]["shop_said"])
        # 10: ยืนยันค่ะ confirms the order read out — hash B
        res = r.typed("ยืนยันค่ะ", "t10")
        s = r.state()
        self.assertRegex(s.order["order_code"], r"^BEAN-\d{4}-\d{4}$")
        self.assertEqual(s.order["order_code"], "BEAN-2609-0010")
        self.assertEqual(s.order["confirmed_at"], res["log_entry"]["at"])
        self.assertEqual(res["log_entry"]["applied"][0], {"set": "order_code", "to": "BEAN-2609-0010"})
        self.assertEqual(res["bot"][0]["text"], "ขอบคุณคุณพี่มากค่ะ ☕ รหัสออเดอร์ BEAN-2609-0010 เตรียมชำระ 2,530 บาทตอนรับของน้า")
        self.assertEqual(res["bot"][0]["buttons"], [{"label": "เริ่มใหม่", "intent": "start_over", "params": {}}])
        self.assertEqual((s.contexts, s.pending_prompt, labels(s.live_buttons)), ({}, None, ["เริ่มใหม่"]))
        # terminal: a later order intent writes nothing
        before = json.dumps(s.order, ensure_ascii=False)
        res = r.typed("เอาเฮาส์เบลนด์ 2 ถุงค่ะ", "t11")
        self.assertEqual((res["outcome"], res["log_entry"]["applied"], json.dumps(r.state().order, ensure_ascii=False)), ("matched", [], before))
        self.assertEqual(labels(res["bot"][0]["buttons"]), ["เริ่มใหม่"])
        self.assertIn("BEAN-2609-0010", res["bot"][0]["text"])
        # NFR10: the typed details are in delivery_text and nowhere else that leaves the session
        s = r.state()
        self.assertNotIn(ADDRESS, blob(s.log))
        self.assertNotIn("081-000-0000", blob(s.log))
        self.assertNotIn(ADDRESS, blob(turn.history(s)))
        self.assertNotIn(ADDRESS, blob(s.last_bot_message["text_for_jev"]))
        self.assertNotIn(ADDRESS, blob([e["request"] for tid, e in s.raw.items() if tid != "t8"]))
        self.assertEqual(s.raw["t8"]["request"]["state"]["customer_said"], ADDRESS)     # once, on its own turn
        self.assertNotIn(FAKE_KEY, blob(s.to_snapshot(), s.raw, res))
        self.assertEqual(r.snapshot()["order"]["order_code"], "BEAN-2609-0010")
        self.assertEqual(r.client.calls, 11)

    def test_one_sentence_fills_three_slots(self):  # AC-2: walk § 2
        r = Rig(self, (200, reply("order_product", 0.96, product="KBN-002", quantity="3", payment="cod")),
                (200, reply("deny", 0.9)), (200, reply("affirm", 0.92)))
        res = r.typed("เอาเอสเปรสโซ่คั่วเข้ม 3 ถุง เก็บปลายทางนะครับ", "t1")
        s = r.state()
        self.assertEqual(s.order["lines"], [{"sku": "KBN-002", "qty": 3, "added_by": "customer"}])
        self.assertEqual((s.order["payment"], s.focus_sku), ("cod", "KBN-002"))
        self.assertEqual(res["log_entry"]["applied"], [{"set": "lines[KBN-002].qty", "to": 3, "product_from": "jev"}, {"set": "payment", "to": "cod"}])
        self.assertEqual(res["bot"][0]["text"], "ได้เลยค่ะ เอสเปรสโซ่คั่วเข้ม 3 ถุง เก็บเงินปลายทาง นะคะ")
        self.assertEqual(res["bot"][1]["response_id"], "promo.offer")                   # PROMO-01: under five bags
        self.assertEqual(s.contexts["offer_promo"]["params"], {"promo_id": "PROMO-01", "effect": {"set_qty": 5, "sku": "KBN-002"}})
        self.assertEqual(labels(res["bot"][1]["buttons"]), ["เพิ่มเป็น 5 ถุง", "ไม่เป็นไร เอาเท่าเดิม"])
        # a deny skips to delivery — payment is already filled
        res = r.typed("ไม่ครับ", "t2")
        self.assertEqual([b["response_id"] for b in res["bot"]], ["promo.declined", "ask_delivery"])
        self.assertEqual(res["bot"][0]["text"], "ได้เลยค่ะ เอาเท่าเดิมนะคะ")
        s = r.state()
        self.assertEqual((s.order["promo_applied"], s.promos_offered, list(s.contexts)), (None, ["PROMO-01"], ["ask_delivery"]))
        # the sample button fills delivery with the fictional constant; the read-back totals 1,270
        res = r.click({"label": "ใช้ข้อมูลตัวอย่าง", "intent": "give_delivery_details", "params": {"sample": True}, "message_id": res["bot"][1]["id"]}, "c1")
        s = r.state()
        self.assertEqual((res["outcome"], res["you"]["kind"], res["you"]["masked"]), ("matched", "clicked", False))
        self.assertEqual(s.order["delivery_text"], order.SAMPLE_DETAILS)
        self.assertEqual(res["log_entry"]["applied"], [{"set": "delivery_text", "to": "[sample]"}])
        rb = res["bot"][0]
        self.assertEqual((rb["variant"], rb["readback"]["total"]), ("read-back", 1270))
        self.assertEqual(rb["readback"]["rows"], [["เอสเปรสโซ่คั่วเข้ม × 3 ถุง", "1,140 บาท"], ["ค่าส่ง", "100 บาท"],
                                                   ["ค่าบริการเก็บเงินปลายทาง", "30 บาท"], ["รวม", "1,270 บาท"]])
        self.assertIn(order.SAMPLE_DETAILS, rb["text"])
        res = r.typed("โอเคครับ เอาตามนี้เลย", "t3")
        self.assertEqual(r.state().order["order_code"], "BEAN-2609-0004")
        self.assertIn("เตรียมชำระ 1,270 บาทตอนรับของน้า", res["bot"][0]["text"])
        self.assertEqual(r.client.calls, 3)

    def test_a_question_mid_order_and_a_change_at_the_end(self):  # AC-3, AC-4: walk § 3.0–3.6
        r = Rig(self, (200, reply("ask_recommendation", 0.95)), (200, reply("inform", 0.9, brew="filter")),
                (200, reply("inform", 0.9, roast="light")), (200, reply("select_option", 0.8, product="DH-001")),
                (200, reply("affirm", 0.9)), (200, reply("faq.shipping_fee", 0.97)),
                (200, reply("inform", 0.85, quantity="1")), (200, reply("view_order", 0.9)),
                (200, reply("change_order", 0.94, quantity="3")), (200, reply("deny", 0.9)), (200, reply("affirm", 0.97)))
        # 3.0: the lead in the SOP's order — brew, roast, then the pair
        r.typed("ช่วยแนะนำหน่อยค่ะ", "t1")
        r.typed("ดริปค่ะ", "t2")
        res = r.typed("คั่วอ่อน", "t3")
        self.assertEqual(labels(res["bot"][0]["buttons"]), ["เกอิชา", "วอชด์ อาราบิก้า", "ดูตัวอื่น"])
        self.assertEqual(res["log_entry"]["applied"], [{"set": "recommend.roast", "to": "light"}])
        self.assertEqual(r.state().options_shown, ["DH-001", "MM-001"])
        self.assertEqual(len(res["raw"]["request"]["questions"]["intent"]["criteria"]), 23)   # select_option not yet in scope
        # 3.1: ตัวแรกค่ะ — Jev names the first product from shop_said; the card; then เอาค่ะ → the quantity
        res = r.typed("ตัวแรกค่ะ", "t4")
        self.assertIn("select_option", res["raw"]["request"]["questions"]["intent"]["criteria"])
        self.assertTrue(res["bot"][0]["text"].startswith("Geisha Light Roast 200g (เกอิชา ดอยหอม) —"))
        self.assertEqual(res["log_entry"]["applied"], [{"set": "focus_sku", "to": "DH-001", "product_from": "jev"}])
        res = r.typed("เอาค่ะ", "t5")
        self.assertEqual((res["outcome"], res["log_entry"]["jev"]["intent"], res["bot"][0]["response_id"]), ("matched", "affirm", "ask_quantity"))
        # 3.2: the shipping answer, then the quantity question again; the order unchanged
        res = r.typed("ค่าส่งเท่าไหร่คะ", "t6")
        self.assertEqual([b["response_id"] for b in res["bot"]], ["faq.shipping_fee", "resume:quantity"])
        self.assertEqual(res["bot"][0]["text"], "ค่าส่ง 100 บาททั่วประเทศ ส่งฟรีเมื่อสั่งครบ 5 ถุงขึ้นไป จัดส่ง 2-3 วันทำการ")
        self.assertEqual(r.state().order["lines"], [{"sku": "DH-001", "qty": None, "added_by": "customer"}])
        # 3.3: 1 ถุงค่ะ by state — the product from the context; the Geisha promotion offered
        res = r.typed("1 ถุงค่ะ", "t7")
        self.assertTrue(res["log_entry"]["jev"]["by_state"])
        self.assertEqual(res["log_entry"]["applied"], [{"set": "lines[DH-001].qty", "to": 1, "product_from": "context:ask_quantity"}])
        self.assertEqual(r.state().contexts["offer_promo"]["params"]["promo_id"], "PROMO-02")
        # 3.4: view_order — the order so far as data, the promotion re-offered, the quantity not re-asked
        res = r.typed("ตอนนี้สั่งอะไรไปบ้างคะ", "t8")
        self.assertEqual([b["response_id"] for b in res["bot"]], ["view_order", "resume:promotion"])
        self.assertEqual(res["bot"][0]["readback"]["rows"], [["เกอิชา × 1 ถุง", "980 บาท"], ["ค่าส่ง", "100 บาท"], ["รวม", "1,080 บาท"]])
        self.assertEqual((res["bot"][0]["variant"], res["bot"][0]["readback"]["delivery_text"], res["bot"][0]["readback"]["tail"]), ("read-back", None, ""))
        self.assertEqual(res["log_entry"]["applied"], [])
        promo_id = res["bot"][1]["id"]
        # 3.4b: the promotion, cod, the sample details — by click
        res = r.click({"label": "เพิ่มเนเชอรัล แอนแอโรบิก", "intent": "affirm", "params": {}, "message_id": promo_id}, "c1")
        self.assertEqual(r.state().order["promo_applied"], "PROMO-02")
        res = r.click({"label": "เก็บเงินปลายทาง", "intent": "inform", "params": {"payment": "cod"}, "message_id": res["bot"][-1]["id"]}, "c2")
        self.assertEqual(res["log_entry"]["applied"], [{"set": "payment", "to": "cod"}])
        res = r.click({"label": "ใช้ข้อมูลตัวอย่าง", "intent": "give_delivery_details", "params": {"sample": True}, "message_id": res["bot"][-1]["id"]}, "c3")
        rb = res["bot"][0]["readback"]
        self.assertEqual(len(rb["rows"]), 6)
        self.assertEqual(rb["rows"][2], ["ส่วนลด ชุดชิมคั่วอ่อน", "−80 บาท"])
        self.assertEqual(rb["total"], 980 + 520 - 80 + 100 + 30)
        s = r.state()
        hash_a = s.contexts["confirm_order"]["params"]["order_hash"]
        self.assertEqual(s.focus_sku, "DH-001")
        # 3.5: a change that names no product goes to the line in focus; no line added; read back again
        res = r.typed("ขอเปลี่ยนเป็น 3 ถุงค่ะ", "t9")
        s = r.state()
        self.assertEqual(s.order["lines"], [{"sku": "DH-001", "qty": 3, "added_by": "customer"}, {"sku": "DH-003", "qty": 1, "added_by": "PROMO-02"}])
        self.assertEqual(res["log_entry"]["applied"], [{"set": "lines[DH-001].qty", "to": 3, "product_from": "focus_sku"}])
        self.assertEqual(res["bot"][0]["text"], "ได้เลยค่ะ แก้ให้แล้วนะคะ")
        self.assertEqual(res["bot"][1]["readback"]["total"], 980 * 3 + 520 - 80 + 100 + 30)
        hash_b = s.contexts["confirm_order"]["params"]["order_hash"]
        self.assertNotEqual(hash_a, hash_b)
        # 3.5b: hesitation — asks what to change, without pressing; the order stands; the read-back's context too
        res = r.typed("เดี๋ยวก่อนนะ ขอคิดดูก่อน", "t10")
        s = r.state()
        self.assertEqual(res["bot"][0]["text"], "ได้เลยค่ะ อยากแก้ส่วนไหนคะ? หรือจะคิดดูก่อนก็ได้น้า")
        self.assertEqual(labels(res["bot"][0]["buttons"]), ["เปลี่ยนสินค้า", "เปลี่ยนจำนวน", "เปลี่ยนวิธีชำระ"])
        self.assertEqual(len(res["bot"]), 1)
        self.assertEqual(res["log_entry"]["applied"], [])
        self.assertEqual(s.order["lines"][0]["qty"], 3)
        self.assertEqual(s.contexts["confirm_order"]["params"]["order_hash"], hash_b)
        # 3.6: a typed ยืนยันค่ะ confirms the order that was read out — hash B
        res = r.typed("ยืนยันค่ะ", "t11")
        self.assertEqual(r.state().order["order_code"], "BEAN-2609-0014")
        self.assertEqual(r.client.calls, 11)

    def test_a_stale_hash_reads_back_again_and_the_promotion_is_rechecked(self):  # contract § confirm_order, § promo_applied
        r = Rig(self, (200, reply("affirm", 0.97)), (200, reply("change_order", 0.9, product="KBN-001")),
                (200, reply("affirm", 0.97)))
        s = r.s
        s.order["lines"] = [{"sku": "DH-001", "qty": 1, "added_by": "customer"}, {"sku": "DH-003", "qty": 1, "added_by": "PROMO-02"}]
        s.order["promo_applied"], s.order["payment"], s.order["delivery_text"] = "PROMO-02", "transfer", order.SAMPLE_DETAILS
        s.promos_offered, s.focus_sku = ["PROMO-02"], "DH-001"
        s.contexts = {"confirm_order": {"expires_after_turn": 3, "params": {"order_hash": "stale-hash"}}}
        r.store.commit(s)
        res = r.typed("ยืนยันค่ะ", "t1")
        s = r.state()
        self.assertIsNone(s.order["order_code"])                                        # not confirmed
        self.assertEqual(res["bot"][0]["response_id"], "confirm")                        # read back again instead
        self.assertEqual(s.contexts["confirm_order"]["params"]["order_hash"], order.order_hash(s.order))
        self.assertEqual(res["log_entry"]["applied"], [])
        # a change to a product not in the order replaces the focus line; PROMO-02 no longer fits and is removed, said so
        res = r.typed("ขอเปลี่ยนเกอิชาเป็นเฮาส์เบลนด์", "t2")
        s = r.state()
        self.assertEqual([l["sku"] for l in s.order["lines"]], ["KBN-001", "DH-003"])
        self.assertEqual(len(s.order["lines"]), 2)                                        # replaced, not added
        self.assertIsNone(s.order["promo_applied"])
        self.assertEqual(res["log_entry"]["applied"], [{"set": "lines[DH-001].sku", "to": "KBN-001", "product_from": "jev"},
                                                       {"set": "promo_applied", "to": None, "was": "PROMO-02"}])
        self.assertEqual(res["bot"][0]["text"], "ได้เลยค่ะ แก้ให้แล้วนะคะ โปร ชุดชิมคั่วอ่อน ไม่เข้าเงื่อนไขแล้ว แอดเอาออกให้นะคะ")
        self.assertEqual(res["bot"][1]["response_id"], "promo.offer")                     # PROMO-03 now fits and was never offered
        self.assertEqual(s.contexts["offer_promo"]["params"]["promo_id"], "PROMO-03")
        res = r.typed("เอาค่ะ", "t3")
        s = r.state()
        self.assertEqual((s.order["lines"][0]["qty"], s.order["promo_applied"]), (6, "PROMO-03"))
        self.assertEqual(res["bot"][-1]["response_id"], "confirm")                        # payment and delivery stand: read back
        self.assertEqual(res["bot"][-1]["readback"]["rows"][2], ["ส่วนลด เฮาส์เบลนด์ยกลัง", "−180 บาท"])
        self.assertEqual(res["bot"][-1]["readback"]["rows"][3], ["ค่าส่ง", "ฟรี"])

    def test_cancel_clears_what_the_contract_says(self):  # AC-5: walk § 4.3
        r = Rig(self, (200, reply("order_product", 0.93, product="KBN-001", quantity="2")), (200, reply("cancel_order", 0.96)),
                (200, reply("view_order", 0.9)))
        res = r.typed("เอาเฮาส์เบลนด์ 2 ถุงค่ะ", "t1")
        s = r.state()
        self.assertEqual(s.order["lines"], [{"sku": "KBN-001", "qty": 2, "added_by": "customer"}])
        self.assertEqual((s.promos_offered, list(s.contexts), s.pending_prompt["slot"], s.focus_sku), (["PROMO-03"], ["offer_promo"], "promotion", "KBN-001"))
        res = r.typed("ยกเลิกออเดอร์ค่ะ", "t2")
        s = r.state()
        self.assertEqual(s.order, session.empty_order())
        self.assertEqual((s.contexts, s.focus_sku, s.pending_prompt, s.promos_offered, s.options_shown), ({}, None, None, [], []))
        self.assertEqual(res["log_entry"]["applied"], [{"set": "order", "to": "cleared"}])
        self.assertEqual(res["bot"][0]["text"], "ยกเลิกให้แล้วค่ะ ไม่ urgent น้า ลองดูก่อนได้ สนใจเมื่อไหร่ทักแอดได้เลยค่ะ 🙏🏻")
        self.assertEqual(res["bot"][0]["buttons"], [{"label": "ดูเมล็ดทั้งหมด", "intent": "browse_catalog", "params": {}},
                                                    {"label": "เริ่มใหม่", "intent": "start_over", "params": {}}])
        self.assertEqual(len(res["bot"]), 1)                                              # it waits; no lead
        self.assertEqual(res["log_entry"]["contexts_after"], [])
        res = r.typed("สั่งอะไรไปบ้าง", "t3")
        self.assertEqual((res["bot"][0]["text"], len(res["bot"])), ("ตอนนี้ยังไม่มีรายการในออเดอร์ค่ะ", 1))
        self.assertNotIn("readback", res["bot"][0])
        self.assertEqual(labels(res["bot"][0]["buttons"]), labels(turn.help_buttons(FLOW)))

    def test_browse_promotions_and_a_pick_checked_against_the_list(self):  # walk § 2.5; contract § select_option
        r = Rig(self, (200, reply("browse_catalog", 0.9)), (200, reply("browse_catalog", 0.9)),
                (200, reply("select_option", 0.7)), (200, reply("select_option", 0.8, product="MM-004")),
                (200, reply("ask_promotion", 0.9)), (200, reply("ask_promotion", 0.9)))
        res = r.typed("ขอดูเมล็ดหน่อย", "t1")
        self.assertEqual(labels(res["bot"][0]["buttons"]), ["ดอยหอม", "คั่วบ้านนา", "เมล็ดเมือง"])
        self.assertTrue(res["bot"][0]["text"].startswith("ตอนนี้ Beanly มี 10 ตัวจาก 3 โรงคั่วค่ะ"))
        # a roaster, by click or by name: its products, as select_option buttons; options_shown set
        res = r.click({"label": "คั่วบ้านนา", "intent": "browse_catalog", "params": {}, "message_id": res["bot"][0]["id"]}, "c1")
        self.assertEqual(labels(res["bot"][0]["buttons"]), ["เฮาส์เบลนด์", "เอสเปรสโซ่คั่วเข้ม", "ดีแคฟ"])
        self.assertEqual([b["params"] for b in res["bot"][0]["buttons"]], [{"product": "KBN-001"}, {"product": "KBN-002"}, {"product": "KBN-003"}])
        self.assertTrue(res["bot"][0]["text"].startswith("ของคั่วบ้านนามี 3 ตัวค่ะ\n📍 เฮาส์เบลนด์: "))
        self.assertEqual(r.state().options_shown, ["KBN-001", "KBN-002", "KBN-003"])
        self.assertEqual(r.state().contexts["options_shown"]["params"], {"skus": ["KBN-001", "KBN-002", "KBN-003"]})
        res = r.typed("ของเมล็ดเมืองมีอะไรบ้าง", "t2")
        self.assertEqual(len(res["bot"][0]["buttons"]), 4)
        self.assertEqual(r.state().options_shown, ["MM-001", "MM-002", "MM-003", "MM-004"])
        # a pick Jev could not resolve: the bot asks which, offering the list actually shown
        res = r.typed("อันนั้นค่ะ", "t3")
        self.assertEqual(res["bot"][0]["text"], turn.WHICH_PRODUCT)
        self.assertEqual([b["params"]["product"] for b in res["bot"][0]["buttons"]], ["MM-001", "MM-002", "MM-003", "MM-004"])
        self.assertEqual(res["log_entry"]["applied"], [])
        self.assertIn("options_shown", r.state().contexts)
        res = r.typed("ตัวสุดท้าย", "t4")
        self.assertTrue(res["bot"][0]["text"].startswith("Single Origin Doi Saeng Ngoen Dark 250g (ดอยแสงเงิน คั่วเข้ม) —"))
        self.assertEqual(r.state().focus_sku, "MM-004")
        self.assertEqual(r.state().contexts["offer_product"]["params"], {"sku": "MM-004"})
        # ask_promotion: the four, PROMO-05 never; on an empty order it waits
        res = r.typed("มีโปรอะไรบ้าง", "t5")
        self.assertEqual(len(res["bot"]), 1)
        self.assertEqual(res["bot"][0]["text"].count("📍"), 4)
        self.assertNotIn("ซื้อหนึ่งแถมหนึ่ง", res["bot"][0]["text"])
        self.assertIn("📍 ส่งฟรีครบ 5 ถุง: สั่งครบ 5 ถุงขึ้นไปในออเดอร์เดียว", res["bot"][0]["text"])
        self.assertEqual([b["intent"] for b in res["bot"][0]["buttons"]], ["ask_recommendation", "browse_catalog"])
        # mid-order, the pending question is asked again after the list
        s = r.state()
        s.order["lines"] = [{"sku": "MM-004", "qty": None, "added_by": "customer"}]
        turn.lead(s, FLOW, s.turn_no + 1)
        r.store.commit(s)
        res = r.typed("มีโปรอะไรบ้าง", "t6")
        self.assertEqual([b["response_id"] for b in res["bot"]], ["ask_promotion", "resume:quantity"])

    def test_f4_first_miss_after_a_faq_offers_the_help_buttons(self):  # Findings F-4, fixed here
        r = Rig(self, (200, reply("faq.shipping_fee", 0.97)), (200, reply("none", 0.93)))
        res = r.typed("ค่าส่งเท่าไหร่คะ", "t1")
        self.assertEqual((res["bot"][0]["buttons"], len(res["bot"])), ([], 1))          # nothing pending: no resume, no buttons
        self.assertEqual(r.state().live_buttons, [])
        res = r.typed("มีหน้าร้านไหมคะ", "t2")
        self.assertEqual((res["outcome"], res["bot"][0]["response_id"]), ("fallback", "fallback.1"))
        self.assertEqual(labels(res["bot"][0]["buttons"]), labels(turn.help_buttons(FLOW)))
        self.assertEqual(r.state().live_buttons, [])                                      # a miss's bubble is not live


say = turn.say


if __name__ == "__main__":
    unittest.main()
