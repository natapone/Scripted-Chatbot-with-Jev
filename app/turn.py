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
