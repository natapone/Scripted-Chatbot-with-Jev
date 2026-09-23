"""The catalogue's test set and its scoring — lifted from `tests/rehearsal/replay_s3.py` (Story 1.6),
which lifted them from Spike S-3's `run_intents.py` (`load_cases`, `scored_entities`, the strict /
`accept_intents` rule). Story 2.1 moves them here so the speed test (`app/speed.py`) and the
rehearsal script score the same way; the code is moved, not rewritten.

A case is one labelled message: its text, the intent it should get (`accept_intents` widens that for
the hard cases), the contexts live when it is typed and the `shop_said` before it. `build_session` is
the session the loop would hold when that case is typed. Nothing here calls Jev or writes to disk.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app import flow as flowmod, turn
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


def build_session(case: dict, flow: Flow) -> Session:
    """The session the loop would hold when this case is typed: the case's contexts live, its
    `shop_said` the last (and only) bot bubble, the context's slot pending."""
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
    return s


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
