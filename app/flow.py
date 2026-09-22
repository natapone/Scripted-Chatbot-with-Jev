"""The flow file and the tables — the only reader of `app/flow/catalogue.json` and `app/data/*.csv`.

Story 1.2 lifts Spike S-3's request builder (`run_intents.py` § `in_scope`, `entity_questions`,
`build_body`) and Spike S-1's product options (`run_spike.py` § `rows`, `thai_criteria`). The
catalogue is a byte-identical copy of the spike's; the CSVs are byte-identical copies of the owner's
tables in `memory/source/` — the app never reads `memory/` at runtime. Nothing here writes to disk.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from app.config import MODEL

HERE = Path(__file__).resolve().parent
CATALOGUE = HERE / "flow" / "catalogue.json"
DATA = HERE / "data"


def rows(name: str) -> list[dict]:
    """One table from `app/data/`, as S-1's `rows()` read it: a list of dicts, one per data row."""
    with open(DATA / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@dataclass(frozen=True)
class Flow:
    intents: list[dict]                 # the catalogue's 26, in file order; each has id, scope, description …
    contexts: dict[str, dict]           # name → {lifespan, set_when, brings_into_scope, params}
    entities: dict[str, dict]           # name → {instructions, options | options_from, not_mentioned}
    events: dict[str, str]
    fallback: dict                      # {id: "none", description, ladder, examples}
    default_shop_said: str
    intent_question: str
    products: dict[str, dict] = field(default_factory=dict)  # sku → the product row (spoken_name, price, note …)
    model: str = MODEL

    def product_options(self) -> dict[str, str]:
        """S-1's `thai_criteria()["product"]`: `{sku: "spoken_name — note"}`, straight from the table."""
        return {sku: f'{p["spoken_name"]} — {p["note"]}' for sku, p in self.products.items()}

    # --- the request, as Spike S-3 proved it (run_intents.py § in_scope / entity_questions / build_body)

    def in_scope(self, contexts: list[str]) -> list[dict]:
        """The global intents plus those any live context brings in, in catalogue order."""
        live = set(contexts)
        return [it for it in self.intents if it["scope"] == "global" or set(it["scope"]) & live]

    def questions(self, contexts: list[str]) -> dict[str, dict]:
        """The five entity questions — the same every turn. An entity with `only_in_context` is asked
        only under that context (S-3's rule; the catalogue has none today). `not_mentioned` is always
        an option; the product options come from the table."""
        qs = {}
        for name, e in self.entities.items():
            if e.get("only_in_context") and e["only_in_context"] not in contexts:
                continue
            opts = self.product_options() if name == "product" else dict(e["options"])
            opts["not_mentioned"] = e["not_mentioned"]
            qs[name] = {"type": "choice", "instructions": e["instructions"], "criteria": opts}
        return qs

    def build_request(self, shop_said: str | None, customer_said: str, awaiting: str | None,
                      history: list[dict], contexts: list[str]) -> dict:
        """The body of one call: `{model, state, questions}`. `state` carries exactly `shop_said`
        (the default when None), `customer_said`, `awaiting` (the slot the bot waits for, or None) and
        `history` — passed through as given; Story 1.3 masks it before it gets here. The intent
        question's options are the intents in scope plus `none`."""
        crit = {it["id"]: it["description"] for it in self.in_scope(contexts)}
        crit[self.fallback["id"]] = self.fallback["description"]
        qs = {"intent": {"type": "choice", "instructions": self.intent_question, "criteria": crit}}
        qs.update(self.questions(contexts))
        return {"model": self.model,
                "state": {"shop_said": shop_said or self.default_shop_said,
                          "customer_said": customer_said,
                          "awaiting": awaiting,
                          "history": list(history)},
                "questions": qs}


def load(catalogue: Path = CATALOGUE, data: Path = DATA) -> Flow:
    """Read the flow file and the product table once. Raises like `open`/`json` would; prints nothing."""
    with open(catalogue, encoding="utf-8") as f:
        cat = json.load(f)
    with open(data / "product.csv", encoding="utf-8", newline="") as f:
        products = {r["sku"]: dict(r) for r in csv.DictReader(f)}
    return Flow(intents=cat["intents"], contexts=cat["contexts"], entities=cat["entities"],
                events=cat["events"], fallback=cat["fallback"],
                default_shop_said=cat["default_shop_said"], intent_question=cat["intent_question"],
                products=products)
