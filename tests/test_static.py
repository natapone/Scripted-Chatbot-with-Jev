"""Story 1.3b — the served page runs on the server, not the fixtures. Hermetic: the real server on
an ephemeral loopback port serves its static files; nothing is typed, no Jev, no network. What a
browser would do with the page is proven by hand (the Story's task 04); here the page's bytes are
checked for the shape that proof relies on."""
from __future__ import annotations

import http.client
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from app import config, server

FAKE_KEY = "sk-or-v1-test-key-never-real"
GOOD = {"OPENROUTER_API_KEY": FAKE_KEY, "THB_PER_USD": "34.9", "RATE_DATE": "2026-09-22"}


class StaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()                    # snapshots go here, never under var/
        cfg = config.load(env_path=Path("/nonexistent/.env"), environ={**GOOD, "VAR_DIR": cls.tmp.name})
        cls.httpd = server.make_server(cfg, port=0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path)
            r = conn.getresponse()
            return r.status, r.read().decode("utf-8", "replace")
        finally:
            conn.close()

    def test_shared_js_talks_to_the_server(self):
        status, js = self.get("/assets/shared.js")
        self.assertEqual(status, 200)
        # the engine path: the session from the server, a typed line and a click as POST /api/turn
        self.assertIn('fetch("/api/session?id="', js)
        self.assertIn('fetch("/api/turn"', js)
        self.assertIn('fetch("/api/session/end"', js)
        self.assertIn('fetch("/api/config"', js)
        self.assertIn("crypto.randomUUID()", js)                      # a fresh turn_id per message
        self.assertIn('sessionStorage.setItem("session_id"', js)     # the id, and nothing else
        self.assertEqual(js.count("sessionStorage.setItem("), 1)
        # the fixture engine is gone: no fixture fetch, no local act, no order form in the browser
        self.assertNotIn('fetch("assets/fixtures.json"', js)
        self.assertNotIn("fixtures.json", js)
        for gone in ("function act(", "act(entry)", "function leadNext(", "function parseSlot(", "function readback(",
                     "function totals(", "function applyPromo(", "function fitPromo(", "function recommendStep(",
                     "function helpButtons(", "const REC ", "FX.data", "const FX "):
            self.assertNotIn(gone, js, gone)
        self.assertNotIn("order:", js)
        self.assertNotIn("PROTO_FORCE_FAIL", js)
        self.assertNotIn(FAKE_KEY, js)
        # a click is the same POST with the button and its message_id; a stale one is `ignored`
        self.assertIn("button: btn", js)
        self.assertIn("message_id: id", js)
        self.assertIn('r.outcome === "ignored"', js)
        # start over ends the session, then asks for a new one; a typed เริ่มใหม่ comes back `ended`
        self.assertIn("if (r.ended)", js)
        self.assertLess(js.index('fetch("/api/session/end"'), js.index('await load("")', js.index('fetch("/api/session/end"')))
        # the composer is `judging` around every call and `ready` after, whatever happened
        self.assertEqual(js.count('setComposer("judging")'), 3)      # send, click, startOver
        self.assertEqual(js.count('finally { setComposer("ready"); }'), 3)
        if shutil.which("node"):                                     # syntax, when a node is at hand
            for name in ("shared.js", "speed.js"):
                r = subprocess.run(["node", "--check", str(server.STATIC / "assets" / name)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)

    # 05_components.md's tokens for the chat screen (P-001 / W-001), by the component that owns them
    TOKENS = {
        "index.html": ("chat", "messages", "composer", "send", "start-over", "panel", "key-info", "avg-ms",
                       "total-baht", "total-turns", "viewer", "viewer-close", "viewer-sent", "viewer-back",
                       "viewer-applied", "rate", "rate-date", "model-status", "band-top", "band-bottom",
                       "viewer-raw-request", "viewer-raw-response"),              # Story 1.5: the page's own <details>
        "shared.js": ("bot-${id}", "you-${youCount}", "opt-${i + 1}", "badge-clicked", "turn-${n}", "turn-${n}-intent",
                      "turn-${n}-confidence", "turn-${n}-ms", "turn-${n}-baht", "turn-${n}-usd", "turn-${n}-open",
                      "turn-${n}-prov-product",                              # Story 1.5: F-1, now named by the design
                      "readback", "readback-total"),                       # Story 1.4: the ReadBack component, from server data
    }                                                                        # Story 2.2: speed.js's tokens are gone (DR-010)

    def test_page_carries_every_token(self):
        served = {"index.html": self.get("/")[1], "shared.js": self.get("/assets/shared.js")[1]}
        for name, tokens in self.TOKENS.items():
            for token in tokens:
                if "$" in token:                                     # a template: the literal the page builds
                    self.assertIn(f"`{token}`", served[name], f"{token} in {name}")
                elif name == "index.html":
                    self.assertIn(f'data-testid="{token}"', served[name], f"{token} in {name}")
                else:
                    self.assertIn(f'"data-testid": "{token}"', served[name], f"{token} in {name}")
        # the figures a driver reads carry data-value; the composer its state; a button its liveness
        js = served["shared.js"]
        for figure in ("avg-ms", "total-baht", "total-turns"):
            self.assertIn(f'set("#{figure}"', js, figure)
        self.assertIn('"data-value": j?.ms', js)
        self.assertIn('"data-value": j?.cost_usd', js)
        self.assertIn('"data-live": "true"', js)
        self.assertIn('data-state="ready"', served["index.html"])

    def test_prototype_mark_gone_and_fixtures_not_served(self):
        status, html = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("<title>Beanly · Scripted Chatbot with Jev</title>", html)
        self.assertNotIn("prototype", html.split("<body>")[0])
        for name, text in (("index.html", html), ("shared.js", self.get("/assets/shared.js")[1])):
            self.assertNotIn("PROTOTYPE", text, name)
            self.assertNotIn("proto-mark", text, name)
            self.assertNotIn("FIXTURES, NOT JEV", text, name)
        status, body = self.get("/assets/fixtures.json")
        self.assertEqual(status, 404)
        self.assertFalse((server.STATIC / "assets" / "fixtures.json").exists())
        self.assertEqual(sorted(p.name for p in (server.STATIC / "assets").iterdir() if not p.name.startswith(".")),
                         ["design-system.css", "shared.js", "speed.js"])
        # the greeting and its three buttons come from the server — what the page draws first
        s = json.loads(self.get("/api/session?id=")[1])
        self.assertTrue(s["new"])
        self.assertTrue(s["transcript"][0]["text"].startswith("สวัสดีค่ะ Beanly นะคะ"))
        self.assertEqual(len(s["transcript"][0]["buttons"]), 3)
        self.assertEqual(len(s["live_buttons"]), 3)
        self.assertNotIn(FAKE_KEY, html)

    def test_read_back_rendered_from_server_data(self):  # Story 1.4 task 04; AC-6
        js = self.get("/assets/shared.js")[1]
        # the grid is built from `m.readback`, never from an order the browser keeps
        self.assertIn("if (m.readback) b.append(...readbackNodes(m.readback))", js)
        self.assertIn("function readbackNodes(", js)
        self.assertNotIn("function readback(", js)
        self.assertIn('"data-testid": "readback-total"', js)
        self.assertIn('"data-value": rb.total', js)
        self.assertIn('class: "readback"', js)
        self.assertIn('"total"', js)                                  # the total row's class, bold in the design system
        self.assertNotIn("totals(", js)
        self.assertNotIn("PROMO-", js)
        # the customer bubble keeps its masked mark and the clicked badge; the sample button is any button
        self.assertIn('"data-masked": String(!!m.masked)', js)
        self.assertIn('"data-testid": "badge-clicked"', js)
        self.assertNotIn("ใช้ข้อมูลตัวอย่าง", js)
        self.assertNotIn("081-000-0000", js)
        css = self.get("/assets/design-system.css")[1]
        self.assertIn(".readback {", css)
        self.assertIn(".readback .total {", css)
        self.assertIn("white-space: pre-wrap", css)                  # the tail's line break renders
        # the server passes the bubble's `readback` through the session view unchanged
        from app import turn
        s = self.httpd.store.new()                                    # type: ignore[attr-defined]
        turn.welcome(s, self.httpd.flow)                              # type: ignore[attr-defined]
        s.order["lines"] = [{"sku": "KBN-002", "qty": 3, "added_by": "customer"}]
        s.order["payment"], s.order["delivery_text"], s.promos_offered = "cod", "ที่อยู่สมมติ", ["PROMO-01"]
        turn.lead(s, self.httpd.flow, 1)                              # type: ignore[attr-defined]
        self.httpd.store.commit(s)                                    # type: ignore[attr-defined]
        v = json.loads(self.get(f"/api/session?id={s.session_id}")[1])
        rb = v["transcript"][-1]
        self.assertEqual((rb["variant"], rb["readback"]["total"], rb["readback"]["rows"][-1]), ("read-back", 1270, ["รวม", "1,270 บาท"]))
        self.assertEqual([b["label"] for b in v["live_buttons"]], ["ยืนยัน", "ขอแก้ไข"])
        self.assertNotIn(FAKE_KEY, json.dumps(v))

    # Story 1.5 — the design diff as a test: every token 05_components names for the panel's
    # components is emitted by the served page (AC-6; F-1)
    DESIGN = Path(__file__).resolve().parent.parent / "memory" / "product" / "design" / "05_components.md"

    def design_tokens(self, component):
        import re
        d = self.DESIGN.read_text(encoding="utf-8")
        i = d.index(f"### `{component}`")
        section = d[i:d.index("\n### ", i + 4)]
        row = next(line for line in section.splitlines() if line.startswith("| **Tokens**"))
        row = row.split("— *Delta")[0]                                # a note's words are not tokens
        return [t for t in re.findall(r"`([^`]+)`", row) if t not in ("jev", "focus_sku") and not t.startswith("context:")]

    @unittest.skipUnless(DESIGN.exists(), "memory/ is local-only, not in this clone")
    def test_design_tokens_are_on_the_page(self):  # AC-6
        served = self.get("/")[1] + self.get("/assets/shared.js")[1]
        seen = []
        for component in ("KeyInfo", "TurnRow", "PanelColumn", "TurnViewer"):
            for token in self.design_tokens(component):
                token = token.replace('data-testid="', "").rstrip('"')
                if token.startswith("data-"):                            # an attribute the page sets
                    needle = f'"{token}"' if f'"{token}"' in served else f"{token}="
                elif "{n}" in token:                                     # a template: the literal the page builds
                    needle = "`" + token.replace("{n}", "${n}") + "`"
                elif token == "total-usd":                               # a hidden attribute, not a testid
                    needle = 'data-total-usd='
                else:
                    needle = f'data-testid="{token}"' if f'data-testid="{token}"' in served else f'"data-testid": "{token}"'
                self.assertIn(needle, served, f"{component}: {token}")
                seen.append(token)
        for token in ("turn-{n}-prov-product", "rate-date", "viewer-raw-request", "viewer-raw-response", "total-usd", "data-at"):
            self.assertIn(token, seen)                                   # the design names them; the loop checked them
        self.assertEqual(self.DESIGN.read_text(encoding="utf-8").count("turn-{n}-prov-product"), 1)

    def node(self, script):
        if not shutil.which("node"):
            self.skipTest("no node")
        src = str(server.STATIC / "assets" / "shared.js")
        prog = ("const vm=require('vm');const fs=require('fs');const c={console};vm.createContext(c);"
                f"vm.runInContext(fs.readFileSync({json.dumps(src)},'utf8')+';'+{json.dumps(script)},c);")
        r = subprocess.run(["node", "-e", prog], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_turn_row_reads_the_server_forms(self):  # AC-2; walk 3.3, 4.1, the hazard
        e = lambda outcome, rid="inform", **jev: {"outcome": outcome, "response_id": rid, "jev": jev}
        cases = [e("matched", intent="none", by_state=True, awaiting="quantity"),
                 e("matched", "give_delivery_details", intent="none", by_state=True, awaiting="delivery"),
                 e("matched", "affirm", intent="affirm"),
                 e("fallback", "fallback.1", intent="none"),
                 e("model_failed", "system.unreachable", error="ConnectionRefusedError"),
                 e("cap_reached", "system.cap", error="cap"),
                 dict(e("matched", "ask_brew", intent="inform", by_state=True, awaiting="payment"), judged="inform")]
        out = self.node("console.log(JSON.stringify({lines: " + json.dumps(cases) + ".map(intentLine),"
                        " prov: ['jev', 'context:ask_quantity', 'focus_sku', 'context:offer_product', 'options_shown'].map(PROV)}))")
        self.assertEqual(out["lines"], ["inform · by state (awaiting quantity)",
                                        "give_delivery_details · by state (awaiting delivery)",
                                        "affirm", "FALLBACK · none", "MODEL FAILED · ConnectionRefusedError",
                                        "SPEND CAP REACHED · no call made",
                                        "inform · by state (awaiting payment)"])     # Story 2.3: a run row names what was judged
        self.assertEqual(out["prov"], ["from Jev", "from context (ask_quantity)", "from focus",
                                       "from context (offer_product)", "from options shown"])

    # A DOM just big enough for the panel's functions: elements by id, text, attributes, children.
    FAKE_DOM = r"""
class N { constructor(tag){ this.tag=tag; this.kids=[]; this.attrs={}; this.style={}; this.own=''; this.offsetHeight=96; this.classList={add(){},remove(){}}; }
  get textContent(){ return this.own + this.kids.map(k=>k.textContent).join('|'); } set textContent(t){ this.own=String(t); this.kids=[]; }
  setAttribute(k,v){ this.attrs[k]=String(v); } getAttribute(k){ return this.attrs[k] ?? null; } removeAttribute(k){ delete this.attrs[k]; }
  append(...xs){ for (const x of xs) this.kids.push(typeof x==='string'? Object.assign(new N('#text'),{own:x}) : x); }
  replaceChildren(...xs){ this.kids=[]; this.append(...xs); } prepend(x){ this.kids.unshift(x); } remove(){}
  addEventListener(){} querySelectorAll(){ return []; } querySelector(){ return null; } }
const byId = {}; for (const id of ['viewer','viewer-title','viewer-sent','viewer-back','viewer-applied','viewer-raw-request','viewer-raw-response','key-info','key-status','model-status','avg-ms','total-baht','total-turns']) byId[id]=new N('div');
var document = { createElement: (t)=>new N(t), createTextNode: (t)=>Object.assign(new N('#text'),{own:t}),
  querySelector: (sel)=> sel.startsWith('#') ? byId[sel.slice(1)] ?? null : null, querySelectorAll: ()=>[] };
var Node = N; var setTimeout = (f)=>f();
"""

    def test_viewer_shows_the_three_sections_and_the_raw(self):  # AC-3; walk 1.11
        entry = {"turn_no": 7, "turn_id": "t7", "at": "2026-09-22T06:48:10.412Z", "input": {"kind": "typed", "text": "1 ถุงค่ะ"},
                 "contexts_before": ["ask_quantity"], "intents_in_scope": 23, "outcome": "matched", "response_id": "inform",
                 "jev": {"status": 200, "intent": "none", "confidence": 0.91, "by_state": True, "awaiting": "quantity",
                         "entities": {"product": "not_mentioned", "quantity": "1", "brew": "not_mentioned", "roast": "not_mentioned", "payment": "not_mentioned"},
                         "t_sent": "2026-09-22T06:48:10.418Z", "t_received": "2026-09-22T06:48:10.756Z", "ms": 338, "cost_usd": 0.000164, "request_id": "gen-dec-1"},
                 "applied": [{"set": "lines[DH-001].qty", "to": 1, "product_from": "context:ask_quantity"}]}
        raw = {"request": {"model": "typesafe/jev-1.13", "state": {"shop_said": "รับกี่ถุงดีคะ?", "customer_said": "1 ถุงค่ะ", "awaiting": "quantity",
                                                                    "history": [{"who": "bot", "text": "สวัสดีค่ะ"}, {"who": "customer", "text": "ตัวแรกค่ะ"}]}},
               "response": {"id": "gen-dec-1", "answers": {"intent": {"choice": "none", "confidence": 0.91,
                                                                   "probabilities": {"none": 0.91, "inform": 0.05, "affirm": 0.03, "greet": 0.01}}}}}
        script = self.FAKE_DOM + (
            "CFG.rate.thb_per_usd = 34.9; const out = {};"
            f"S.session = {{ id: 's', log: [{json.dumps(entry)}], raw: {{ t7: {json.dumps(raw)} }} }};"
            "openViewer(1); for (const k of ['viewer-sent','viewer-back','viewer-applied','viewer-raw-request','viewer-raw-response']) out[k] = document.querySelector('#'+k).textContent;"
            "out.bottom = document.querySelector('#viewer').style.bottom; out.open = document.querySelector('#viewer').getAttribute('data-open');"
            "S.session.raw = {}; openViewer(1); out.after = {}; for (const k of ['viewer-sent','viewer-back','viewer-raw-request','viewer-raw-response']) out.after[k] = document.querySelector('#'+k).textContent;"
            "console.log(JSON.stringify(out));")
        out = self.node(script)
        sent, back, applied = out["viewer-sent"], out["viewer-back"], out["viewer-applied"]
        for field in ("shop_said|รับกี่ถุงดีคะ?", "customer_said|1 ถุงค่ะ", "awaiting|quantity", "history|bot: สวัสดีค่ะ|customer: ตัวแรกค่ะ",
                      "contexts|ask_quantity", "intents in scope|23"):
            self.assertIn(field, sent)
        self.assertLess(sent.index("shop_said"), sent.index("customer_said"))
        self.assertLess(sent.index("customer_said"), sent.index("awaiting"))
        self.assertLess(sent.index("awaiting"), sent.index("history"))
        for field in ("intent|none 0.91 · by state → inform", "top probabilities|none 0.91 · inform 0.05 · affirm 0.03", "quantity|1",
                      "status|200", "t_sent → t_received|06:48:10.418 → 06:48:10.756 = 338 ms", "cost|$0.000164 → ฿0.0057", "request_id|gen-dec-1"):
            self.assertIn(field, back)
        self.assertIn("lines[DH-001].qty|1  ← from context (ask_quantity)", applied)
        self.assertIn('"customer_said": "1 ถุงค่ะ"', out["viewer-raw-request"])
        self.assertIn('"probabilities"', out["viewer-raw-response"])
        self.assertEqual((out["bottom"], out["open"]), ("96px", "true"))            # stops above key-info
        # after a restart: the raw is gone; the raw blocks say so and the rest shows from the log
        after = out["after"]
        self.assertEqual((after["viewer-raw-request"], after["viewer-raw-response"]), ("— not in memory", "— not in memory"))
        self.assertIn("customer_said|1 ถุงค่ะ", after["viewer-sent"])
        self.assertIn("awaiting|quantity", after["viewer-sent"])                     # from the log's jev block
        self.assertIn("shop_said|— not in memory", after["viewer-sent"])
        self.assertIn("t_sent → t_received|06:48:10.418 → 06:48:10.756 = 338 ms", after["viewer-back"])
        js = self.get("/assets/shared.js")[1]
        self.assertIn('if (ev.key === "Escape") closeViewer()', js)                  # Escape closes

    def test_badge_and_status_line_follow_the_last_typed_turn(self):  # AC-4; walk hazard
        html = self.get("/")[1]
        self.assertIn('data-testid="model-status" id="model-status" data-status="live"', html)
        ok = lambda n, cost=0.000164: {"turn_id": f"t{n}", "outcome": "matched", "input": {"text": "x"}, "jev": {"status": 200, "ms": 300 + n, "cost_usd": cost}}
        down = {"turn_id": "tf", "outcome": "model_failed", "input": {"text": "x"}, "jev": {"status": 0, "error": "ConnectionRefusedError", "ms": 0, "cost_usd": 0}}
        cap = {"turn_id": "tc", "outcome": "cap_reached", "input": {"text": "x"}, "jev": {"status": 0, "error": "cap", "ms": 0, "cost_usd": 0.0}}
        clicked = {"turn_id": "tk", "outcome": "matched", "input": {"kind": "clicked", "text": "1 ถุง"}}
        steps = [[ok(1)], [ok(1), down], [ok(1), down, clicked], [ok(1), down, clicked, ok(2)], [ok(1), cap], []]
        script = self.FAKE_DOM + (
            "CFG.rate.thb_per_usd = 34.9; const out = [];"
            f"for (const log of {json.dumps(steps)}) {{ S.session = {{ id: 's', log, raw: {{}} }}; updateKeyInfo();"
            " const b = document.querySelector('#model-status');"
            " out.push([b.textContent, b.className, b.getAttribute('data-status'), document.querySelector('#key-status').textContent,"
            " document.querySelector('#total-baht').getAttribute('data-value'), document.querySelector('#avg-ms').textContent]); }"
            "console.log(JSON.stringify(out));")
        out = self.node(script)
        self.assertEqual(out[0][:4], ["live", "badge live", "live", ""])
        self.assertEqual(out[1][:4], ["down", "badge down", "down", "● unreachable · ConnectionRefusedError"])
        self.assertEqual((out[1][4], out[1][5]), ("0.000164", "300 ms"))             # the failed turn is not counted
        self.assertEqual(out[2][:4], out[1][:4])                                     # a click makes no call: still down
        self.assertEqual(out[3][:4], ["live", "badge live", "live", ""])             # the next answered call: live, line gone
        self.assertEqual(out[4][:4], ["cap", "badge cap", "cap", "● spend cap reached"])
        self.assertEqual(out[5][:4], ["live", "badge live", "live", ""])             # start over / a fresh page
        self.assertIn(".badge.cap::before", self.get("/assets/design-system.css")[1])

    # Story 2.2 — DR-010: the speed test adds nothing to the page. The design's SpeedTest and
    # SpeedTestButton sections are superseded, so their tokens are diffed in reverse: none is served.
    GONE = ("speed-test-open", "speed-pop", "speed-chooser", "speed-target-100", "speed-target-1000", "speed-start",
            "speed-test", "speed-count", "speed-target", "speed-elapsed-ms", "speed-per-s", "speed-correct",
            "speed-errors", "speed-phase", "speed-ticker", "speed-summary", "speed-status")

    def test_speed_test_control_is_off_the_page(self):  # AC-1
        served = {name: self.get(path)[1] for name, path in (("index.html", "/"), ("shared.js", "/assets/shared.js"),
                                                              ("speed.js", "/assets/speed.js"),
                                                              ("design-system.css", "/assets/design-system.css"))}
        for name, text in served.items():
            self.assertFalse("speed-" in text, name)                # no testid, id or class of the control
            for words in ("speed test ▾", "not wired", "1,000 demo", "100 rehearsal", '"Start"', "btn-start"):
                self.assertFalse(words in text, f"{words} in {name}")
        tokens = list(self.GONE)
        if self.DESIGN.exists():                                    # the reverse diff reads the design's own list
            tokens += [t.replace('data-testid="', "").rstrip('"') for c in ("SpeedTest", "SpeedTestButton")
                       for t in self.design_tokens(c) if "speed-" in t]            # `data-value` is the chat's too
        for token in tokens:
            for name, text in served.items():
                self.assertFalse(token in text, f"{token} in {name}")
        self.assertIn("speedFromAddress()", served["index.html"])  # the only thing the page boots for it
        self.assertNotIn("speedMount", served["index.html"] + served["speed.js"])
        self.assertNotIn("setInterval", served["speed.js"])        # no simulated run


    # Story 2.2 — the run client, driven in a DOM just big enough for the chat's own functions:
    # elements with parents and children, class selectors, the composer, a fetch that records
    # every call and answers from a script, and an address bar with history.replaceState.
    PAGE_DOM = r"""
class N { constructor(tag){ this.tag=tag; this.kids=[]; this.attrs={}; this.style={}; this.own=''; this.className=''; this.parent=null; this.dataset={}; this.disabled=false; this.offsetHeight=96; this.offsetWidth=1; this.scrollTop=0; this.scrollHeight=0;
    const self=this; this.classList={ add(c){ if(!self.cls().includes(c)) self.className=(self.className+' '+c).trim(); }, remove(c){ self.className=self.cls().filter(x=>x!==c).join(' '); }, contains(c){ return self.cls().includes(c); } }; }
  cls(){ return String(this.className||'').split(/\s+/).filter(Boolean); }
  get textContent(){ return this.own + this.kids.map(k=>k.textContent).join('|'); } set textContent(t){ this.own=String(t); this.kids=[]; }
  setAttribute(k,v){ this.attrs[k]=String(v); } getAttribute(k){ return this.attrs[k] ?? null; } removeAttribute(k){ delete this.attrs[k]; }
  append(...xs){ for (let x of xs){ if (typeof x==='string') x=Object.assign(new N('#text'),{own:x}); x.parent=this; this.kids.push(x); } }
  prepend(x){ x.parent=this; this.kids.unshift(x); } replaceChildren(...xs){ this.kids=[]; this.append(...xs); }
  remove(){ if (this.parent) { this.parent.kids=this.parent.kids.filter(k=>k!==this); this.parent=null; } }
  get children(){ return this.kids.filter(k=>k.tag!=='#text'); } get firstElementChild(){ return this.children[0]||null; } get lastElementChild(){ const c=this.children; return c[c.length-1]||null; }
  all(){ return this.children.flatMap(k=>[k, ...k.all()]); }
  match(sel){ const m=sel.match(/^([a-z]*)((?:\.[\w-]+)*)/); const tag=m[1], cs=m[2].split('.').filter(Boolean); return (!tag||this.tag===tag) && cs.every(c=>this.cls().includes(c)); }
  querySelectorAll(sel){ return this.all().filter(n=>n.match(sel)); } querySelector(sel){ return this.querySelectorAll(sel)[0]||null; }
  addEventListener(){} closest(){ return null; } }
const byId = {};
for (const id of ['messages','rows','viewer','viewer-title','viewer-sent','viewer-back','viewer-applied','viewer-raw-request','viewer-raw-response','key-info','key-status','model-status','avg-ms','total-baht','total-turns','composer']) byId[id]=new N('div');
byId.composer.append(new N('input'), Object.assign(new N('span'),{className:'helper'})); byId.composer.dataset.state='ready';
var document = { createElement:(t)=>new N(t), createTextNode:(t)=>Object.assign(new N('#text'),{own:t}),
  querySelector:(sel)=>{ if (sel.startsWith('#')) { const [id, rest]=sel.slice(1).split(' '); const n=byId[id]??null; return rest&&n ? n.querySelector(rest) : n; } return null; },
  querySelectorAll:(sel)=>Object.values(byId).flatMap(n=>n.querySelectorAll(sel.split('[')[0])), addEventListener(){} };
var Node = N; const timers = []; var setTimeout = (f, ms)=>{ if (ms === POLL_MS) { timers.push(f); return timers.length; } f(); return 0; }; var clearTimeout = ()=>{};
async function tick(){ const f = timers.shift(); if (f) await f(); }
async function drain(){ while (timers.length) await tick(); }
var sessionStorage = { setItem(){}, getItem(){ return ''; } };
var location = { href: 'http://127.0.0.1:8768/', search: '' };
const trail = [];
var history = { state: null, replaceState(st, t, url){ trail.push(['replace', url]); location.href='http://127.0.0.1:8768'+url; location.search=url.includes('?')?'?'+url.split('?')[1].split('#')[0]:''; } };
let answers = []; const states = [];
var fetch = async (url, opts={}) => { trail.push([opts.method||'GET', url, opts.body ? JSON.parse(opts.body) : null]); states.push(byId.composer.dataset.state);
  const a = answers.shift() || { status: 404, body: { error: 'no answer scripted' } };
  return { ok: (a.status||200) < 400, status: a.status||200, json: async () => a.body }; };
function at(url){ location.href='http://127.0.0.1:8768'+url; location.search=url.includes('?')?'?'+url.split('?')[1]:''; }
function freshPage(){ CFG.rate.thb_per_usd = 34.9; fresh('s1'); trail.length=0; states.length=0; timers.length=0; answers=[]; }
function item(n, text, masked=false){ const e = { turn_id: 'run-1-'+n, turn_no: n, batch: 'run-1', batch_n: n, outcome: 'matched', response_id: 'shipping', input: { kind: 'typed', text },
  jev: { status: 200, intent: 'ask_shipping', confidence: 0.9, entities: {}, ms: 800 + n, cost_usd: 0.0002, t_sent: '2026-09-23T10:00:00.000Z', t_received: '2026-09-23T10:00:00.800Z' } };
  return { entry: e, you: { who: 'you', text, kind: 'typed', masked }, bot: [{ who: 'bot', text: 'ค่าส่ง 40 บาทค่ะ', buttons: [], variant: 'plain', response_id: 'shipping' }],
    raw: { request: { state: { customer_said: text, shop_said: 'hi', history: [] }, questions: { intent: {} } }, response: { id: 'gen-'+n } } }; }
function screen(){ return { you: byId.messages.children.filter(n => n.cls().includes('you')).map(n => [n.getAttribute('data-testid'), n.textContent, n.getAttribute('data-masked')]),
  bot: byId.messages.children.filter(n => n.cls().includes('bot')).map(n => n.getAttribute('data-testid')), bubbles: byId.messages.querySelectorAll('.bubble').length,
  rows: byId.rows.children.map(r => r.getAttribute('data-testid') || r.className), turns: byId['total-turns'].textContent, usd: byId['key-info'].getAttribute('data-total-usd'),
  avg: byId['avg-ms'].textContent, composer: byId.composer.dataset.state, input_disabled: byId.composer.querySelector('input').disabled, log: S.session.log.length, status: byId['key-status'].textContent }; }
"""

    def page(self, script):
        """Run shared.js and speed.js in the fake page, then `script` (async); it prints JSON."""
        if not shutil.which("node"):
            self.skipTest("no node")
        src = "".join((server.STATIC / "assets" / n).read_text(encoding="utf-8") + ";\n" for n in ("shared.js", "speed.js"))
        body = self.PAGE_DOM + src + "(async () => {" + script + "})().catch((e) => { console.error(e.stack); process.exit(3); });"
        prog = ("const vm=require('vm');const c={console,URL,URLSearchParams,process};vm.createContext(c);"
                f"vm.runInContext({json.dumps(body)},c);")
        r = subprocess.run(["node", "-e", prog], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        return json.loads(r.stdout)

    def test_run_starts_from_the_address_once(self):  # AC-2
        out = self.page(
            "const out = {};"
            "freshPage(); at('/?run=100&fail=1'); answers=[{ body: { refused: false, run_id: 'run-1', state: 'running' } }, { body: { run_id: 'run-1', state: 'done', next: 0, items: [] } }];"
            "await speedFromAddress(); out.hundred = trail.slice(0, 2); out.left = location.search;"
            "freshPage(); at('/?run=1000'); answers=[{ body: { refused: false, run_id: 'run-2', state: 'running' } }, { body: { run_id: 'run-2', state: 'done', next: 0, items: [] } }];"
            "await speedFromAddress(); out.thousand = trail[1];"
            "out.other = []; for (const q of ['?run=10', '?run=1,000', '?run=abc', '?run=', '?run=100.0']) { freshPage(); at('/' + q); await speedFromAddress(); out.other.push(trail.slice()); }"
            "freshPage(); at('/'); await speedFromAddress(); out.plain = trail.slice();"
            "freshPage(); at('/'); await speedFromAddress(); out.reload = trail.slice();"
            "console.log(JSON.stringify(out));")
        # ?run= leaves the address first, then the one POST asks for the run on the page's session
        self.assertEqual(out["hundred"], [["replace", "/?fail=1"], ["POST", "/api/run", {"session_id": "s1", "target": 100}]])
        self.assertEqual(out["left"], "?fail=1")
        self.assertEqual(out["thousand"], ["POST", "/api/run", {"session_id": "s1", "target": 1000}])
        for trail in out["other"]:                                   # any other value: dropped, nothing asked
            self.assertEqual([t[0] for t in trail], ["replace"], trail)
        self.assertEqual((out["plain"], out["reload"]), ([], []))    # `/` and a reload of it ask for nothing

    def test_refused_run_shows_the_cap_line_and_streams_nothing(self):  # AC-5
        out = self.page(
            "freshPage(); updateKeyInfo(); at('/?run=100');"
            "answers=[{ body: { refused: true, outcome: 'cap_reached', model_status: 'cap', estimate_usd: 0.02, room_usd: 0.00098 } }];"
            "await speedFromAddress();"
            "console.log(JSON.stringify({ trail, status: document.querySelector('#key-status').textContent,"
            " badge: document.querySelector('#model-status').getAttribute('data-status'), turns: document.querySelector('#total-turns').textContent,"
            " rows: byId.rows.children.map(r => r.className), bubbles: byId.messages.children.length, composer: byId.composer.dataset.state }));")
        self.assertEqual([t[:2] for t in out["trail"]], [["replace", "/"], ["POST", "/api/run"]])   # no GET: nothing streams
        self.assertEqual((out["status"], out["badge"], out["turns"]), ("● spend cap reached", "cap", "0"))
        self.assertEqual((out["rows"], out["bubbles"], out["composer"]), (["empty"], 0, "ready"))


    def test_run_streams_on_the_same_screen(self):  # AC-3
        out = self.page(
            "freshPage(); at('/?run=100');"
            "answers=[{ body: { refused: false, run_id: 'run-1', state: 'running' } },"
            " { body: { run_id: 'run-1', state: 'running', next: 2, items: [item(1, 'ค่าส่งเท่าไหร่คะ'), item(2, '[delivery details]', true)] } },"
            " { body: { run_id: 'run-1', state: 'done', next: 3, items: [item(3, 'มีกาแฟอะไรบ้าง')] } }];"
            "await speedFromAddress(); const during = screen(); await drain(); const after = screen();"
            "S.session.raw['run-1-3'] && openViewer(3);"
            "console.log(JSON.stringify({ trail, states, during, after, viewer: byId['viewer-sent'].textContent }));")
        self.assertEqual([t[:2] for t in out["trail"]], [["replace", "/"], ["POST", "/api/run"],
                                                         ["GET", "/api/run?session_id=s1&since=0"], ["GET", "/api/run?session_id=s1&since=2"]])
        self.assertEqual(out["states"], ["ready", "judging", "judging"])       # disabled from the first ask to the end
        d, a = out["during"], out["after"]
        self.assertEqual((d["composer"], d["input_disabled"], d["turns"], d["rows"]), ("judging", True, "2", ["turn-2", "turn-1"]))
        # the same chat column: customer bubble, then Beanly's prepared reply; masked text stays masked
        self.assertEqual(a["you"], [["you-1", "ค่าส่งเท่าไหร่คะ", "false"], ["you-2", "[delivery details]", "true"], ["you-3", "มีกาแฟอะไรบ้าง", "false"]])
        self.assertEqual(a["bot"], ["bot-run-1-1-1", "bot-run-1-2-1", "bot-run-1-3-1"])
        # the same panel, newest first; the key-info block from the log; the composer ready at the end
        self.assertEqual((a["rows"], a["turns"], a["log"], a["usd"], a["avg"]), (["turn-3", "turn-2", "turn-1"], "3", 3, "0.000600", "800 ms"))
        self.assertEqual((a["composer"], a["input_disabled"], a["status"]), ("ready", False, ""))
        self.assertIn("customer_said|มีกาแฟอะไรบ้าง", out["viewer"])         # `open` on a run row shows its request

    def test_start_over_during_a_run_stops_the_stream(self):  # AC-6
        out = self.page(
            "freshPage(); at('/?run=100');"
            "answers=[{ body: { refused: false, run_id: 'run-1', state: 'running' } },"
            " { body: { run_id: 'run-1', state: 'running', next: 1, items: [item(1, 'ค่าส่งเท่าไหร่คะ')] } },"
            " { body: { ended: true, session_id: 's1' } },"
            " { body: { session_id: 's2', new: true, turn_no: 0, transcript: [{ who: 'bot', id: 'm1', text: 'สวัสดีค่ะ Beanly นะคะ', buttons: [{ label: 'ดูเมล็ดกาแฟ', intent: 'browse' }] }], log: [], raw: {} } }];"
            "await speedFromAddress(); const during = screen(); await startOver(); await drain();"
            "console.log(JSON.stringify({ trail, during, after: screen(), id: S.session.id, running: speedRunning() }));")
        self.assertEqual(out["during"]["composer"], "judging")
        self.assertEqual([t[:2] for t in out["trail"]][-2:], [["POST", "/api/session/end"], ["GET", "/api/session?id="]])
        self.assertEqual(sum(t[1].startswith("/api/run") for t in out["trail"]), 2)   # no ask after start-over; no second run
        a = out["after"]
        self.assertEqual((out["id"], out["running"], a["bot"], a["you"], a["rows"], a["turns"], a["composer"]),
                         ("s2", False, ["bot-m1"], [], ["empty"], "0", "ready"))


    def test_a_run_of_1000_keeps_the_dom_bounded(self):  # AC-4, AC-6 (reload)
        out = self.page(
            "freshPage(); at('/?run=1000');"
            "answers=[{ body: { refused: false, run_id: 'run-1', state: 'running' } }];"
            "for (let k = 0; k < 10; k++) answers.push({ body: { run_id: 'run-1', state: k < 9 ? 'running' : 'done', next: (k + 1) * 100,"
            " items: Array.from({ length: 100 }, (_, i) => item(k * 100 + i + 1, 'ข้อความ ' + (k * 100 + i + 1))) } });"
            "await speedFromAddress(); await drain(); const run = screen();"
            "const firstYou = byId.messages.firstElementChild.getAttribute('data-testid'); const raw = Object.keys(S.session.raw).length;"
            "const log = S.session.log.map(it => it);"
            # a reload: the session view holds the chat's transcript (the greeting) and the whole log
            "answers=[{ body: { session_id: 's1', new: false, turn_no: 1000, transcript: [{ who: 'bot', id: 'm1', text: 'สวัสดีค่ะ', buttons: [] }], log, raw: {} } }];"
            "at('/'); await load('s1'); await speedFromAddress();"
            "console.log(JSON.stringify({ run, firstYou, raw, reload: screen(), asked: trail.filter(t => t[1].startsWith('/api/run')).length }));")
        run, reload = out["run"], out["reload"]
        self.assertEqual((run["bubbles"], len(run["rows"]), run["rows"][0], run["rows"][-1]), (40, 50, "turn-1000", "turn-951"))
        self.assertEqual(out["firstYou"], "you-981")                     # the newest 20 exchanges, starting on a customer bubble
        self.assertEqual((run["turns"], run["log"], out["raw"], run["composer"]), ("1000", 1000, 50, "ready"))
        self.assertEqual(run["usd"], f"{1000 * 0.0002:.6f}")
        # reloaded after the run: the chat's own transcript, the totals of the whole log, the newest 50 rows, no run
        self.assertEqual((reload["bot"], reload["you"], reload["turns"], len(reload["rows"]), reload["rows"][0], reload["rows"][-1]),
                         (["bot-m1"], [], "1000", 50, "turn-1000", "turn-951"))
        self.assertEqual(out["asked"], 11)                               # the run's POST and ten asks; nothing on reload


if __name__ == "__main__":
    unittest.main()
