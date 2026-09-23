"""The catalogue's test set and its scoring — lifted from `tests/rehearsal/replay_s3.py` (Story 1.6),
which lifted them from Spike S-3's `run_intents.py` (`load_cases`, `scored_entities`, the strict /
`accept_intents` rule). Story 2.1 moves them here so the speed test (`app/speed.py`) and the
rehearsal script score the same way; the code is moved, not rewritten.

A case is one labelled message: its text, the intent it should get (`accept_intents` widens that for
the hard cases), the contexts live when it is typed and the `shop_said` before it. `build_session` is
the session the loop would hold when that case is typed — Story 2.6: with the order a shop would be
holding at that point (`fill_order`), fictional, so the prepared reply is the one a real shop gives.
None of it reaches the request to Jev. Nothing here calls Jev or writes to disk.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app import flow as flowmod, order as rules, turn
from app.flow import Flow
from app.session import Session

# the slot the loop leaves pending under each context (`app/turn.py` § lead / recommend_step)
SLOT_OF = {"ask_brew": "brew", "ask_roast": "roast", "ask_quantity": "quantity",
           "offer_promo": "promotion", "ask_payment": "payment", "ask_delivery": "delivery",
           "confirm_order": "confirmation"}


# --- the cases (S-3's load_cases, lifted)

def load_cases(cat: dict) -> list[dict]:
    out = []
    for it in cat["intents"]:
        for ex in it["examples"]:
            out.append({"text": ex["text"], "intent": it["id"], "group": it["group"],
                        "contexts": ex.get("contexts", []), "shop_said": ex.get("shop_said"),
                        "entities": ex.get("entities", {}), "kind": "example",
                        "accept_intents": None, "accept_entities": ex.get("accept_entities", {})})
    for ex in cat["fallback"]["examples"]:
        out.append({"text": ex["text"], "intent": "none", "group": "none", "contexts": [],
                    "shop_said": None, "entities": {}, "kind": "example",
                    "accept_intents": None, "accept_entities": {}})
    gmap = {it["id"]: it["group"] for it in cat["intents"]}
    for ex in cat["multi_slot_and_hard_cases"]:
        out.append({"text": ex["text"], "intent": ex["intent"], "group": gmap[ex["intent"]],
                    "contexts": ex.get("contexts", []), "shop_said": ex.get("shop_said"),
                    "entities": ex.get("entities", {}), "kind": "hard",
                    "accept_intents": ex.get("accept_intents"), "accept_entities": ex.get("accept_entities", {})})
    for i, c in enumerate(out):
        c["n"] = i + 1
    return out


def read_catalogue(path: Path = flowmod.CATALOGUE) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_session(case: dict, flow: Flow, *, filled: bool = True) -> Session:
    """The session the loop would hold when this case is typed: the case's contexts live, its
    `shop_said` the last (and only) bot bubble, the context's slot pending — and (Story 2.6, unless
    `filled` is False) the order the shop holds at that step, from `fill_order`."""
    s = Session.new(session_id=f"replay-{case['n']}", flow_version="replay",
                    now=datetime(2026, 9, 23, tzinfo=timezone.utc))
    for ctx in case["contexts"]:
        s.contexts[ctx] = {"expires_after_turn": flow.contexts[ctx]["lifespan"], "params": {}}
    msg_id = None
    if case["shop_said"]:
        msg_id = "m1"
        s.transcript.append({"who": "bot", "id": msg_id, "text": case["shop_said"], "buttons": [],
                             "variant": "plain", "response_id": None})
        s.last_bot_message = {"id": msg_id, "text": case["shop_said"], "text_for_jev": case["shop_said"]}
    for ctx in case["contexts"]:
        if ctx in SLOT_OF:
            s.pending_prompt = {"slot": SLOT_OF[ctx], "context": ctx, "params": {}, "message_id": msg_id}
            break
    if filled:
        fill_order(s, case, flow)
    return s


# --- the order a case's session holds (Story 2.6, F-23)
#
# A case typed mid-order (a quantity, a promotion, the payment, the address, the read-back) or about
# the order (change, cancel, view) is answered by `turn.act` from the session's order form. Without an
# order the loop leads to the brew question; with the order the shop would hold at that step, the
# reply is the next step — the read-back, the order code. Only the order form, `focus_sku`,
# `promos_offered` and the live context's params are written: none of them is in the request to Jev
# (`turn.build_request` reads `last_bot_message`, the pending slot, the transcript and the context
# names). The order follows the case's `shop_said` where it names one (the read-back's lines, the
# offered promotion, the offered product); otherwise it is the House Blend, two bags. Fictional.

STAPLE = ("KBN-001", 2)                      # เฮาส์เบลนด์ × 2 — the shop's staple, as the read-back cases show it
PROMO_LINE = {"PROMO-01": ("DH-002", 2), "PROMO-02": ("DH-001", 1),   # a first line `fit_promo` offers
              "PROMO-03": ("KBN-001", 2), "PROMO-04": ("KBN-003", 1)}  # exactly this promotion for
PAYMENT = "transfer"                         # the read-back cases' totals carry no COD fee
ORDER_ABOUT = ("change_order", "cancel_order", "view_order")          # context-free, but about the order
FILLED_CONTEXTS = ("ask_quantity", "offer_promo", "ask_payment", "ask_delivery", "confirm_order", "offer_product")


def readback_lines(shop_said: str | None, flow: Flow) -> list[tuple[str, int]]:
    """The lines a read-back names: `<spoken_name> × <n> ถุง`, in the table's order."""
    out = []
    for sku, p in flow.products.items():
        m = re.search(re.escape(p["spoken_name"]) + r" × (\d+) ถุง", shop_said or "")
        if m:
            out.append((sku, int(m.group(1))))
    return out


