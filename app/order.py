"""The order form's arithmetic and rules — pure functions over `session.order` and the tables.

Ported from the prototype's `shared.js` (`totals`, `fitPromo`, `applyPromo`, `readback`, `REC`) and
the flow page's two tables (§ The recommendation table, § The promotion rules). Nothing here reads a
session, calls Jev or knows the key; Story 1.6's rehearsal can test these without a server. Prices
come from the product table, promotion texts from the promotion table, the FAQ answers from the FAQ
table — the app's byte-identical copies under `app/data/`.
"""
from __future__ import annotations

import functools
import hashlib
import json
from datetime import datetime

from app.flow import rows

SHIPPING = 100                 # baht, waived at FREE_SHIPPING_BAGS
FREE_SHIPPING_BAGS = 5
COD_FEE = 30
PROMO02_DISCOUNT = 80          # Geisha + Natural Anaerobic
PROMO03_PER_BAG = 30           # House Blend at 6+

# the sample delivery details — the prototype's constant; fictional, never a real person
SAMPLE_DETAILS = "สมชาย ใจดี 123/4 ซอยสุขุมวิท 50 คลองเตย กรุงเทพ 10110 โทร 081-000-0000"

PROMOS_LISTED = ("PROMO-01", "PROMO-02", "PROMO-03", "PROMO-04")     # PROMO-05 is not used

FAQ_BY_INTENT = {"faq.shipping_fee": "FAQ-01", "faq.payment_methods": "FAQ-02", "faq.roast_levels": "FAQ-03",
                 "faq.storage": "FAQ-04", "faq.delivery_time": "FAQ-05", "faq.grinding": "FAQ-06",
                 "faq.minimum_order": "FAQ-07", "faq.freshness": "FAQ-08"}
GRINDING_TAIL = "กาแฟดีต้องคู่ grind ที่ตรงเสมอค่ะ"

# conversation-flow § The recommendation table: brew → roast → the two skus, story first
RECOMMEND = {
    "espresso_milk": {"light": ["DH-002", "MM-002"], "medium": ["KBN-001", "DH-002"], "dark": ["KBN-002", "MM-004"], "any": ["KBN-001", "DH-002"]},
    "filter": {"light": ["DH-001", "MM-001"], "medium": ["MM-002", "DH-002"], "dark": ["MM-004", "KBN-002"], "any": ["MM-001", "MM-002"]},
    "cold_brew": {"light": ["DH-003", "MM-003"], "medium": ["MM-003", "DH-003"], "dark": ["MM-003", "MM-004"], "any": ["MM-003", "DH-003"]},
    "any": {"light": ["DH-001", "MM-001"], "medium": ["KBN-001", "DH-002"], "dark": ["KBN-002", "MM-004"], "any": ["KBN-001", "DH-002"]},
}
DECAF = ["KBN-003"]


# --- the tables

@functools.lru_cache(maxsize=None)
def promotions() -> dict[str, dict]:
    return {r["id"]: dict(r) for r in rows("promotion.csv")}


@functools.lru_cache(maxsize=None)
def faqs() -> dict[str, dict]:
    return {r["id"]: dict(r) for r in rows("faq.csv")}


def faq_answer(intent: str) -> str:
    """The CSV answer for a `faq.*` intent; grinding carries the SOP's signature line."""
    answer = faqs()[FAQ_BY_INTENT[intent]]["answer"]
    return f"{answer} {GRINDING_TAIL}" if intent == "faq.grinding" else answer


def promotion_list() -> str:
    """`ask_promotion`: the four promotions as the prototype listed them; PROMO-05 never."""
    lines = [f"📍 {promotions()[pid]['title']}: {promotions()[pid]['detail']}" for pid in PROMOS_LISTED]
    return "ตอนนี้มีโปรตามนี้ค่ะ — " + "\n".join(lines)


# --- lines

def line_for(order: dict, sku: str, added_by: str = "customer") -> dict:
    """Find the line for `sku`, or add it with `qty` null — a line is never duplicated."""
    for line in order["lines"]:
        if line["sku"] == sku:
            return line
    line = {"sku": sku, "qty": None, "added_by": added_by}
    order["lines"].append(line)
    return line


