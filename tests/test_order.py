"""Story 1.4 — the order form's rules, without a session. Hermetic: the tables only, no server, no Jev."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app import flow, order
from app.session import empty_order

FLOW = flow.load()
P = FLOW.products


def form(*lines, promo=None, payment=None, delivery=None):
    o = empty_order()
    o["lines"] = [{"sku": sku, "qty": qty, "added_by": "customer"} for sku, qty in lines]
    o["promo_applied"], o["payment"], o["delivery_text"] = promo, payment, delivery
    return o


class TotalsTests(unittest.TestCase):
    def test_the_walks_1270_and_the_fees(self):  # walk § 2.3; prototype totals()
        t = order.totals(form(("KBN-002", 3), payment="cod"), P)
        self.assertEqual(t, {"sub": 1140, "discount": 0, "shipping": 100, "cod": 30, "total": 1270, "bags": 3})
        self.assertEqual(order.totals(form(("KBN-001", 5)), P)["shipping"], 0)                 # free at 5
        self.assertEqual(order.totals(form(("KBN-001", 4)), P)["shipping"], 100)
        self.assertEqual(order.totals(form(("DH-001", 1), ("DH-003", 1), promo="PROMO-02"), P)["total"], 980 + 520 - 80 + 100)
        t = order.totals(form(("KBN-001", 6), promo="PROMO-03"), P)
        self.assertEqual((t["discount"], t["shipping"], t["total"]), (180, 0, 6 * 350 - 180))
        self.assertEqual(order.totals(form(("DH-001", None)), P), {"sub": 0, "discount": 0, "shipping": 100, "cod": 0, "total": 100, "bags": 0})
        self.assertEqual(order.totals(empty_order(), P)["total"], 100)

    def test_readback_rows_as_the_prototype_wrote_them(self):  # prototype readback(); Delta: the read-back as data
        d = order.readback_data(form(("DH-001", 2), ("DH-003", 1), promo="PROMO-02", payment="cod", delivery=order.SAMPLE_DETAILS), P)
        self.assertEqual(d["rows"], [["เกอิชา × 2 ถุง", "1,960 บาท"], ["เนเชอรัล แอนแอโรบิก × 1 ถุง", "520 บาท"],
                                     ["ส่วนลด ชุดชิมคั่วอ่อน", "−80 บาท"], ["ค่าส่ง", "100 บาท"],
                                     ["ค่าบริการเก็บเงินปลายทาง", "30 บาท"], ["รวม", "2,530 บาท"]])
        self.assertEqual((d["total"], d["delivery_text"], d["lead"]), (2530, order.SAMPLE_DETAILS, "สรุปออเดอร์ค่ะ"))
        self.assertTrue(d["tail"].startswith(f"จัดส่งที่: {order.SAMPLE_DETAILS}"))
        self.assertTrue(d["tail"].endswith("ยืนยันให้แอดน้า 🙏🏻"))
        text = order.readback_text(d)
        self.assertIn("เกอิชา × 2 ถุง — 1,960 บาท", text)
        self.assertIn("รวม 2,530 บาท", text)
        self.assertIn(order.SAMPLE_DETAILS, text)
        # view_order's read-back: no address, no ask; free shipping reads ฟรี
        d = order.readback_data(form(("KBN-001", 5)), P, ask=False)
        self.assertEqual(d["rows"], [["เฮาส์เบลนด์ × 5 ถุง", "1,750 บาท"], ["ค่าส่ง", "ฟรี"], ["รวม", "1,750 บาท"]])
        self.assertEqual((d["delivery_text"], d["tail"]), (None, ""))
        self.assertNotIn(order.SAMPLE_DETAILS, order.readback_text(d))


class PromotionTests(unittest.TestCase):
    def test_each_rule_in_order_and_promo_05_never(self):  # conversation-flow § The promotion rules
        self.assertEqual(order.fit_promo(form(("KBN-001", 2)), [])["promo_id"], "PROMO-03")
        self.assertEqual(order.fit_promo(form(("KBN-001", 2)), [])["effect"], {"set_qty": 6, "sku": "KBN-001"})
        self.assertIsNone(order.fit_promo(form(("KBN-001", 6)), []))                       # 6 bags: rule 1 no longer fits, 4 neither
        offer = order.fit_promo(form(("DH-001", 1)), [])
        self.assertEqual((offer["promo_id"], offer["effect"], offer["take_label"]), ("PROMO-02", {"add_line": "DH-003"}, "เพิ่มเนเชอรัล แอนแอโรบิก"))
        self.assertEqual(order.fit_promo(form(("DH-003", 9)), [])["effect"], {"add_line": "DH-001"})   # rule 2 has no quantity bound
        self.assertEqual(order.fit_promo(form(("KBN-003", 1)), [])["promo_id"], "PROMO-04")
        self.assertEqual(order.fit_promo(form(("KBN-003", 2)), [])["promo_id"], "PROMO-01")            # rule 3 misses, rule 4 fits
        self.assertEqual(order.fit_promo(form(("KBN-002", 3)), [])["promo_id"], "PROMO-01")            # the walk's § 2 order
        self.assertEqual(order.fit_promo(form(("KBN-002", 3)), [])["effect"], {"set_qty": 5, "sku": "KBN-002"})
        self.assertIsNone(order.fit_promo(form(("KBN-002", 5)), []))
        self.assertEqual(order.fit_promo(form(("MM-004", None)), [])["promo_id"], "PROMO-01")          # qty null reads as 0
        self.assertIsNone(order.fit_promo(empty_order(), []))
        # offered once: the first fit already offered means nothing, not the next rule
        self.assertIsNone(order.fit_promo(form(("KBN-001", 2)), ["PROMO-03"]))
        self.assertIsNone(order.fit_promo(form(("DH-001", 1)), ["PROMO-02"]))
        # PROMO-05 never fits, is never listed, though it is in the table
        self.assertIn("PROMO-05", order.promotions())
        self.assertNotIn("PROMO-05", order.promotion_list())
        self.assertNotIn("PROMO-05", order.PROMOS_LISTED)
        for sku in P:
            for qty in (None, 1, 2, 5, 6, 9):
                o = order.fit_promo(form((sku, qty)), [])
                self.assertNotEqual((o or {}).get("promo_id"), "PROMO-05")
        listed = order.promotion_list()
        self.assertTrue(listed.startswith("ตอนนี้มีโปรตามนี้ค่ะ — 📍 ส่งฟรีครบ 5 ถุง: "))
        self.assertEqual(listed.count("📍"), 4)
        self.assertEqual(order.offer_text("PROMO-02"), "ซื้อเกอิชาคู่กับเนเชอรัล แอนแอโรบิก รับส่วนลด 80 บาท สำหรับคอกาแฟคั่วอ่อน สนใจไหมคะ? ไม่ urgent น้า ลองดูก่อนได้")

    def test_apply_exactly_the_offer_and_recheck_on_change(self):  # contract § promo_applied, § offer_promo
        o = form(("DH-001", 1))
        applied = order.apply_promo(o, "PROMO-02", {"add_line": "DH-003"})
        self.assertEqual(o["lines"], [{"sku": "DH-001", "qty": 1, "added_by": "customer"}, {"sku": "DH-003", "qty": 1, "added_by": "PROMO-02"}])
        self.assertEqual(o["promo_applied"], "PROMO-02")
        self.assertEqual(applied, [{"set": "lines[DH-003]", "to": 1, "product_from": "PROMO-02"}, {"set": "promo_applied", "to": "PROMO-02"}])
        self.assertIsNone(order.recheck_promo(o))                                   # still fits
        o["lines"][0]["qty"] = 2
        self.assertIsNone(order.recheck_promo(o))                                   # traced turn 9: still fits
        o["lines"][0]["sku"] = "KBN-001"                                            # the Geisha line replaced
        self.assertEqual(order.recheck_promo(o), "PROMO-02")
        self.assertIsNone(o["promo_applied"])
        self.assertIsNone(order.recheck_promo(o))
        # set_qty goes to the line the offer named, not whichever is first now
        o = form(("KBN-001", 2))
        self.assertEqual(order.apply_promo(o, "PROMO-03", {"set_qty": 6, "sku": "KBN-001"})[0], {"set": "lines[KBN-001].qty", "to": 6, "product_from": "PROMO-03"})
        self.assertEqual(o["lines"][0]["qty"], 6)
        self.assertIsNone(order.recheck_promo(o))
        o["lines"][0]["qty"] = 3
        self.assertEqual(order.recheck_promo(o), "PROMO-03")
        o = form(("KBN-002", 3))
        order.apply_promo(o, "PROMO-01", {"set_qty": 5, "sku": "KBN-002"})
        self.assertEqual((o["lines"][0]["qty"], order.totals(o, P)["shipping"]), (5, 0))
        o["lines"][0]["qty"] = 4
        self.assertEqual(order.recheck_promo(o), "PROMO-01")
        o = form(("KBN-003", 1))
        order.apply_promo(o, "PROMO-04", {"set_qty": 2, "sku": "KBN-003"})
        self.assertTrue(order.still_fits(o, "PROMO-04"))
        self.assertFalse(order.still_fits(o, "PROMO-05"))


class LinesAndHashTests(unittest.TestCase):
    def test_line_for_and_the_focus_rule_never_add(self):  # contract: replaced not duplicated; change_order's Delta
        o = empty_order()
        l1 = order.line_for(o, "DH-001")
        self.assertEqual(l1, {"sku": "DH-001", "qty": None, "added_by": "customer"})
        self.assertIs(order.line_for(o, "DH-001"), l1)
        self.assertEqual(len(o["lines"]), 1)
        order.line_for(o, "DH-003", added_by="PROMO-02")["qty"] = 1
        self.assertEqual([l["sku"] for l in o["lines"]], ["DH-001", "DH-003"])
        # change_target: the named line; a product not in the order → the focus line; else the first; never a new one
        self.assertIs(order.change_target(o, "DH-003", "DH-001"), o["lines"][1])
        self.assertIs(order.change_target(o, "KBN-001", "DH-003"), o["lines"][1])
        self.assertIs(order.change_target(o, "KBN-001", "MM-001"), o["lines"][0])
        self.assertIs(order.change_target(o, None, None), o["lines"][0])
        self.assertEqual(len(o["lines"]), 2)
        self.assertIsNone(order.change_target(empty_order(), "KBN-001", "KBN-001"))
        self.assertEqual(order.bags(o), 1)

    def test_hash_changes_with_the_order_and_the_code_shape(self):  # contract § confirm_order, § order_code
        o = form(("DH-001", 1), ("DH-003", 1), promo="PROMO-02", payment="cod", delivery=order.SAMPLE_DETAILS)
        a = order.order_hash(o)
        self.assertEqual(len(a), 12)
        self.assertEqual(order.order_hash(o), a)                                    # stable
        o["lines"][0]["qty"] = 2
        b = order.order_hash(o)
        self.assertNotEqual(a, b)                                                   # traced turn 9: hash A → hash B
        o["lines"][0]["qty"] = 1
        self.assertEqual(order.order_hash(o), a)
        o["payment"] = "transfer"
        self.assertNotEqual(order.order_hash(o), a)
        o["payment"] = "cod"
        o["delivery_text"] = "ที่อยู่อื่น"
        self.assertNotEqual(order.order_hash(o), a)
        o["delivery_text"] = order.SAMPLE_DETAILS
        o["promo_applied"] = None
        self.assertNotEqual(order.order_hash(o), a)
        o["lines"][0]["added_by"] = "someone"                                       # provenance is not part of the order read back
        o["promo_applied"] = "PROMO-02"
        self.assertEqual(order.order_hash(o), a)
        now = datetime(2026, 9, 22, 7, 0, tzinfo=timezone.utc)
        self.assertEqual(order.order_code(42, now), "BEAN-2609-0042")
        self.assertEqual(order.order_code(10, datetime(2027, 1, 5)), "BEAN-2701-0010")
        self.assertRegex(order.order_code(12345, now), r"^BEAN-\d{4}-\d{4}$")


class RecommendAndFaqTests(unittest.TestCase):
    def test_the_table_cell_by_cell_and_the_decaf_override(self):  # conversation-flow § The recommendation table
        self.assertEqual(sorted(order.RECOMMEND), ["any", "cold_brew", "espresso_milk", "filter"])
        self.assertEqual(order.recommend("espresso_milk", "light"), ["DH-002", "MM-002"])
        self.assertEqual(order.recommend("espresso_milk", "medium"), ["KBN-001", "DH-002"])     # walk § 1.2
        self.assertEqual(order.recommend("espresso_milk", "dark"), ["KBN-002", "MM-004"])
        self.assertEqual(order.recommend("espresso_milk", None), ["KBN-001", "DH-002"])
        self.assertEqual(order.recommend("filter", "light"), ["DH-001", "MM-001"])              # walk § 3.0
        self.assertEqual(order.recommend("filter", "medium"), ["MM-002", "DH-002"])
        self.assertEqual(order.recommend("filter", "dark"), ["MM-004", "KBN-002"])
        self.assertEqual(order.recommend("filter", None), ["MM-001", "MM-002"])
        self.assertEqual(order.recommend("cold_brew", "light"), ["DH-003", "MM-003"])
        self.assertEqual(order.recommend("cold_brew", "medium"), ["MM-003", "DH-003"])
        self.assertEqual(order.recommend("cold_brew", "dark"), ["MM-003", "MM-004"])
        self.assertEqual(order.recommend("cold_brew", None), ["MM-003", "DH-003"])
        self.assertEqual(order.recommend(None, "light"), ["DH-001", "MM-001"])
        self.assertEqual(order.recommend(None, "medium"), ["KBN-001", "DH-002"])
        self.assertEqual(order.recommend(None, "dark"), ["KBN-002", "MM-004"])
        self.assertEqual(order.recommend(None, None), ["KBN-001", "DH-002"])
        for brew in (None, "espresso_milk", "filter", "cold_brew", "any", "unknown"):
            self.assertEqual(order.recommend(brew, "decaf"), ["KBN-003"], brew)
        self.assertEqual(order.recommend("unknown", "unknown"), ["KBN-001", "DH-002"])
        # every sku named is a product in the table; the pair is a real pair
        for by_roast in order.RECOMMEND.values():
            for pair in by_roast.values():
                self.assertEqual(len(pair), 2)
                for sku in pair:
                    self.assertIn(sku, P)

    def test_faq_answers_from_the_csv(self):  # the eight prepared answers; grinding's tail
        self.assertEqual(len(order.FAQ_BY_INTENT), 8)
        self.assertEqual(order.faq_answer("faq.shipping_fee"), "ค่าส่ง 100 บาททั่วประเทศ ส่งฟรีเมื่อสั่งครบ 5 ถุงขึ้นไป จัดส่ง 2-3 วันทำการ")
        self.assertTrue(order.faq_answer("faq.grinding").endswith(" กาแฟดีต้องคู่ grind ที่ตรงเสมอค่ะ"))
        self.assertTrue(order.faq_answer("faq.grinding").startswith("มีค่ะ แจ้งได้ตอนสั่ง"))
        for intent, fid in order.FAQ_BY_INTENT.items():
            self.assertTrue(order.faq_answer(intent).startswith(order.faqs()[fid]["answer"]), intent)
            if intent != "faq.grinding":
                self.assertEqual(order.faq_answer(intent), order.faqs()[fid]["answer"])
        self.assertEqual(sorted(order.faqs()), [f"FAQ-0{i}" for i in range(1, 9)])
        with self.assertRaises(KeyError):
            order.faq_answer("faq.nope")
        self.assertEqual(order.SAMPLE_DETAILS, "สมชาย ใจดี 123/4 ซอยสุขุมวิท 50 คลองเตย กรุงเทพ 10110 โทร 081-000-0000")


if __name__ == "__main__":
    unittest.main()
