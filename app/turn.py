"""The turn loop — contract `session-state.md` § What is sent, § State before the classifier,
§ Committing a turn, § Who reads and writes what. The only caller of `jev.ask` for a customer
message; the only module that changes a `Session`.

Story 1.3 built the loop with a minimal act; Story 1.4 fills `lead()` (the prompt for the first
empty slot, in the SOP's order) and the order-form writers — every reply from the catalogue, the
tables (`app/order.py`) and the prototype's texts, in Beanly's voice. Nothing here knows the key:
the client carries it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app import jev, order as rules
from app.flow import Flow
from app.session import Session, Store, empty_order, parse_stamp

THRESHOLD = 0.45                                 # conversation-flow Delta 2026-09-22: เอาค่ะ at 0.49 matches
HISTORY_TURNS = 4
MASK_FOR_JEV = "[รายละเอียดจัดส่ง]"              # what Jev sees instead of the delivery details
MASK_FOR_LOG = "[delivery details]"              # what the log stores for the give_delivery_details turn
NOT_MENTIONED = "not_mentioned"
DELIVERY_SLOT = "delivery"                       # the pending slot `ask_delivery` sets; it has no entity


# --- masking

def mask(text: str | None, delivery_text: str | None) -> str:
    """`text_for_jev`: the text with the typed delivery details replaced by the placeholder."""
    if not text:
        return ""
    if delivery_text and delivery_text.strip() and delivery_text.strip() in text:
        return text.replace(delivery_text.strip(), MASK_FOR_JEV)
    return text


def history(session: Session) -> list[dict]:
    """The last four turns as `[{who, text}]`, bot and customer, from the transcript — a turn is a
    customer bubble and the bot's reply. Delivery details never appear: a masked customer bubble
    is the placeholder and every bot bubble is masked against `delivery_text`."""
    delivery = session.order.get("delivery_text")
    start, seen = 0, 0
    for i in range(len(session.transcript) - 1, -1, -1):
        if session.transcript[i].get("who") == "you":
            seen += 1
            if seen == HISTORY_TURNS:
                start = i
                break
    out = []
    for b in session.transcript[start:]:
        if b.get("who") == "you":
            out.append({"who": "customer", "text": MASK_FOR_JEV if b.get("masked") else b.get("text", "")})
        else:
            out.append({"who": "bot", "text": mask(b.get("text", ""), delivery)})
    return out


# --- the classifier, with the state applied before it

@dataclass
class Verdict:
    """What one typed message came to, before anything is applied."""
    outcome: str                                  # matched | fallback | model_failed | cap_reached
    request: dict
    answer: jev.JevAnswer | None = None           # None only for cap_reached — no call was made
    intent: str | None = None                     # the intent the bot acts on (may differ from Jev's)
    entities: dict = field(default_factory=dict)
    by_state: bool = False                        # the pending slot made it `inform`
    sku: str | None = None                        # the product this turn is about, resolved
    product_from: str | None = None               # jev | context:<name> | focus_sku | None


def build_request(session: Session, text: str, flow: Flow) -> dict:
    last = session.last_bot_message or {}
    pending = session.pending_prompt or {}
    return flow.build_request(last.get("text_for_jev") or None, text, pending.get("slot") or None,
                              history(session), session.live_contexts())


def resolve_product(session: Session, entities: dict) -> tuple[str | None, str | None]:
    """Contract § State before the classifier, the table: Jev's product; else a live context's
    `sku`; else `focus_sku`; else nothing."""
    product = entities.get("product")
    if product and product != NOT_MENTIONED:
        return product, "jev"
    for name, ctx in session.contexts.items():
        sku = (ctx.get("params") or {}).get("sku")
        if sku:
            return sku, f"context:{name}"
    if session.focus_sku:
        return session.focus_sku, "focus_sku"
    return None, None


def classify(session: Session, text: str, flow: Flow, client: jev.Client, *,
             spend_cap_usd: float | None = None, clock=jev.now_utc) -> Verdict:
    """Build the request from the session, check the cap, call Jev, then decide: the pending
    slot first (state before the classifier), then the 0.45 threshold and `none`."""
    request = build_request(session, text, flow)
    if spend_cap_usd is not None and client.spent_usd >= spend_cap_usd:
        return Verdict("cap_reached", request)
    answer = jev.ask(None, request, client=client, clock=clock)
    if answer.error is not None:
        return Verdict("model_failed", request, answer)
    entities = dict(answer.entities)
    v = Verdict("fallback", request, answer, entities=entities)
    slot = (session.pending_prompt or {}).get("slot")
    if slot and entities.get(slot) not in (None, NOT_MENTIONED):
        v.outcome, v.intent, v.by_state = "matched", "inform", True
    else:
        in_scope = {it["id"] for it in flow.in_scope(session.live_contexts())}
        confident = (answer.confidence or 0.0) >= THRESHOLD
        if answer.intent in in_scope and confident:
            v.outcome, v.intent = "matched", answer.intent
        elif slot == DELIVERY_SLOT:
            # F-8 (Story 1.5): the customer was asked for the delivery details and Jev matched nothing
            # else — the typed text is those details, by state (the slot has no entity to fill)
            v.outcome, v.intent, v.by_state = "matched", "give_delivery_details", True
    if v.outcome == "matched":
        v.sku, v.product_from = resolve_product(session, entities)
    return v


# --- the catalogue's text and buttons, as written

def strip_text(response: str) -> str:
    """The catalogue's `response` with `{…}` placeholders (nested) and `(…)` notes removed, a
    trailing `— then …` prose clause cut, whitespace collapsed."""
    out, depth = [], 0
    for ch in response:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    text = "".join(out)
    text = re.sub(r"\([^()]*\)", "", text)
    text = re.sub(r"\s*—\s*then\b.*$", "", text)
    text = re.sub(r"\s+", " ", text).strip(" —-")
    return text.strip()


def clause(response: str, marker: str) -> str:
    """The text of one `{<marker>: …}` clause of a response, or ''."""
    i = response.find("{" + marker + ":")
    if i < 0:
        return ""
    depth, start, j = 0, i + len(marker) + 2, i
    while j < len(response):
        if response[j] == "{":
            depth += 1
        elif response[j] == "}":
            depth -= 1
            if depth == 0:
                return re.sub(r"\s+", " ", response[start:j]).strip()
        j += 1
    return ""


def button(label: str, intent: str, params: dict | None = None) -> dict:
    return {"label": label, "intent": intent, "params": dict(params or {})}


def buttons_of(intent: dict) -> list[dict]:
    """`"label→intent"` strings become buttons; a bare label fires the same intent; a
    parenthesised note is not a button."""
    out = []
    for b in intent.get("buttons", []):
        if b.startswith("("):
            continue
        if "→" in b:
            label, target = b.split("→", 1)
            out.append(button(label.strip(), target.strip()))
        else:
            out.append(button(b.strip(), intent["id"]))
    return out


def help_buttons(flow: Flow) -> list[dict]:
    return buttons_of(flow_intent(flow, "help"))


def flow_intent(flow: Flow, intent_id: str) -> dict:
    for it in flow.intents:
        if it["id"] == intent_id:
            return it
    raise KeyError(intent_id)


# --- a bot message

def say(session: Session, text: str, buttons: list[dict], *, variant: str = "plain",
        response_id: str | None = None, live: bool = True, readback: dict | None = None) -> dict:
    """Append a bot bubble `m<n>` to the transcript. With `live` (every committed reply) it becomes
    `last_bot_message` and its buttons the `live_buttons`; a miss's bubble leaves those alone.
    A read-back carries its grid as data in the optional `readback` field (Story 1.4's Delta)."""
    msg_id = f"m{len(session.transcript) + 1}"
    bubble = {"who": "bot", "id": msg_id, "text": text,
              "buttons": [button(b["label"], b["intent"], b.get("params")) for b in buttons],
              "variant": variant, "response_id": response_id}
    if readback is not None:
        bubble["readback"] = readback
    session.transcript.append(bubble)
    if live:
        session.last_bot_message = {"id": msg_id, "text": text,
                                    "text_for_jev": mask(text, session.order.get("delivery_text"))}
        session.live_buttons = [dict(b, message_id=msg_id) for b in bubble["buttons"]]
    return bubble


def current_message_id(session: Session) -> str | None:
    """The id of the latest bot bubble — the only one whose buttons a click may name."""
    for b in reversed(session.transcript):
        if b.get("who") == "bot":
            return b.get("id")
    return None


def welcome(session: Session, flow: Flow) -> dict:
    """`events.welcome`: the greet response and its buttons, no model call."""
    greet = flow_intent(flow, "greet")
    return say(session, strip_text(greet["response"]), buttons_of(greet), response_id="greet")


def new_session(store: Store, flow: Flow) -> Session:
    s = store.new()
    welcome(s, flow)
    store.commit(s)
    return s


def fill(template: str, values: dict) -> str:
    """`{name}`-style placeholders that the product row can fill, then `strip_text` for the rest.
    The values are put in after the strip so a value's own parentheses survive."""
    tokens = {}
    for k, v in values.items():
        if "{" + k + "}" in template:
            tokens[f"\x00{k}\x00"] = str(v)
            template = template.replace("{" + k + "}", f"\x00{k}\x00")
    text = strip_text(template)
    for tok, v in tokens.items():
        text = text.replace(tok, v)
    return text


# --- the act: what a matched intent does here (contract § Who reads and writes what)

UNREACHABLE = "ขอโทษด้วยน้า ตอนนี้ติดต่อระบบไม่ได้ค่ะ กดเลือกจากด้านล่างได้เลยน้า"   # the could-not-reach line
WHICH_PRODUCT = "ตัวไหนคะ? พิมพ์ชื่อหรือเลือกจากรายการได้เลยน้า"                 # contract: "the bot asks which product"
ORDER_INTENTS = ("order_product", "inform", "change_order", "view_order", "affirm", "deny",
                 "give_delivery_details", "cancel_order")
SLOTS = ("quantity", "brew", "roast", "payment")
ROASTERS = {"ดอยหอม": "DH", "คั่วบ้านนา": "KBN", "เมล็ดเมือง": "MM"}
PAYMENT_WORDS = {"cod": "เก็บเงินปลายทาง", "transfer": "โอนเงิน"}
ROAST_WORDS = {"light": "คั่วอ่อน", "medium": "คั่วกลาง", "dark": "คั่วเข้ม", "decaf": "ไม่มีคาเฟอีน"}
BREW_WORDS = {"espresso_milk": "เอสเปรสโซ่และเมนูนม", "filter": "ดริป", "cold_brew": "โคลด์บรูว์"}

# the prototype's texts, as walked and approved (prototypes/assets/shared.js § act, § leadNext)
ASK_QUANTITY = "รับกี่ถุงดีคะ? สั่งครบ 5 ถุงส่งฟรีน้า"
ASK_PAYMENT = "ค่าส่ง {fee} ค่ะ ชำระแบบไหนสะดวกคะ? โอนผ่านบัญชีธนาคาร หรือเก็บเงินปลายทาง (มีค่าบริการเพิ่ม 30 บาท)"
ASK_DELIVERY = "รบกวนขอชื่อ ที่อยู่ และเบอร์โทรสำหรับจัดส่งค่ะ — เดโมนี้ไม่ส่งของจริง ใช้ข้อมูลสมมติได้เลยน้า"
PROMO_TAKEN = "ได้เลยค่ะ ใส่ให้แล้วนะคะ"
PROMO_DECLINED = "ได้เลยค่ะ เอาเท่าเดิมนะคะ"
PROMO_DROPPED = "โปร {title} ไม่เข้าเงื่อนไขแล้ว แอดเอาออกให้นะคะ"
PRODUCT_DECLINED = "ได้ค่ะ ลองดูตัวอื่นไหมคะ?"
CHANGE_WHAT = "ได้เลยค่ะ อยากแก้ส่วนไหนคะ? หรือจะคิดดูก่อนก็ได้น้า"
CHANGED = "ได้เลยค่ะ แก้ให้แล้วนะคะ"
NO_ORDER = "ตอนนี้ยังไม่มีรายการในออเดอร์ค่ะ"
CONFIRMED = "ขอบคุณคุณพี่มากค่ะ ☕ รหัสออเดอร์ {code} {how}"
CONFIRMED_TRANSFER = "โอนแล้วรบกวน reply slip ด้วยน้า — เดโมนี้ไม่มีบัญชีจริงค่ะ"
CONFIRMED_COD = "เตรียมชำระ {total} บาทตอนรับของน้า"
ALREADY_CONFIRMED = "ออเดอร์นี้ยืนยันแล้วค่ะ รหัส {code} — อยากสั่งเพิ่ม กดเริ่มใหม่ได้เลยน้า"
RECOMMEND_PAIR = "story bean ก่อนนะคะ — ตัวแรก {a_name}: {a_note} อีกตัว {b_name}: {b_note} สนใจตัวไหนคะ?"
RECOMMEND_ONE = "story bean ก่อนนะคะ — {a_name}: {a_note} สนใจตัวนี้ไหมคะ?"


def set_context(s: Session, flow: Flow, name: str, params: dict | None, turn_no_after: int) -> None:
    """`expires_after_turn` is absolute: the turn being committed plus the catalogue's lifespan."""
    lifespan = int(flow.contexts.get(name, {}).get("lifespan", 2))
    s.contexts[name] = {"expires_after_turn": turn_no_after + lifespan, "params": dict(params or {})}


def expire_contexts(s: Session) -> None:
    """Drop every context whose `expires_after_turn` has been reached — after the turn's own sets,
    so a context set this turn survives and one set two turns ago goes."""
    s.contexts = {n: c for n, c in s.contexts.items() if c.get("expires_after_turn", 0) > s.turn_no}


def ask(s: Session, flow: Flow, text: str, buttons: list[dict], *, slot: str, context: str,
        params: dict | None, turn_no_after: int, response_id: str, variant: str = "plain",
        readback: dict | None = None) -> dict:
    """A question of the bot's own: the bubble, its context (the catalogue's lifespan) and the
    `pending_prompt` the classifier and the resume step read."""
    bubble = say(s, text, buttons, variant=variant, response_id=response_id, readback=readback)
    set_context(s, flow, context, params, turn_no_after)
    s.pending_prompt = {"slot": slot, "context": context, "params": dict(params or {}), "message_id": bubble["id"]}
    return bubble


def option_buttons(flow: Flow, slot: str) -> list[dict]:
    """One button per short label (the entity's `labels`: label → option key) — one option each, and
    two labels may fill the same key. Jev never sees `labels`; it reads the long `options`. An entity
    without `labels` falls back to its option texts."""
    e = flow.entities[slot]
    labels = e.get("labels") or {text: key for key, text in e["options"].items()}
    return [button(label, "inform", {slot: key}) for label, key in labels.items()]


def recommend_step(s: Session, flow: Flow, turn_no_after: int) -> None:
    """Before a product: brew unknown → ask how they brew; roast unknown → ask the roast; both
    known → the pair from the table, story first, as `select_option` buttons + ดูตัวอื่น."""
    it = flow_intent(flow, "ask_recommendation")
    rec = s.order.get("recommend") or {}
    if rec.get("brew") is None:
        ask(s, flow, clause(it["response"], "if brew unknown"), option_buttons(flow, "brew"),
            slot="brew", context="ask_brew", params=None, turn_no_after=turn_no_after, response_id="ask_brew")
        return
    if rec.get("roast") is None:
        ask(s, flow, clause(it["response"], "else if roast unknown"), option_buttons(flow, "roast"),
            slot="roast", context="ask_roast", params=None, turn_no_after=turn_no_after, response_id="ask_roast")
        return
    skus = rules.recommend(rec.get("brew"), rec.get("roast"))
    rows = [flow.products[k] for k in skus]
    if len(rows) == 2:
        text = RECOMMEND_PAIR.format(a_name=rows[0]["spoken_name"], a_note=rows[0]["note"],
                                     b_name=rows[1]["spoken_name"], b_note=rows[1]["note"])
    else:
        text = RECOMMEND_ONE.format(a_name=rows[0]["spoken_name"], a_note=rows[0]["note"])
    buttons = [button(p["spoken_name"], "select_option", {"product": p["sku"]}) for p in rows]
    buttons.append(button("ดูตัวอื่น", "browse_catalog"))
    say(s, text, buttons, response_id="recommend")
    s.options_shown = list(skus)
    set_context(s, flow, "options_shown", {"skus": list(skus)}, turn_no_after)
    s.order["recommend"] = {"brew": None, "roast": None}          # cleared when a recommendation has been given
    s.pending_prompt = None


def lead(s: Session, flow: Flow, turn_no_after: int, *, recommend: bool = True) -> None:
    """`then: lead` — the prompt for the first empty slot, in the SOP's order: product (offer to
    recommend) · quantity · the promotion, once · payment · delivery · confirmation. A confirmed
    order is terminal: nothing is asked."""
    o = s.order
    if o.get("order_code"):
        return
    if not o["lines"]:
        if recommend:
            recommend_step(s, flow, turn_no_after)
        return
    empty = next((l for l in o["lines"] if l.get("qty") is None), None)
    if empty is not None:
        ask(s, flow, ASK_QUANTITY, [button(f"{n} ถุง", "inform", {"quantity": str(n)}) for n in (1, 2, 3, 5)],
            slot="quantity", context="ask_quantity", params={"sku": empty["sku"]}, turn_no_after=turn_no_after,
            response_id="ask_quantity")
        return
    offer = rules.fit_promo(o, s.promos_offered)
    if offer is not None:
        s.promos_offered.append(offer["promo_id"])
        params = {"promo_id": offer["promo_id"], "effect": offer["effect"]}
        ask(s, flow, rules.offer_text(offer["promo_id"]),
            [button(offer["take_label"], "affirm"), button("ไม่เป็นไร เอาเท่าเดิม", "deny")],
            slot="promotion", context="offer_promo", params=params, turn_no_after=turn_no_after, response_id="promo.offer")
        return
    if not o.get("payment"):
        shipping = rules.totals(o, flow.products)["shipping"]
        ask(s, flow, ASK_PAYMENT.format(fee="ฟรี" if shipping == 0 else f"{shipping} บาท"),
            [button("โอนผ่านธนาคาร", "inform", {"payment": "transfer"}), button("เก็บเงินปลายทาง", "inform", {"payment": "cod"})],
            slot="payment", context="ask_payment", params=None, turn_no_after=turn_no_after, response_id="ask_payment")
        return
    if not o.get("delivery_text"):
        ask(s, flow, ASK_DELIVERY, [button("ใช้ข้อมูลตัวอย่าง", "give_delivery_details", {"sample": True})],
            slot="delivery", context="ask_delivery", params=None, turn_no_after=turn_no_after, response_id="ask_delivery")
        return
    data = rules.readback_data(o, flow.products, ask=True)
    ask(s, flow, rules.readback_text(data), [button("ยืนยัน", "affirm"), button("ขอแก้ไข", "deny")],
        slot="confirmation", context="confirm_order", params={"order_hash": rules.order_hash(o)},
        turn_no_after=turn_no_after, response_id="confirm", variant="read-back", readback=data)


def resume(s: Session, flow: Flow, turn_no_after: int) -> None:
    """`then: resume` — after a prepared answer, ask the pending question again and re-arm its
    context. The asked bubble is said again as it was (its grid included): a FAQ writes nothing,
    so the question is still the right one — and a promotion is offered once, so `lead()` would
    not re-offer it."""
    p = s.pending_prompt
    if not p:
        return
    asked = next((b for b in s.transcript if b.get("who") == "bot" and b.get("id") == p.get("message_id")), None)
    if asked is None:
        return
    say(s, asked["text"], asked.get("buttons", []), variant=asked.get("variant", "plain"),
        response_id=f"resume:{p.get('slot')}", readback=asked.get("readback"))
    s.pending_prompt = dict(p, message_id=s.last_bot_message["id"])
    if p.get("context"):
        set_context(s, flow, p["context"], p.get("params"), turn_no_after)


def resume_or_lead(s: Session, flow: Flow, turn_no_after: int) -> None:
    """After a reply that wrote nothing (`view_order`, `ask_promotion`): the pending question again
    if there is one, else the lead — which, on an empty form, waits."""
    if s.pending_prompt:
        resume(s, flow, turn_no_after)
    else:
        lead(s, flow, turn_no_after, recommend=False)


def default_reply(s: Session, flow: Flow, response_id: str) -> dict:
    return say(s, flow.default_shop_said, help_buttons(flow), response_id=response_id)


def given(entities: dict, name: str) -> str | None:
    v = entities.get(name)
    return v if v and v != NOT_MENTIONED else None


def context_for(s: Session, *names: str) -> tuple[str | None, dict]:
    """The live context `affirm`/`deny` answers: the one the pending prompt names if it is among
    `names`, else the first of `names` that is live. Returns (name, params)."""
    p = s.pending_prompt or {}
    if p.get("context") in names and p["context"] in s.contexts:
        return p["context"], dict(s.contexts[p["context"]].get("params") or {})
    for name in names:
        if name in s.contexts:
            return name, dict(s.contexts[name].get("params") or {})
    return None, {}


def drop_context(s: Session, name: str) -> None:
    s.contexts.pop(name, None)
    if (s.pending_prompt or {}).get("context") == name:
        s.pending_prompt = None


def consume_pending(s: Session, entities: dict) -> None:
    """The slot the bot asked for has been filled: its question is answered, its context goes."""
    p = s.pending_prompt or {}
    if p.get("slot") and given(entities, p["slot"]) and p.get("context"):
        drop_context(s, p["context"])


def write_line_qty(s: Session, sku: str, qty: str, product_from: str | None, applied: list) -> None:
    line = rules.line_for(s.order, sku)
    line["qty"] = int(qty) if str(qty).isdigit() else 7          # `more` — the entity's "มากกว่า 6 ถุง"
    if s.focus_sku != sku:
        s.focus_sku = sku
    applied.append({"set": f"lines[{sku}].qty", "to": line["qty"], "product_from": product_from})


def write_payment(s: Session, payment: str, applied: list) -> None:
    s.order["payment"] = payment
    applied.append({"set": "payment", "to": payment})


def write_recommend(s: Session, entities: dict, applied: list) -> bool:
    wrote = False
    for slot in ("brew", "roast"):
        v = given(entities, slot)
        if v:
            s.order.setdefault("recommend", {"brew": None, "roast": None})[slot] = v
            applied.append({"set": f"recommend.{slot}", "to": v})
            wrote = True
    return wrote


def after_lines_changed(s: Session, applied: list) -> str | None:
    """Contract § promo_applied: re-check; when it no longer fits, remove it and say so."""
    dropped = rules.recheck_promo(s.order)
    if dropped:
        applied.append({"set": "promo_applied", "to": None, "was": dropped})
    return dropped


def product_card(s: Session, flow: Flow, sku: str, product_from: str | None, applied: list, response_id: str,
                 turn_no_after: int) -> None:
    it = flow_intent(flow, "product_info")
    say(s, fill(it["response"], flow.products[sku]), buttons_of(it), response_id=response_id)
    if s.focus_sku != sku:
        applied.append({"set": "focus_sku", "to": sku, "product_from": product_from})
    s.focus_sku = sku
    set_context(s, flow, "offer_product", {"sku": sku}, turn_no_after)


def act(s: Session, flow: Flow, intent: str, entities: dict, *, sku: str | None, product_from: str | None,
        turn_no_after: int, text: str = "", at: str = "") -> list[dict]:
    """Apply a matched intent to the copy: its writes, its reply, its contexts, its `then`.
    Returns `applied`. `start_over` is not handled here (it ends the session — see run_turn).
    `text` is the customer's message (a click's label) — read only by `give_delivery_details`
    (kept exactly as typed) and `browse_catalog` (a roaster's name); `at` stamps `confirmed_at`."""
    it = flow_intent(flow, intent)
    applied: list[dict] = []
    s.miss_count = 0
    o = s.order
    plain = strip_text(it["response"]) or it["response"]     # as written when nothing but notes is left
    buttons = buttons_of(it)

    if o.get("order_code") and intent in ORDER_INTENTS + ("select_option",):
        # terminal: the order is confirmed; nothing is written, only เริ่มใหม่ is live
        say(s, ALREADY_CONFIRMED.format(code=o["order_code"]), [button("เริ่มใหม่", "start_over")], response_id="done")
        return applied

    if intent in ("product_info", "ask_price"):
        if sku and sku in flow.products:
            template = it["response"]
            say(s, fill(template, flow.products[sku]), buttons, response_id=intent)
            if s.focus_sku != sku:
                applied.append({"set": "focus_sku", "to": sku, "product_from": product_from})
            s.focus_sku = sku
            set_context(s, flow, "offer_product", {"sku": sku}, turn_no_after)
        else:
            say(s, WHICH_PRODUCT, [button("ดูเมล็ดทั้งหมด", "browse_catalog")], response_id=intent)

    elif intent == "select_option":
        # a pick is checked against the list actually shown; a product the customer named is taken
        shown = list(s.options_shown or (s.contexts.get("options_shown", {}).get("params") or {}).get("skus") or [])
        if sku in flow.products and (sku in shown or product_from == "jev" or not shown):
            product_card(s, flow, sku, product_from if sku in shown or product_from == "jev" else "options_shown",
                         applied, intent, turn_no_after)
        else:
            opts = [button(flow.products[k]["spoken_name"], "select_option", {"product": k}) for k in shown if k in flow.products]
            say(s, WHICH_PRODUCT, opts or [button("ดูเมล็ดทั้งหมด", "browse_catalog")], response_id=intent)
            if shown:
                set_context(s, flow, "options_shown", {"skus": shown}, turn_no_after)

    elif intent == "ask_recommendation":
        write_recommend(s, entities, applied)
        recommend_step(s, flow, turn_no_after)

    elif intent == "inform":
        asked = (s.pending_prompt or {}).get("slot")
        consume_pending(s, entities)
        wrote_rec = write_recommend(s, entities, applied)
        qty, payment = given(entities, "quantity"), given(entities, "payment")
        if qty and sku:
            write_line_qty(s, sku, qty, product_from, applied)
            dropped = after_lines_changed(s, applied)
            if dropped:
                say(s, PROMO_DROPPED.format(title=rules.promotions()[dropped]["title"]), [], response_id="promo.dropped")
        if payment:
            write_payment(s, payment, applied)
        if wrote_rec or asked in ("brew", "roast"):
            recommend_step(s, flow, turn_no_after)
        elif qty and not sku:
            say(s, WHICH_PRODUCT, [button("ดูเมล็ดทั้งหมด", "browse_catalog")], response_id=intent)
        else:
            lead(s, flow, turn_no_after)

    elif intent == "order_product":
        qty, payment = given(entities, "quantity"), given(entities, "payment")
        consume_pending(s, entities)
        if sku and sku in flow.products:
            line = rules.line_for(o, sku)
            if qty:
                write_line_qty(s, sku, qty, product_from, applied)
            else:
                applied.append({"set": f"lines[{sku}]", "to": None, "product_from": product_from})
            s.focus_sku = sku
            after_lines_changed(s, applied)
            if payment:
                write_payment(s, payment, applied)
            p = flow.products[sku]
            echo = f"ได้เลยค่ะ {p['spoken_name']}" + (f" {line['qty']} ถุง" if line["qty"] else "") + \
                   (f" {PAYMENT_WORDS.get(payment, '')}" if payment else "") + " นะคะ"
            say(s, echo, [], response_id=intent)
            lead(s, flow, turn_no_after)
        else:
            # no product named or in focus: the bot leads to a recommendation
            if payment:
                write_payment(s, payment, applied)
            write_recommend(s, entities, applied)
            s.focus_sku = None
            recommend_step(s, flow, turn_no_after)

    elif intent == "affirm":
        name, params = context_for(s, "confirm_order", "offer_promo", "offer_product")
        if name == "offer_product" and params.get("sku") in flow.products:
            line = rules.line_for(o, params["sku"])
            s.focus_sku = params["sku"]
            applied.append({"set": f"lines[{params['sku']}]", "to": line["qty"], "product_from": "context:offer_product"})
            drop_context(s, "offer_product")
            lead(s, flow, turn_no_after)
        elif name == "offer_promo" and params.get("promo_id"):
            applied.extend(rules.apply_promo(o, params["promo_id"], params.get("effect") or {}))
            drop_context(s, "offer_promo")
            say(s, PROMO_TAKEN, [], response_id="promo.taken")
            lead(s, flow, turn_no_after)
        elif name == "confirm_order":
            if params.get("order_hash") == rules.order_hash(o):
                o["order_code"] = rules.order_code(turn_no_after, parse_stamp(at) if at else jev.now_utc())
                o["confirmed_at"] = at or jev.stamp(jev.now_utc())
                applied.append({"set": "order_code", "to": o["order_code"]})
                applied.append({"set": "confirmed_at", "to": o["confirmed_at"]})
                total = rules.totals(o, flow.products)["total"]
                how = CONFIRMED_TRANSFER if o.get("payment") == "transfer" else CONFIRMED_COD.format(total=f"{total:,}")
                say(s, CONFIRMED.format(code=o["order_code"], how=how), [button("เริ่มใหม่", "start_over")], response_id="done")
                s.contexts, s.pending_prompt = {}, None
            else:
                lead(s, flow, turn_no_after)             # the order changed since: read it back again
        else:
            say(s, "ได้เลยค่ะ", help_buttons(flow), response_id=intent)

    elif intent == "deny":
        name, params = context_for(s, "confirm_order", "offer_promo", "offer_product")
        if name == "offer_product":
            drop_context(s, "offer_product")
            say(s, PRODUCT_DECLINED, [button("ดูเมล็ดทั้งหมด", "browse_catalog"), button("ช่วยแนะนำหน่อย", "ask_recommendation")], response_id=intent)
        elif name == "offer_promo":
            drop_context(s, "offer_promo")
            say(s, PROMO_DECLINED, [], response_id="promo.declined")
            lead(s, flow, turn_no_after)
        elif name == "confirm_order":
            # the order stands, and so does the read-back's context: a typed ยืนยันค่ะ still confirms it
            say(s, CHANGE_WHAT, change_buttons(), response_id=intent)
            set_context(s, flow, "confirm_order", params, turn_no_after)
        else:
            say(s, "ได้ค่ะ", help_buttons(flow), response_id=intent)

    elif intent == "give_delivery_details":
        details = rules.SAMPLE_DETAILS if entities.get("sample") else (text or "").strip()
        if details:
            o["delivery_text"] = details
            applied.append({"set": "delivery_text", "to": "[kept as typed]" if not entities.get("sample") else "[sample]"})
            drop_context(s, "ask_delivery")
            lead(s, flow, turn_no_after)
        else:
            lead(s, flow, turn_no_after)

    elif intent == "change_order":
        qty, payment, field = given(entities, "quantity"), given(entities, "payment"), entities.get("field")
        target = rules.change_target(o, sku, s.focus_sku)
        if target is None:
            say(s, NO_ORDER, help_buttons(flow), response_id=intent)
        elif field == "quantity":
            say(s, "ได้เลยค่ะ", [], response_id=intent)
            ask(s, flow, ASK_QUANTITY, [button(f"{n} ถุง", "inform", {"quantity": str(n)}) for n in (1, 2, 3, 5)],
                slot="quantity", context="ask_quantity", params={"sku": target["sku"]}, turn_no_after=turn_no_after,
                response_id="ask_quantity")
        elif field == "payment":
            say(s, "ได้เลยค่ะ", [], response_id=intent)
            o["payment"] = None
            applied.append({"set": "payment", "to": None})
            lead(s, flow, turn_no_after)
        elif not (qty or payment or (sku and product_from == "jev")):
            say(s, CHANGE_WHAT, change_buttons(), response_id=intent)
        else:
            changed = False
            if sku and product_from == "jev" and sku != target["sku"] and sku in flow.products:
                # a new product for this line: replaced, not duplicated
                applied.append({"set": f"lines[{target['sku']}].sku", "to": sku, "product_from": "jev"})
                target["sku"], target["added_by"] = sku, "customer"
                changed = True
            if qty:
                target["qty"] = int(qty) if str(qty).isdigit() else 7
                applied.append({"set": f"lines[{target['sku']}].qty", "to": target["qty"],
                                "product_from": "jev" if sku == target["sku"] and product_from == "jev" else "focus_sku"})
                changed = True
            s.focus_sku = target["sku"]
            if payment:
                write_payment(s, payment, applied)
            dropped = after_lines_changed(s, applied) if changed else None
            say(s, CHANGED + (" " + PROMO_DROPPED.format(title=rules.promotions()[dropped]["title"]) if dropped else ""),
                [], response_id=intent)
            lead(s, flow, turn_no_after)

    elif intent == "cancel_order":
        s.order = empty_order()
        s.contexts, s.focus_sku, s.pending_prompt, s.promos_offered, s.options_shown = {}, None, None, [], []
        applied.append({"set": "order", "to": "cleared"})
        say(s, plain, buttons, response_id=intent)

    elif intent == "view_order":
        if o["lines"]:
            data = rules.readback_data(o, flow.products, ask=False)
            say(s, rules.readback_text(data), [], variant="read-back", response_id=intent, readback=data)
        else:
            say(s, NO_ORDER, help_buttons(flow), response_id=intent)
        resume_or_lead(s, flow, turn_no_after)

    elif intent == "browse_catalog":
        code = next((c for name, c in ROASTERS.items() if name in (text or "")), None)
        if code:
            listed = [p for k, p in flow.products.items() if k.startswith(code + "-")]
            name = next(n for n, c in ROASTERS.items() if c == code)
            lines = [f"📍 {p['spoken_name']}: {p['note']} — {p['price']} บาท" for p in listed]
            say(s, f"ของ{name}มี {len(listed)} ตัวค่ะ\n" + "\n".join(lines) + "\nสนใจตัวไหนคะ?",
                [button(p["spoken_name"], "select_option", {"product": p["sku"]}) for p in listed], response_id=intent)
            s.options_shown = [p["sku"] for p in listed]
            set_context(s, flow, "options_shown", {"skus": s.options_shown}, turn_no_after)
        elif skus := rules.matching(flow.products, given(entities, "roast"), given(entities, "brew")):
            # "{if a roast or brew was given: only the matching products, as a list}"
            roast, brew = given(entities, "roast"), given(entities, "brew")
            write_recommend(s, entities, applied)
            what = "ตัว" + (ROAST_WORDS.get(roast, "") if roast else "") + (f"ที่เหมาะกับ{BREW_WORDS[brew]}" if brew in BREW_WORDS else "")
            lines = [f"📍 {flow.products[k]['spoken_name']}: {flow.products[k]['note']} — {flow.products[k]['price']} บาท" for k in skus]
            if len(skus) <= 4:          # sets: options_shown when four or fewer products are listed
                say(s, f"{what}มี {len(skus)} ตัวค่ะ\n" + "\n".join(lines) + "\nสนใจตัวไหนคะ?",
                    [button(flow.products[k]["spoken_name"], "select_option", {"product": k}) for k in skus], response_id=intent)
                s.options_shown = list(skus)
                set_context(s, flow, "options_shown", {"skus": s.options_shown}, turn_no_after)
            else:
                say(s, f"{what}มี {len(skus)} ตัวค่ะ\n" + "\n".join(lines) + "\nพิมพ์ชื่อตัวที่สนใจมาได้เลยน้า",
                    buttons, response_id=intent)
        else:
            say(s, plain, buttons, response_id=intent)

    elif intent == "ask_promotion":
        say(s, rules.promotion_list(), buttons, response_id=intent)
        resume_or_lead(s, flow, turn_no_after)

    elif intent.startswith("faq."):
        say(s, rules.faq_answer(intent), buttons, response_id=intent)
        resume(s, flow, turn_no_after)

    else:   # greet · help · thanks_bye
        say(s, plain, buttons, response_id=intent)

    return applied


def change_buttons() -> list[dict]:
    return [button("เปลี่ยนสินค้า", "browse_catalog"), button("เปลี่ยนจำนวน", "change_order", {"field": "quantity"}),
            button("เปลี่ยนวิธีชำระ", "change_order", {"field": "payment"})]


# --- the turn (contract § Committing a turn)

class TurnError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def you_bubble(text: str, kind: str, masked: bool = False) -> dict:
    return {"who": "you", "text": text, "kind": kind, "masked": masked}


def _result(s: Session, outcome: str, *, you: dict | None, bot: list, entry: dict | None, raw: dict | None,
            model_status: str = "live", ended: bool = False) -> dict:
    return {"session_id": s.session_id, "turn_no": s.turn_no, "outcome": outcome, "you": you, "bot": list(bot),
            "log_entry": entry, "raw": raw, "model_status": model_status, "ended": ended}


def run_turn(store: Store, flow: Flow, client: jev.Client, session_id: str, turn_id: str, *,
             text: str | None = None, button: dict | None = None, spend_cap_usd: float | None = None,
             clock=jev.now_utc) -> dict:
    """One customer message, typed or clicked, committed whole or not at all. Raises TurnError for
    a bad request (400) or an unknown session (404); everything else is a result dict."""
    if not turn_id or not isinstance(turn_id, str):
        raise TurnError(400, "turn_id is missing")
    if (text is None) == (button is None):
        raise TurnError(400, "send text or button, not both")
    if text is not None and (not isinstance(text, str) or not text.strip()):
        raise TurnError(400, "text is empty")
    if button is not None and not isinstance(button, dict):
        raise TurnError(400, "button must be an object")
    with store.lock(session_id):
        s = store.get(session_id)
        if s is None:
            raise TurnError(404, "unknown or expired session")
        if turn_id == s.last_turn_id:                                       # step 3
            if s.last_response is not None:
                return dict(s.last_response, repeat=True)
            return _result(s, "repeat", you=None, bot=[], entry=s.log[-1] if s.log else None, raw=None)
        if button is not None:
            return _click(store, flow, s, turn_id, button, clock)
        return _typed(store, flow, client, s, turn_id, text.strip(), spend_cap_usd, clock)


def _click(store: Store, flow: Flow, s: Session, turn_id: str, button: dict, clock) -> dict:
    current = current_message_id(s)
    bubble = next((b for b in s.transcript if b.get("who") == "bot" and b.get("id") == current), None)
    label, intent = button.get("label"), button.get("intent")
    known = bubble is not None and any(b["label"] == label and b["intent"] == intent for b in bubble["buttons"])
    if button.get("message_id") != current or not known:                    # step 4: stale → ignored
        return _result(s, "ignored", you=None, bot=[], entry=None, raw=None)
    params = dict(button.get("params") or {})
    at = jev.stamp(clock())
    you = you_bubble(label, "clicked")
    if intent == "start_over":
        return _start_over(store, flow, s, turn_id, at, you, verdict=None, kind="clicked")
    c = s.copy()
    c.transcript.append(you)
    before = len(c.transcript)
    turn_no_after = c.turn_no + 1
    sku, product_from = resolve_product(c, params)
    applied = act(c, flow, intent, params, sku=sku, product_from=product_from, turn_no_after=turn_no_after, text=label, at=at)
    c.turn_no = turn_no_after
    expire_contexts(c)
    entry = log_entry(s, flow, turn_no=c.turn_no, turn_id=turn_id, at=at, kind="clicked", text=label,
                      outcome="matched", applied=applied, response_id=intent, contexts_after=c.live_contexts())
    c.log.append(entry)
    c.last_turn_id = turn_id
    result = _result(c, "matched", you=you, bot=c.transcript[before:], entry=entry, raw=None)
    c.last_response = result
    store.commit(c)                                                          # step 7: swap and snapshot
    return result


def _typed(store: Store, flow: Flow, client: jev.Client, s: Session, turn_id: str, text: str,
           spend_cap_usd: float | None, clock) -> dict:
    at = jev.stamp(clock())
    v = classify(s, text, flow, client, spend_cap_usd=spend_cap_usd, clock=clock)   # step 5: no change held
    raw = {"request": v.request, "response": v.answer.raw if v.answer is not None else None}
    masked = v.intent == "give_delivery_details"
    you = you_bubble(text, "typed", masked)
    if v.outcome != "matched":
        if (s.pending_prompt or {}).get("slot") == DELIVERY_SLOT:
            # F-8: a failed call or the cap under the delivery slot — the text was the details; it is
            # stored nowhere: not the bubble, not the log, not the raw request kept for the viewer
            you = you_bubble(MASK_FOR_LOG, "typed", True)
            request = dict(v.request, state=dict(v.request.get("state") or {}, customer_said=MASK_FOR_JEV))
            raw = dict(raw, request=request)
        return _miss(store, flow, s, turn_id, at, you, v, raw)
    if v.intent == "start_over":
        return _start_over(store, flow, s, turn_id, at, you, verdict=v, kind="typed", raw=raw)
    c = s.copy()                                                             # step 6
    c.transcript.append(you)
    before = len(c.transcript)
    turn_no_after = c.turn_no + 1
    applied = act(c, flow, v.intent, v.entities, sku=v.sku, product_from=v.product_from, turn_no_after=turn_no_after, text=text, at=at)
    c.turn_no = turn_no_after
    expire_contexts(c)
    entry = log_entry(s, flow, turn_no=c.turn_no, turn_id=turn_id, at=at, kind="typed",
                      text=MASK_FOR_LOG if masked else text, outcome="matched", verdict=v, applied=applied,
                      response_id=v.intent, contexts_after=c.live_contexts())
    c.log.append(entry)
    c.last_turn_id = turn_id
    result = _result(c, "matched", you=you, bot=c.transcript[before:], entry=entry, raw=raw)
    c.last_response = result
    store.commit(c)                                                          # step 7
    c.raw[turn_id] = raw
    return result


def _miss(store: Store, flow: Flow, s: Session, turn_id: str, at: str, you: dict, v: Verdict, raw: dict) -> dict:
    """Step 5: `miss_count` +1, a log entry, the fallback or could-not-reach message — nothing else."""
    c = s.copy()
    c.transcript.append(you)
    before = len(c.transcript)
    c.miss_count += 1
    same = [button(b["label"], b["intent"], b.get("params")) for b in c.live_buttons]
    if v.outcome == "fallback":
        if c.miss_count == 1:      # F-4: "the same buttons" when there are none are the help buttons
            say(c, strip_text(flow.fallback["ladder"][0]), same or help_buttons(flow), variant="fallback", response_id="fallback.1", live=False)
        else:
            say(c, strip_text(flow.fallback["ladder"][1]), help_buttons(flow), variant="fallback", response_id="fallback.2", live=False)
        status = "live"
    elif v.outcome == "cap_reached":
        say(c, UNREACHABLE, same, variant="system", response_id="system.cap", live=False)
        status = "cap"
    else:
        say(c, UNREACHABLE, same, variant="system", response_id="system.unreachable", live=False)
        status = "unreachable"
    response_id = c.transcript[-1]["response_id"]
    entry = log_entry(s, flow, turn_no=c.turn_no, turn_id=turn_id, at=at, kind="typed", text=you["text"],
                      outcome=v.outcome, verdict=v, applied=[], response_id=response_id)
    c.log.append(entry)
    c.last_turn_id = turn_id
    result = _result(c, v.outcome, you=you, bot=c.transcript[before:], entry=entry, raw=raw, model_status=status)
    c.last_response = result
    store.commit(c)
    c.raw[turn_id] = raw
    return result


def _start_over(store: Store, flow: Flow, s: Session, turn_id: str, at: str, you: dict, *, verdict, kind: str,
                raw: dict | None = None) -> dict:
    """`start_over` ends the session — the snapshot goes — and a new one starts with the greeting."""
    entry = log_entry(s, flow, turn_no=s.turn_no, turn_id=turn_id, at=at, kind=kind, text=you["text"],
                      outcome="matched", verdict=verdict, applied=[], response_id="start_over", contexts_after=[])
    store.end(s.session_id)
    fresh = new_session(store, flow)
    return _result(fresh, "matched", you=you, bot=list(fresh.transcript), entry=entry, raw=raw, ended=True)


# --- the log entry (contract § The turn log)

def jev_block(answer: jev.JevAnswer, by_state: bool = False, awaiting: str | None = None) -> dict:
    block = {"status": answer.status, "intent": answer.intent, "confidence": answer.confidence,
             "entities": dict(answer.entities), "t_sent": answer.t_sent, "t_received": answer.t_received,
             "ms": answer.ms, "cost_usd": answer.cost_usd, "request_id": answer.request_id,
             "jev_ms": answer.jev_ms, "input_tokens": answer.input_tokens, "output_tokens": answer.output_tokens}
    if answer.error is not None:
        block["error"] = answer.error
    if by_state:
        block["by_state"] = True
    if awaiting:
        block["awaiting"] = awaiting          # Story 1.5: the slot sent, so a row renders from the log alone
    return block


def log_entry(session: Session, flow: Flow, *, turn_no: int, turn_id: str, at: str, kind: str,
              text: str, outcome: str, verdict: Verdict | None = None, applied: list | None = None,
              response_id: str | None = None, contexts_after: list | None = None) -> dict:
    """One entry. `session` is the state *before* the turn (its contexts are `contexts_before`).
    A click has no `jev` block; the `give_delivery_details` turn stores the log mask, not the text."""
    entry = {"turn_no": turn_no, "turn_id": turn_id, "at": at,
             "input": {"kind": kind, "text": text},
             "contexts_before": session.live_contexts(),
             "intents_in_scope": len(flow.in_scope(session.live_contexts())) + 1}
    if verdict is not None and verdict.answer is not None:
        entry["jev"] = jev_block(verdict.answer, verdict.by_state, (verdict.request.get("state") or {}).get("awaiting"))
    elif verdict is not None and verdict.outcome == "cap_reached":
        entry["jev"] = {"status": 0, "error": "cap", "ms": 0, "cost_usd": 0.0}
    entry["outcome"] = outcome
    entry["applied"] = list(applied or [])
    entry["response_id"] = response_id
    entry["contexts_after"] = list(contexts_after if contexts_after is not None else session.live_contexts())
    return entry
