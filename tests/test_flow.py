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


class CopiesTests(unittest.TestCase):
    def test_copies_are_byte_identical(self):
        # the flow file is the spike's catalogue, byte for byte — "lifted, not rewritten"
        self.assertEqual(sha256(flow.CATALOGUE), sha256(SPIKE_CATALOGUE))
        self.assertEqual(flow.CATALOGUE.read_bytes(), SPIKE_CATALOGUE.read_bytes())
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
        self.assertEqual(len(f.events), 3)
        self.assertEqual(len(f.products), 10)
        self.assertEqual(list(f.entities), ["product", "quantity", "brew", "roast", "payment"])
        self.assertEqual(sorted(f.events), ["button_click", "use_sample_details", "welcome"])
        self.assertIn("options_shown", f.contexts)
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


if __name__ == "__main__":
    unittest.main()
