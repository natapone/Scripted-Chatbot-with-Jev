"""Story 2.1 — the catalogue's test set and its scoring, in `app/testset.py` (lifted from the
rehearsal script, which now imports them). Hermetic: no network."""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from app import flow, order, testset, turn

_spec = importlib.util.spec_from_file_location(
    "replay_s3", Path(__file__).resolve().parent / "rehearsal" / "replay_s3.py")
replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(replay)

FLOW = flow.load()
CAT = testset.read_catalogue()


class TestSetTests(unittest.TestCase):

    def test_one_copy_shared_with_the_rehearsal(self):
        for name in ("load_cases", "build_session", "scored_entities", "loop_intent", "score", "read_catalogue"):
            self.assertIs(getattr(replay, name), getattr(testset, name), name)
        cases = testset.load_cases(CAT)
        self.assertEqual(len(cases), 129)
        self.assertEqual([c["n"] for c in cases], list(range(1, 130)))
        self.assertTrue(any(c["intent"] == "give_delivery_details" for c in cases))
        self.assertTrue(any(c["intent"] == "none" for c in cases))

    def test_the_delivery_cases_are_asked_as_the_customer_sees_it(self):  # Story 2.7, F-30
        cases = [c for c in testset.load_cases(CAT) if "ask_delivery" in c["contexts"]]
        self.assertEqual([c["n"] for c in cases], [106, 107, 108])
        for c in cases:
            req = turn.build_request(testset.build_session(c, FLOW), c["text"], FLOW)
            self.assertEqual(c["shop_said"], turn.ASK_DELIVERY)
            self.assertEqual(req["state"]["shop_said"], "รบกวนขอชื่อ ที่อยู่ และเบอร์โทรสำหรับจัดส่งค่ะ")
            self.assertNotIn("เดโมนี้", json.dumps(req, ensure_ascii=False))

    def test_score_counts_the_loops_intent_against_the_label(self):
        cases = testset.load_cases(CAT)
        case = next(c for c in cases if c["intent"] == "greet")
        s = testset.build_session(case, FLOW)
        req = turn.build_request(s, case["text"], FLOW)
        v = turn.Verdict("matched", req, None, intent="greet")
        self.assertTrue(testset.score(CAT, case, v)["loop_ok"])
        v = turn.Verdict("model_failed", req, None)
        r = testset.score(CAT, case, v)
        self.assertEqual((r["loop"], r["loop_ok"], r["cost_usd"]), (None, False, 0.0))


class FilledOrderTests(unittest.TestCase):
    """Story 2.6 — each case's session holds the order a shop would hold at that step (F-23), and the
    request to Jev is byte-identical to the one Story 2.1's order-less session built."""

    def test_the_request_to_jev_is_byte_identical_for_every_case(self):  # AC-1
        cases = testset.load_cases(CAT)
        filled = 0
        for c in cases:
            before = testset.build_session(c, FLOW, filled=False)
            after = testset.build_session(c, FLOW)
            filled += bool(after.order["lines"] or after.focus_sku)
            a = json.dumps(turn.build_request(before, c["text"], FLOW), ensure_ascii=False, sort_keys=True)
            b = json.dumps(turn.build_request(after, c["text"], FLOW), ensure_ascii=False, sort_keys=True)
            self.assertEqual(a, b, c["n"])
            # what decides the verdict besides Jev's answer is unchanged too: the pending slot and the contexts
            self.assertEqual((before.pending_prompt or {}).get("slot"), (after.pending_prompt or {}).get("slot"))
            self.assertEqual(before.live_contexts(), after.live_contexts())
            self.assertEqual(before.transcript, after.transcript)
        self.assertEqual(filled, 34)          # read-back 6, address 3, payment 3, quantity 3, promotion 4, product card 3, change/view/cancel 12
        self.assertEqual(testset.build_session(cases[0], FLOW, filled=False).order, testset.build_session(cases[0], FLOW).order)

    def test_the_order_matches_what_the_shop_said(self):  # AC-5
        cases = testset.load_cases(CAT)
        for c in cases:
            s = testset.build_session(c, FLOW)
            ctx = set(c["contexts"])
            with self.subTest(n=c["n"]):
                if "confirm_order" in ctx:         # the read-back's lines and total, as read out
                    t = order.totals(s.order, FLOW.products)
                    self.assertIn(f"รวม {t['total']:,} บาท", c["shop_said"])
                    for line in s.order["lines"]:
                        self.assertIn(f"{FLOW.products[line['sku']]['spoken_name']} × {line['qty']} ถุง", c["shop_said"])
                    self.assertEqual(s.contexts["confirm_order"]["params"], {"order_hash": order.order_hash(s.order)})
                    self.assertEqual(s.order["delivery_text"], order.SAMPLE_DETAILS)   # the test set's fictional address
                elif "offer_promo" in ctx:         # the promotion offered is the one the line fits
                    pid = s.contexts["offer_promo"]["params"]["promo_id"]
                    self.assertTrue(order.offer_text(pid).startswith(c["shop_said"].split(" สนใจไหมคะ")[0]))
                    self.assertEqual(order.fit_promo(s.order, [])["promo_id"], pid)
                    self.assertEqual(s.promos_offered, [pid])
                elif "offer_product" in ctx:       # the product on the card
                    sku = s.contexts["offer_product"]["params"]["sku"]
                    self.assertTrue(c["shop_said"].startswith(FLOW.products[sku]["spoken_name"] + " — "))
                    self.assertEqual((s.focus_sku, s.order["lines"]), (sku, []))
                elif "ask_quantity" in ctx:
                    self.assertEqual(s.order["lines"], [{"sku": "KBN-001", "qty": None, "added_by": "customer"}])
                    self.assertEqual(s.pending_prompt["params"], {"sku": "KBN-001"})
                elif ctx & {"ask_payment", "ask_delivery"} or (not ctx and c["intent"] in testset.ORDER_ABOUT):
                    self.assertEqual([(l["sku"], l["qty"]) for l in s.order["lines"]], [("KBN-001", 2)])
                    self.assertEqual(s.promos_offered, ["PROMO-03"])
                    self.assertEqual(s.order["payment"], "transfer" if "ask_delivery" in ctx else None)
                    self.assertIsNone(s.order["delivery_text"])
                else:                              # every other case starts from an empty order, as before
                    self.assertEqual(s.order, testset.build_session(c, FLOW, filled=False).order)
                    self.assertIsNone(s.focus_sku)


if __name__ == "__main__":
    unittest.main()