def change_target(order: dict, sku: str | None, focus_sku: str | None) -> dict | None:
    """The focus rule (contract § change_order, Delta 2026-09-22): the named line if it is in the
    order; else the line in focus; else the first line. Never adds a line; None on an empty order."""
    by_sku = {line["sku"]: line for line in order["lines"]}
    if sku in by_sku:
        return by_sku[sku]
    if focus_sku in by_sku:
        return by_sku[focus_sku]
    return order["lines"][0] if order["lines"] else None


def bags(order: dict) -> int:
    return sum(int(line.get("qty") or 0) for line in order["lines"])


# --- money

def totals(order: dict, products: dict) -> dict:
    """`{sub, discount, shipping, cod, total, bags}` — the prototype's `totals()`."""
    sub, n = 0, 0
    for line in order["lines"]:
        qty = int(line.get("qty") or 0)
        sub += int(products[line["sku"]]["price"]) * qty
        n += qty
    discount = 0
    promo = order.get("promo_applied")
    if promo == "PROMO-02":
        discount = PROMO02_DISCOUNT
    elif promo == "PROMO-03":
        kbn = next((l for l in order["lines"] if l["sku"] == "KBN-001"), None)
        discount = PROMO03_PER_BAG * int((kbn or {}).get("qty") or 0)
    shipping = 0 if n >= FREE_SHIPPING_BAGS else SHIPPING
    cod = COD_FEE if order.get("payment") == "cod" else 0
    return {"sub": sub, "discount": discount, "shipping": shipping, "cod": cod,
            "total": sub - discount + shipping + cod, "bags": n}


def baht(n: int) -> str:
    return f"{n:,} บาท"


# --- promotions

def fit_promo(order: dict, promos_offered: list) -> dict | None:
    """The first rule that fits the first line (conversation-flow § The promotion rules, in order),
    unless it was offered already — then nothing, the bot moves on. `effect` is exactly what
    `apply_promo` will do, so "สนใจค่ะ" applies what was offered, not whatever fits later."""
    if not order["lines"]:
        return None
    line = order["lines"][0]
    sku, qty = line["sku"], int(line.get("qty") or 0)
    if sku == "KBN-001" and qty < 6:
        offer = {"promo_id": "PROMO-03", "take_label": "เพิ่มเป็น 6 ถุง", "effect": {"set_qty": 6, "sku": sku}}
    elif sku in ("DH-001", "DH-003"):
        other = "DH-003" if sku == "DH-001" else "DH-001"
        offer = {"promo_id": "PROMO-02", "take_label": "เพิ่ม" + ("เนเชอรัล แอนแอโรบิก" if other == "DH-003" else "เกอิชา"),
                 "effect": {"add_line": other}}
    elif sku == "KBN-003" and qty < 2:
        offer = {"promo_id": "PROMO-04", "take_label": "เพิ่มเป็น 2 ถุง", "effect": {"set_qty": 2, "sku": sku}}
    elif qty < 5:
        offer = {"promo_id": "PROMO-01", "take_label": "เพิ่มเป็น 5 ถุง", "effect": {"set_qty": 5, "sku": sku}}
    else:
        return None
    return None if offer["promo_id"] in promos_offered else offer


def offer_text(promo_id: str) -> str:
    return f"{promotions()[promo_id]['detail']} สนใจไหมคะ? ไม่ urgent น้า ลองดูก่อนได้"


def apply_promo(order: dict, promo_id: str, effect: dict) -> list[dict]:
    """Apply exactly the offered effect; returns the `applied` entries for the log."""
    applied = []
    if effect.get("set_qty"):
        target = change_target(order, effect.get("sku"), None)
        if target is not None:
            target["qty"] = int(effect["set_qty"])
            applied.append({"set": f"lines[{target['sku']}].qty", "to": target["qty"], "product_from": promo_id})
    if effect.get("add_line"):
        line = line_for(order, effect["add_line"], added_by=promo_id)
        if line["qty"] is None:
            line["qty"] = 1
        applied.append({"set": f"lines[{line['sku']}]", "to": line["qty"], "product_from": promo_id})
    order["promo_applied"] = promo_id
    applied.append({"set": "promo_applied", "to": promo_id})
    return applied


