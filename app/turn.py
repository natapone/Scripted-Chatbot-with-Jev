"""The turn loop — contract `session-state.md` § What is sent, § State before the classifier,
§ Committing a turn, § Who reads and writes what. The only caller of `jev.ask` for a customer
message; the only module that changes a `Session`.

Story 1.3 builds the loop with a minimal act: a matched intent answers with the catalogue's text
(placeholders and notes stripped) and its buttons, sets the contexts the catalogue names, and
writes nothing to the order form. `lead()` is the hook Story 1.4 fills; the order-form writers
come with it. Nothing here knows the key: the client carries it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app import jev
from app.flow import Flow
from app.session import Session, Store

THRESHOLD = 0.45                                 # conversation-flow Delta 2026-09-22: เอาค่ะ at 0.49 matches
HISTORY_TURNS = 4
MASK_FOR_JEV = "[รายละเอียดจัดส่ง]"              # what Jev sees instead of the delivery details
MASK_FOR_LOG = "[delivery details]"              # what the log stores for the give_delivery_details turn
NOT_MENTIONED = "not_mentioned"


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
        response_id: str | None = None, live: bool = True) -> dict:
    """Append a bot bubble `m<n>` to the transcript. With `live` (every committed reply) it becomes
    `last_bot_message` and its buttons the `live_buttons`; a miss's bubble leaves those alone."""
    msg_id = f"m{len(session.transcript) + 1}"
    bubble = {"who": "bot", "id": msg_id, "text": text,
              "buttons": [button(b["label"], b["intent"], b.get("params")) for b in buttons],
              "variant": variant, "response_id": response_id}
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


# --- the act: what a matched intent does here (Story 1.4 fills the order form on top of this)

UNREACHABLE = "ขอโทษด้วยน้า ตอนนี้ติดต่อระบบไม่ได้ค่ะ กดเลือกจากด้านล่างได้เลยน้า"   # the could-not-reach line
WHICH_PRODUCT = "ตัวไหนคะ? พิมพ์ชื่อหรือเลือกจากรายการได้เลยน้า"                 # contract: "the bot asks which product"
ORDER_INTENTS = ("order_product", "inform", "change_order", "view_order", "affirm", "deny",
                 "give_delivery_details", "cancel_order")
SLOTS = ("quantity", "brew", "roast", "payment")


def set_context(s: Session, flow: Flow, name: str, params: dict | None, turn_no_after: int) -> None:
    """`expires_after_turn` is absolute: the turn being committed plus the catalogue's lifespan."""
    lifespan = int(flow.contexts.get(name, {}).get("lifespan", 2))
    s.contexts[name] = {"expires_after_turn": turn_no_after + lifespan, "params": dict(params or {})}


def expire_contexts(s: Session) -> None:
    """Drop every context whose `expires_after_turn` has been reached — after the turn's own sets,
    so a context set this turn survives and one set two turns ago goes."""
    s.contexts = {n: c for n, c in s.contexts.items() if c.get("expires_after_turn", 0) > s.turn_no}


def lead(s: Session, flow: Flow, turn_no_after: int) -> None:
    """`then: lead` — the prompt for the first empty slot of the order. Story 1.4 fills this."""
    return None


def resume(s: Session, flow: Flow, turn_no_after: int) -> None:
    """`then: resume` — after a prepared answer, ask the pending question again and re-arm its context."""
    p = s.pending_prompt
    if not p:
        return
    asked = next((b for b in s.transcript if b.get("who") == "bot" and b.get("id") == p.get("message_id")), None)
    if asked is None:
        return
    say(s, asked["text"], asked.get("buttons", []), response_id=f"resume:{p.get('slot')}")
    s.pending_prompt = dict(p, message_id=s.last_bot_message["id"])
    if p.get("context"):
        set_context(s, flow, p["context"], p.get("params"), turn_no_after)


def default_reply(s: Session, flow: Flow, response_id: str) -> dict:
    return say(s, flow.default_shop_said, help_buttons(flow), response_id=response_id)


