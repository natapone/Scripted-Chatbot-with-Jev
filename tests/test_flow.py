"""Story 1.2 — the flow file and the request builder. Hermetic: reads the repo's own files, no network."""
from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

from app import flow

ROOT = Path(__file__).resolve().parent.parent
SPIKE_CATALOGUE = ROOT / "spikes" / "S-3_jev_intent_catalogue" / "catalogue.json"
SOURCE = ROOT / "memory" / "source"
SOURCE_INDEX = SOURCE / "index.md"
COPIES = {"product": "2026-09-20_1022_thclaw-poc02-product.csv",
          "faq": "2026-09-20_1022_thclaw-poc02-faq.csv",
          "promotion": "2026-09-20_1022_thclaw-poc02-promotion.csv"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_from_index(source_name: str) -> str:
    """The sha256 column of that file's row in memory/source/index.md."""
    for line in SOURCE_INDEX.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"| {source_name} |"):
            m = re.search(r"\b([0-9a-f]{64})\b", line)
            assert m, line
            return m.group(1)
    raise AssertionError(f"no row for {source_name} in {SOURCE_INDEX}")


@unittest.skipUnless(SPIKE_CATALOGUE.exists() and SOURCE_INDEX.exists(),
                     "spikes/ and memory/ are local-only, not in this clone")
class CopiesTests(unittest.TestCase):
    def test_copies_are_byte_identical(self):
        # the flow file was lifted from the spike's catalogue and has since been edited (button
        # labels, sharper descriptions): what still holds is the same intents and the same option keys
        app_cat = json.loads(flow.CATALOGUE.read_text(encoding="utf-8"))
        spike = json.loads(SPIKE_CATALOGUE.read_text(encoding="utf-8"))
        self.assertEqual([i["id"] for i in app_cat["intents"]], [i["id"] for i in spike["intents"]])
        for name, e in spike["entities"].items():
            self.assertEqual(list(app_cat["entities"][name].get("options", {})), list(e.get("options", {})), name)
        # the three tables are the owner's files: equal to the source bytes and to the index's digests
        for short, source_name in COPIES.items():
            copy = flow.DATA / f"{short}.csv"
            self.assertEqual(copy.read_bytes(), (SOURCE / source_name).read_bytes(), short)
            self.assertEqual(sha256(copy), digest_from_index(source_name), short)
        self.assertEqual(sha256(flow.DATA / "product.csv"),
                         "b500500cdca14778977d4e5017105634d23dc016691aaf81bf85f7c52596b98d")


class LoadTests(unittest.TestCase):
    def test_load_counts_and_shape(self):
        f = flow.load()
        self.assertEqual(len(f.intents), 26)
        self.assertEqual(len(f.contexts), 9)
        self.assertEqual(len(f.entities), 5)
        self.assertEqual(len(f.events), 2)                      # Story 2.7: the sample-details event is gone
        self.assertEqual(len(f.products), 10)
        self.assertEqual(list(f.entities), ["product", "quantity", "brew", "roast", "payment"])
        self.assertEqual(sorted(f.events), ["button_click", "welcome"])
        self.assertIn("options_shown", f.contexts)
        # F-30: the shop's delivery question, as Jev is told it was asked, is what the customer sees
        from app import turn
        examples = next(i for i in f.intents if i["id"] == "give_delivery_details")["examples"]
        self.assertEqual([e["shop_said"] for e in examples], [turn.ASK_DELIVERY] * 3)
        raw = flow.CATALOGUE.read_text(encoding="utf-8")
        for gone in ("ใช้ข้อมูลตัวอย่าง", "เดโมนี้", "use_sample_details"):
            self.assertNotIn(gone, raw)
        self.assertEqual(f.contexts["options_shown"]["brings_into_scope"], ["select_option"])
        self.assertEqual(f.fallback["id"], "none")
        self.assertTrue(f.fallback["description"])
        self.assertEqual(f.default_shop_said, "มีอะไรให้แอดช่วยอีกไหมคะ?")
        self.assertIn("Beanly", f.intent_question)
        self.assertEqual(f.model, "typesafe/jev-1.13")
        # 22 global intents, 4 scoped by context — the S-3 dry-run's "min 23 (incl. none)"
        self.assertEqual(sum(1 for i in f.intents if i["scope"] == "global"), 22)
        self.assertEqual([i["id"] for i in f.intents if i["scope"] != "global"],
                         ["affirm", "deny", "select_option", "give_delivery_details"])
        # products: {sku: row} with the S-1 spoken_name/price/note columns, and the S-1 option shape
        self.assertIn("DH-001", f.products)
        for p in f.products.values():
            for col in ("sku", "name", "spoken_name", "price", "note"):
                self.assertIn(col, p)
        opts = f.product_options()
        self.assertEqual(len(opts), 10)
        self.assertEqual(opts["DH-001"], f'{f.products["DH-001"]["spoken_name"]} — {f.products["DH-001"]["note"]}')
        self.assertTrue(all(" — " in v for v in opts.values()))
        # the flow file's product entity takes its options from the table, not from the file
        self.assertNotIn("options", f.entities["product"])
        self.assertIn("options_from", f.entities["product"])
        # loading is read-only and the loaded sections are the file's own
        self.assertEqual(json.loads(flow.CATALOGUE.read_text(encoding="utf-8"))["contexts"], f.contexts)


class BuildRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flow = flow.load()

    def test_no_context_offers_globals_plus_none(self):  # AC-1
        r = self.flow.build_request("รับกี่ถุงดีคะ?", "1 ถุงค่ะ", "quantity", [], [])
        self.assertEqual(sorted(r), ["model", "questions", "state"])
        self.assertEqual(r["model"], "typesafe/jev-1.13")
        self.assertEqual(list(r["questions"]), ["intent", "product", "quantity", "brew", "roast", "payment"])
        intent = r["questions"]["intent"]
        self.assertEqual(intent["type"], "choice")
        self.assertEqual(intent["instructions"], self.flow.intent_question)
        self.assertEqual(len(intent["criteria"]), 23)                 # 22 global + none
        self.assertEqual(list(intent["criteria"])[-1], "none")
        for scoped in ("affirm", "deny", "select_option", "give_delivery_details"):
            self.assertNotIn(scoped, intent["criteria"])
        self.assertEqual(len(self.flow.in_scope([])), 22)
        # every entity question is a choice with not_mentioned last; product options are the table's
        for name in ("product", "quantity", "brew", "roast", "payment"):
            q = r["questions"][name]
            self.assertEqual(q["type"], "choice")
            self.assertEqual(q["instructions"], self.flow.entities[name]["instructions"])
            self.assertEqual(list(q["criteria"])[-1], "not_mentioned")
            self.assertEqual(q["criteria"]["not_mentioned"], self.flow.entities[name]["not_mentioned"])
        self.assertEqual(len(r["questions"]["product"]["criteria"]), 11)   # 10 SKUs + not_mentioned
        self.assertEqual(r["questions"]["product"]["criteria"]["DH-001"], self.flow.product_options()["DH-001"])
        self.assertEqual(list(r["questions"]["quantity"]["criteria"]), ["1", "2", "3", "4", "5", "6", "more", "not_mentioned"])
        self.assertEqual(r["state"], {"shop_said": "รับกี่ถุงดีคะ?", "customer_said": "1 ถุงค่ะ",
                                      "awaiting": "quantity", "history": []})

    def test_context_scope_and_state_keys(self):  # AC-2
        history = [{"who": "bot", "text": "สวัสดีค่ะ"}, {"who": "customer", "text": "ขอดูเมล็ดหน่อย"},
                   {"who": "bot", "text": "มี 3 ตัวค่ะ …"}]
        r = self.flow.build_request("มี 3 ตัวค่ะ …", "ตัวแรกค่ะ", None, history, ["options_shown"])
        crit = r["questions"]["intent"]["criteria"]
        self.assertIn("select_option", crit)
        self.assertEqual(len(crit), 24)
        self.assertEqual(sorted(r["state"]), ["awaiting", "customer_said", "history", "shop_said"])
        self.assertIsNone(r["state"]["awaiting"])
        self.assertEqual(r["state"]["history"], history)            # as passed in — 1.3 masks
        self.assertIsNot(r["state"]["history"], history)            # a copy: the request is its own
        # the S-3 dry-run's max: offer_product/offer_promo/confirm_order bring in affirm and deny → 25
        for ctx in ("offer_product", "offer_promo", "confirm_order"):
            ids = [i["id"] for i in self.flow.in_scope([ctx])]
            self.assertEqual(ids[-2:], ["affirm", "deny"], ctx)
            self.assertEqual(len(self.flow.build_request(None, "เอาค่ะ", None, [], [ctx])["questions"]["intent"]["criteria"]), 25)
        self.assertEqual([i["id"] for i in self.flow.in_scope(["ask_delivery"])][-1], "give_delivery_details")
        self.assertEqual(len(self.flow.in_scope(["ask_quantity", "ask_brew"])), 22)  # brings nothing in
        # shop_said None → the catalogue's default_shop_said
        self.assertEqual(self.flow.build_request(None, "x", None, [], [])["state"]["shop_said"],
                         self.flow.default_shop_said)
        self.assertEqual(self.flow.build_request("", "x", None, [], [])["state"]["shop_said"],
                         self.flow.default_shop_said)

    def test_only_in_context_and_size(self):
        # an entity with only_in_context is asked only under that context, as S-3's entity_questions did
        ents = dict(self.flow.entities)
        ents["delivery_slot"] = {"instructions": "When?", "only_in_context": "ask_delivery",
                                 "options": {"am": "เช้า", "pm": "บ่าย"}, "not_mentioned": "ไม่ได้บอก"}
        f = flow.Flow(intents=self.flow.intents, contexts=self.flow.contexts, entities=ents,
                      events=self.flow.events, fallback=self.flow.fallback,
                      default_shop_said=self.flow.default_shop_said,
                      intent_question=self.flow.intent_question, products=self.flow.products)
        self.assertNotIn("delivery_slot", f.questions([]))
        self.assertNotIn("delivery_slot", f.questions(["ask_quantity"]))
        self.assertEqual(f.questions(["ask_delivery"])["delivery_slot"]["criteria"],
                         {"am": "เช้า", "pm": "บ่าย", "not_mentioned": "ไม่ได้บอก"})
        self.assertEqual(len(f.build_request(None, "x", None, [], ["ask_delivery"])["questions"]), 7)
        # the request is JSON-serialisable and within S-3's ~10 KB
        for ctx in ([], ["options_shown"], ["confirm_order"]):
            body = json.dumps(self.flow.build_request(None, "ขอเปลี่ยนเป็น 3 ถุงค่ะ", "quantity", [], ctx),
                              ensure_ascii=False).encode("utf-8")
            self.assertLess(len(body), 12_000, ctx)
            self.assertGreater(len(body), 4_000, ctx)


if __name__ == "__main__":
    unittest.main()