def still_fits(order: dict, promo_id: str) -> bool:
    qty = {line["sku"]: int(line.get("qty") or 0) for line in order["lines"]}
    if promo_id == "PROMO-03":
        return qty.get("KBN-001", 0) >= 6
    if promo_id == "PROMO-02":
        return qty.get("DH-001", 0) >= 1 and qty.get("DH-003", 0) >= 1
    if promo_id == "PROMO-04":
        return qty.get("KBN-003", 0) >= 2
    if promo_id == "PROMO-01":
        return bags(order) >= 5
    return False


def recheck_promo(order: dict) -> str | None:
    """Contract § promo_applied: re-checked whenever `lines` change — removed when the order no
    longer qualifies. Returns the removed promotion's id so the bot can say so, else None."""
    promo = order.get("promo_applied")
    if promo and not still_fits(order, promo):
        order["promo_applied"] = None
        return promo
    return None


# --- the read-back, the hash, the code

def order_hash(order: dict) -> str:
    """A hash of lines, promotion, payment and delivery as read back — what `confirm_order` carries."""
    key = {"lines": [[l["sku"], l.get("qty")] for l in order["lines"]], "promo": order.get("promo_applied"),
           "payment": order.get("payment"), "delivery": order.get("delivery_text")}
    return hashlib.sha256(json.dumps(key, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def order_code(turn_no: int, now: datetime) -> str:
    """`BEAN-YYMM-####` — the prototype's shape, the turn number as the serial."""
    return f"BEAN-{now:%y%m}-{turn_no % 10000:04d}"


READBACK_LEAD = "สรุปออเดอร์ค่ะ"
READBACK_ASK = "รบกวนคุณพี่ตรวจรายการอีกครั้ง แล้วยืนยันให้แอดน้า 🙏🏻"


def readback_data(order: dict, products: dict, promos: dict | None = None, *, ask: bool = True) -> dict:
    """What the page renders as the `readback` grid: `rows` of `[label, amount_text]`, the `total`,
    the `delivery_text` (the customer's own — shown to them, masked everywhere else), the lead-in
    and the tail. With `ask`, the tail carries the address and the confirm request."""
    promos = promos if promos is not None else promotions()
    t = totals(order, products)
    rws = []
    for line in order["lines"]:
        p = products[line["sku"]]
        qty = int(line.get("qty") or 0)
        rws.append([f"{p['spoken_name']} × {qty} ถุง", baht(int(p["price"]) * qty)])
    if t["discount"]:
        rws.append([f"ส่วนลด {promos[order['promo_applied']]['title']}", f"−{t['discount']} บาท"])
    rws.append(["ค่าส่ง", baht(t["shipping"]) if t["shipping"] else "ฟรี"])
    if t["cod"]:
        rws.append(["ค่าบริการเก็บเงินปลายทาง", baht(t["cod"])])
    rws.append(["รวม", baht(t["total"])])
    delivery = order.get("delivery_text") if ask else None
    tail = f"จัดส่งที่: {delivery}\n{READBACK_ASK}" if ask and delivery else (READBACK_ASK if ask else "")
    return {"rows": rws, "total": t["total"], "delivery_text": delivery, "lead": READBACK_LEAD, "tail": tail}


def readback_text(data: dict) -> str:
    """The same read-back as one text — the bubble's `text`, what history and `shop_said` carry."""
    body = "\n".join(f"{label} — {amount}" if not label.startswith(("ค่าส่ง", "ค่าบริการ", "รวม", "ส่วนลด")) else f"{label} {amount}"
                     for label, amount in data["rows"])
    return "\n".join(x for x in (data["lead"], body, data["tail"]) if x)


# --- the recommendation

def recommend(brew: str | None, roast: str | None) -> list[str]:
    """The pair from the table; decaf overrides everything; an unknown value reads as *not said*."""
    if roast == "decaf":
        return list(DECAF)
    by_roast = RECOMMEND.get(brew or "any", RECOMMEND["any"])
    return list(by_roast.get(roast or "any", by_roast["any"]))
