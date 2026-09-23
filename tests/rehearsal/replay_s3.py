"""Story 1.6 — the S-3 replay instrument. Not collected by the suite (no `test_` prefix, no
`__init__.py`); `tests/test_rehearsal.py` drives it hermetically.

Sub-commands:

    cases                                   build the 125 sessions, no network — a dry run
    replay --pass A|B [--limit-usd X]       every case through `turn.classify` on real Jev
    compare <A.json> <B.json>               the cases right in one pass and wrong in the other
    idle [--waits 5,30,90,180] [--samples 2]  F-7: first-call ms after an idle, then a warm call

Pass A is the loop's request: `awaiting` from the case's context (the slot `turn.lead`/`turn.ask`
would have left pending) and `history` from the one bot bubble the case's `shop_said` makes. Pass B
is the same session with `awaiting=None` and `history=[]` — S-3's request shape, inside the loop.
The decision after the call (the pending slot first, then the 0.45 threshold) is the loop's in both.

Scoring is lifted from `spikes/S-3_jev_intent_catalogue/run_intents.py` § `load_cases`,
`scored_entities` and the strict / `accept_intents` rule. The key never leaves the `jev.Client`
built from `config.load()`; summaries go to `var/rehearsal/` (ignored) and never hold a header.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config, flow as flowmod, jev, turn  # noqa: E402
from app.flow import Flow  # noqa: E402
from app.session import Session  # noqa: E402

OUT = ROOT / "var" / "rehearsal"
VOID_AFTER = 10                   # S-3 saw 57 empty answers in a row; 10 in a row voids the pass
TIMEOUT_UPPER_USD = 0.0002        # a call the client abandoned: counted at this upper bound (F-9)
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


class ShapeB(Flow):
    """Pass B: the loop's request with `awaiting` and `history` taken out — S-3's shape."""

    def build_request(self, shop_said, customer_said, awaiting, history, contexts):
        return super().build_request(shop_said, customer_said, None, [], contexts)


def flow_for(pass_name: str, flow: Flow) -> Flow:
    if pass_name == "A":
        return flow
    return ShapeB(**{f.name: getattr(flow, f.name) for f in fields(flow)})


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


def summarise(records: list[dict], pass_name: str, client: jev.Client, status: str, timeout_s: float) -> dict:
    answered = [r for r in records if r["error"] is None]
    ms = [r["ms"] for r in records]
    er = [e for r in records for e in r["entities"]]
    named = [e for e in er if e["expected"] != "not_mentioned"]
    timeouts = [r for r in records if r["error"] == "TimeoutError"]
    return {"pass": pass_name, "status": status, "cases": len(records), "calls": client.calls,
            "answered": len(answered), "failed": len(records) - len(answered),
            "loop_ok": sum(r["loop_ok"] for r in records), "loop_strict": sum(r["loop_strict"] for r in records),
            "jev_ok": sum(r["jev_ok"] for r in records), "jev_strict": sum(r["jev_strict"] for r in records),
            "entities_ok": sum(e["ok"] for e in er), "entities_n": len(er),
            "named_ok": sum(e["ok"] for e in named), "named_n": len(named),
            "by_state": sum(r["by_state"] for r in records),
            "p50_ms": round(pct(ms, 50)), "p95_ms": round(pct(ms, 95)), "max_ms": max(ms) if ms else 0,
            "over_5s": [r["ms"] for r in records if r["ms"] > 5000],
            "over_timeout": [r["ms"] for r in records if r["ms"] > timeout_s * 1000],
            "timeouts": len(timeouts), "spent_usd": round(client.spent_usd, 6),
            "spent_upper_usd": round(client.spent_usd + TIMEOUT_UPPER_USD * len(timeouts), 6)}


def run_pass(cases: list[dict], cat: dict, flow: Flow, client: jev.Client, pass_name: str, *,
             limit_usd: float | None = None, timeout_s: float = config.JEV_TIMEOUT, clock=jev.now_utc,
             echo=print) -> dict:
    """Every case through `turn.classify`. Stops VOID after `VOID_AFTER` failures in a row, LIMIT
    when the client's spend reaches `limit_usd`. Returns the summary with its records."""
    f = flow_for(pass_name, flow)
    records, in_a_row, status = [], 0, "COMPLETE"
    for case in cases:
        v = turn.classify(build_session(case, flow), case["text"], f, client, clock=clock)
        r = score(cat, case, v)
        records.append(r)
        in_a_row = in_a_row + 1 if r["error"] else 0
        mark = "✓" if r["loop_ok"] else "✗"
        if r["error"] or not r["loop_ok"] or not r["jev_ok"]:
            echo(f"{case['n']:>3} {mark} want {case['intent']:<20} loop {r['loop']} · jev {r['jev']} "
                 f"({r['confidence']}) {r['ms']} ms {r['error'] or ''} — {case['text'][:40]}")
        if in_a_row >= VOID_AFTER:
            status = "VOID"
            break
        if limit_usd is not None and client.spent_usd >= limit_usd:
            status = "LIMIT"
            break
    summary = summarise(records, pass_name, client, status, timeout_s)
    summary["records"] = records
    return summary