def act(s: Session, flow: Flow, intent: str, entities: dict, *, sku: str | None, product_from: str | None,
        turn_no_after: int) -> list[dict]:
    """Apply a matched intent to the copy: its writes, its reply, its contexts, its `then`.
    Returns `applied`. `start_over` is not handled here (it ends the session — see run_turn)."""
    it = flow_intent(flow, intent)
    applied: list[dict] = []
    s.miss_count = 0
    text = strip_text(it["response"]) or it["response"]     # as written when nothing but notes is left
    buttons = buttons_of(it)

    if intent in ("product_info", "ask_price", "select_option"):
        if sku and sku in flow.products:
            row = flow.products[sku]
            template = it["response"] if intent != "select_option" else flow_intent(flow, "product_info")["response"]
            say(s, fill(template, row), buttons, response_id=intent)
            if s.focus_sku != sku:
                applied.append({"set": "focus_sku", "to": sku, "product_from": product_from})
            s.focus_sku = sku
            set_context(s, flow, "offer_product", {"sku": sku}, turn_no_after)
        else:
            say(s, WHICH_PRODUCT, [button("ดูเมล็ดทั้งหมด", "browse_catalog")], response_id=intent)
    elif intent == "ask_recommendation":
        # the catalogue's first clause: brew unknown → ask how they brew; the rest is Story 1.4's
        recommend = s.order.get("recommend") or {}
        if recommend.get("brew") is None:
            opts = flow.entities["brew"]["options"]
            say(s, clause(it["response"], "if brew unknown"),
                [button(label, "inform", {"brew": key}) for key, label in opts.items()], response_id=intent)
            set_context(s, flow, "ask_brew", None, turn_no_after)
            s.pending_prompt = {"slot": "brew", "context": "ask_brew", "params": {}, "message_id": s.last_bot_message["id"]}
        elif recommend.get("roast") is None:
            opts = flow.entities["roast"]["options"]
            say(s, clause(it["response"], "else if roast unknown"),
                [button(label, "inform", {"roast": key}) for key, label in opts.items()], response_id=intent)
            set_context(s, flow, "ask_roast", None, turn_no_after)
            s.pending_prompt = {"slot": "roast", "context": "ask_roast", "params": {}, "message_id": s.last_bot_message["id"]}
        else:
            default_reply(s, flow, intent)
    elif intent in ORDER_INTENTS:
        # the minimal act: the text as written, no order-form write (Story 1.4)
        for slot in SLOTS:
            value = entities.get(slot)
            if value and value != NOT_MENTIONED:
                entry = {"set": slot, "to": value}
                if slot == "quantity":
                    entry["product_from"] = product_from
                applied.append(entry)
        say(s, text, buttons, response_id=intent)
    else:   # greet · help · thanks_bye · browse_catalog · ask_promotion · faq.*
        say(s, text, buttons, response_id=intent)

    then = it.get("then", "wait")
    if then == "lead":
        lead(s, flow, turn_no_after)
    elif then == "resume":
        resume(s, flow, turn_no_after)
    return applied


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
    applied = act(c, flow, intent, params, sku=sku, product_from=product_from, turn_no_after=turn_no_after)
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
        return _miss(store, flow, s, turn_id, at, you, v, raw)
    if v.intent == "start_over":
        return _start_over(store, flow, s, turn_id, at, you, verdict=v, kind="typed", raw=raw)
    c = s.copy()                                                             # step 6
    c.transcript.append(you)
    before = len(c.transcript)
    turn_no_after = c.turn_no + 1
    applied = act(c, flow, v.intent, v.entities, sku=v.sku, product_from=v.product_from, turn_no_after=turn_no_after)
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
        if c.miss_count == 1:
            say(c, strip_text(flow.fallback["ladder"][0]), same, variant="fallback", response_id="fallback.1", live=False)
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

def jev_block(answer: jev.JevAnswer, by_state: bool = False) -> dict:
    block = {"status": answer.status, "intent": answer.intent, "confidence": answer.confidence,
             "entities": dict(answer.entities), "t_sent": answer.t_sent, "t_received": answer.t_received,
             "ms": answer.ms, "cost_usd": answer.cost_usd, "request_id": answer.request_id}
    if answer.error is not None:
        block["error"] = answer.error
    if by_state:
        block["by_state"] = True
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
        entry["jev"] = jev_block(verdict.answer, verdict.by_state)
    elif verdict is not None and verdict.outcome == "cap_reached":
        entry["jev"] = {"status": 0, "error": "cap", "ms": 0, "cost_usd": 0.0}
    entry["outcome"] = outcome
    entry["applied"] = list(applied or [])
    entry["response_id"] = response_id
    entry["contexts_after"] = list(contexts_after if contexts_after is not None else session.live_contexts())
    return entry