def offered_product(shop_said: str | None, flow: Flow) -> str | None:
    """The product a product card offers: its text opens with `<spoken_name> — `."""
    return next((sku for sku, p in flow.products.items() if (shop_said or "").startswith(p["spoken_name"] + " — ")), None)


def offered_promo(shop_said: str | None) -> str | None:
    """The promotion an offer names: the offer's text before `สนใจไหมคะ` opens that promotion's detail."""
    head = (shop_said or "").split(" สนใจไหมคะ")[0].strip()
    return next((pid for pid, p in rules.promotions().items() if head and p["detail"].startswith(head)), None)


def _line(s: Session, sku: str, qty: int | None) -> None:
    rules.line_for(s.order, sku)["qty"] = qty
    s.focus_sku = sku


def _params(s: Session, ctx: str, params: dict) -> None:
    s.contexts[ctx]["params"] = dict(params)
    if (s.pending_prompt or {}).get("context") == ctx:
        s.pending_prompt["params"] = dict(params)


def _lines_then_promo_declined(s: Session, lines: list[tuple[str, int]]) -> None:
    for sku, qty in lines:
        _line(s, sku, qty)
    offer = rules.fit_promo(s.order, [])
    if offer is not None:                    # offered once already, and declined: the loop moves on
        s.promos_offered.append(offer["promo_id"])


def fill_order(s: Session, case: dict, flow: Flow) -> None:
    """Write into `s` the fictional order the shop holds when this case is typed (see above)."""
    ctx = set(case["contexts"])
    said = case["shop_said"]
    if "confirm_order" in ctx:               # the read-back: lines as read, payment and address given
        _lines_then_promo_declined(s, readback_lines(said, flow) or [STAPLE])
        s.order["payment"] = PAYMENT
        s.order["delivery_text"] = rules.SAMPLE_DETAILS
        _params(s, "confirm_order", {"order_hash": rules.order_hash(s.order)})
    elif "ask_delivery" in ctx:              # asked for the address: lines and payment given
        _lines_then_promo_declined(s, [STAPLE])
        s.order["payment"] = PAYMENT
    elif "ask_payment" in ctx:               # asked how to pay: the lines given, the promotion passed
        _lines_then_promo_declined(s, [STAPLE])
    elif "offer_promo" in ctx:               # a promotion offered for the line it fits
        promo = offered_promo(said)
        if promo in PROMO_LINE:
            _line(s, *PROMO_LINE[promo])
            offer = rules.fit_promo(s.order, [])
            s.promos_offered.append(promo)
            _params(s, "offer_promo", {"promo_id": offer["promo_id"], "effect": offer["effect"]})
    elif "ask_quantity" in ctx:              # a product taken, its bags not yet said
        _line(s, STAPLE[0], None)
        _params(s, "ask_quantity", {"sku": STAPLE[0]})
    elif "offer_product" in ctx:             # a product card shown: that product in focus, no line yet
        sku = offered_product(said, flow)
        if sku:
            s.focus_sku = sku
            _params(s, "offer_product", {"sku": sku})
    elif not ctx and case["intent"] in ORDER_ABOUT:
        _lines_then_promo_declined(s, [STAPLE])   # an order in progress, at the payment step


# --- scoring (S-3's rules, lifted)

def scored_entities(cat: dict, case: dict) -> dict:
    exp = {}
    for name, e in cat["entities"].items():
        if e.get("only_in_context") and e["only_in_context"] not in case["contexts"]:
            continue
        if name in case["entities"]:
            exp[name] = case["entities"][name]
            continue
        if name in ("roast", "brew") and "product" in case["entities"]:
            continue
        if (name == "roast" and case["intent"] == "faq.roast_levels") or (name == "brew" and case["intent"] == "faq.grinding"):
            continue
        if name in case.get("accept_entities", {}):
            continue
        exp[name] = "not_mentioned"
    return exp


def loop_intent(v: turn.Verdict) -> str | None:
    """What the bot acts on: the matched intent, `none` for a fallback, None when no answer came."""
    if v.outcome == "matched":
        return v.intent
    if v.outcome == "fallback":
        return "none"
    return None


def score(cat: dict, case: dict, v: turn.Verdict) -> dict:
    a = v.answer
    accept = case.get("accept_intents") or [case["intent"]]
    got_loop, got_jev = loop_intent(v), (a.intent if a else None)
    exp_e = scored_entities(cat, case)
    ent = dict(a.entities) if a else {}
    e_rows = [{"entity": k, "expected": x, "got": ent.get(k), "ok": ent.get(k) == x} for k, x in exp_e.items()]
    return {"n": case["n"], "text": case["text"], "intent": case["intent"], "kind": case["kind"],
            "contexts": case["contexts"], "awaiting": v.request["state"].get("awaiting"),
            "history_len": len(v.request["state"].get("history") or []),
            "outcome": v.outcome, "loop": got_loop, "jev": got_jev, "by_state": v.by_state,
            "confidence": a.confidence if a else None,
            "loop_ok": got_loop in accept, "loop_strict": got_loop == case["intent"],
            "jev_ok": got_jev in accept, "jev_strict": got_jev == case["intent"],
            "entities": e_rows, "ms": a.ms if a else 0, "error": a.error if a else None,
            "cost_usd": a.cost_usd if a else 0.0}


def pct(values: list, p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)