def table(s: dict) -> str:
    n = s["cases"]
    return "\n".join([
        f"pass {s['pass']} · {s['status']} · {n} cases · {s['calls']} calls · {s['failed']} failed ({s['timeouts']} timeouts)",
        f"loop intent  {s['loop_ok']}/{n} (accept_intents) · strict {s['loop_strict']}/{n} · by state {s['by_state']}",
        f"jev intent   {s['jev_ok']}/{n} (accept_intents) · strict {s['jev_strict']}/{n}",
        f"entities     {s['entities_ok']}/{s['entities_n']} strict · named values {s['named_ok']}/{s['named_n']}",
        f"latency      p50 {s['p50_ms']} · p95 {s['p95_ms']} · max {s['max_ms']} ms · >5 s {s['over_5s']} · >timeout {s['over_timeout']}",
        f"cost         ${s['spent_usd']:.6f} (upper ${s['spent_upper_usd']:.6f})"])


def verdict(a: dict, b: dict, floor: int = 119) -> str:
    """AC-1, pre-registered: PASS iff A ≥ B and A ≥ 119/125 (the loop's intent, accept_intents)."""
    if a["status"] == "VOID" or b["status"] == "VOID":
        return "VOID"
    return "PASS" if a["loop_ok"] >= b["loop_ok"] and a["loop_ok"] >= floor else "FAIL"


def differing(a: dict, b: dict) -> list[dict]:
    rb = {r["n"]: r for r in b["records"]}
    out = []
    for r in a["records"]:
        o = rb.get(r["n"])
        if o is not None and r["loop_ok"] != o["loop_ok"]:
            out.append({"n": r["n"], "text": r["text"], "want": r["intent"], "A": r["loop"], "B": o["loop"],
                        "A_conf": r["confidence"], "B_conf": o["confidence"], "awaiting": r["awaiting"]})
    return out


# --- F-7: the idle drop

def idle(client: jev.Client, waits: list[int], samples: int, sleep=time.sleep, clock=jev.now_utc,
         echo=print) -> list[dict]:
    """After each idle: one call (the first after the wait), then one straight after (warm).
    `reconnected` says whether the first call had to open a new connection."""
    rows = []
    for w in waits:
        for i in range(samples):
            sleep(w)
            before = client._conn
            first = jev.ask(None, jev.WARM_UP_BODY, client=client, clock=clock)
            reconnected = client._conn is not before
            warm = jev.ask(None, jev.WARM_UP_BODY, client=client, clock=clock)
            row = {"wait_s": w, "sample": i + 1, "first_ms": first.ms, "first_error": first.error,
                   "reconnected": reconnected, "warm_ms": warm.ms, "warm_error": warm.error}
            rows.append(row)
            echo(f"idle {w:>4} s #{i + 1}: first {first.ms} ms{' (reconnected)' if reconnected else ''}"
                 f"{' ' + first.error if first.error else ''} · warm {warm.ms} ms")
    return rows


# --- command line

def _client(cfg: config.Config) -> jev.Client:
    return jev.Client(cfg.key, cfg.jev_host, cfg.jev_timeout)


def _write(name: str, data: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{name}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="replay_s3")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("cases")
    rp = sub.add_parser("replay")
    rp.add_argument("--pass", dest="pass_name", choices=("A", "B"), required=True)
    rp.add_argument("--limit-usd", type=float, default=None)
    cp = sub.add_parser("compare")
    cp.add_argument("a")
    cp.add_argument("b")
    ip = sub.add_parser("idle")
    ip.add_argument("--waits", default="5,30,90,180")
    ip.add_argument("--samples", type=int, default=2)
    args = ap.parse_args(argv)

    cat, flow = read_catalogue(), flowmod.load()
    cases = load_cases(cat)
    if args.cmd == "cases":
        slots: dict[str, int] = {}
        for c in cases:
            p = build_session(c, flow).pending_prompt
            if p:
                slots[p["slot"]] = slots.get(p["slot"], 0) + 1
        print(f"cases {len(cases)} · with a context {sum(1 for c in cases if c['contexts'])}"
              f" · with shop_said {sum(1 for c in cases if c['shop_said'])}")
        entity = {k: v for k, v in slots.items() if k != "confirmation"}
        print(f"awaiting with an entity slot {sum(entity.values())}: "
              + ", ".join(f"{k} {v}" for k, v in sorted(entity.items()))
              + f" · awaiting confirmation {slots.get('confirmation', 0)}")
        return 0
    if args.cmd == "compare":
        a = json.loads(Path(args.a).read_text(encoding="utf-8"))
        b = json.loads(Path(args.b).read_text(encoding="utf-8"))
        print(f"A loop {a['loop_ok']}/{a['cases']} · B loop {b['loop_ok']}/{b['cases']} · verdict {verdict(a, b)}")
        for d in differing(a, b):
            print(f"  #{d['n']} want {d['want']} · A {d['A']} ({d['A_conf']}) · B {d['B']} ({d['B_conf']})"
                  f" · awaiting {d['awaiting']} — {d['text']}")
        return 0

    cfg = config.load()
    client = _client(cfg)
    try:
        if args.cmd == "replay":
            s = run_pass(cases, cat, flow, client, args.pass_name, limit_usd=args.limit_usd,
                         timeout_s=cfg.jev_timeout)
            print(table(s))
            print(f"summary: {_write('replay-' + args.pass_name, s).relative_to(ROOT)}")
        else:
            waits = [int(x) for x in args.waits.split(",") if x.strip()]
            status = jev.warm_up(None, client=client)
            rows = idle(client, waits, args.samples)
            data = {"warm_up": status, "rows": rows, "calls": client.calls,
                    "spent_usd": round(client.spent_usd, 6)}
            print(f"calls {client.calls} · ${client.spent_usd:.6f}")
            print(f"summary: {_write('idle', data).relative_to(ROOT)}")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
