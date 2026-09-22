/* Component library — the SpeedTest organism (05_components.md), as ruled 2026-09-22: it runs ON
   the W-001 screen. A header popover chooses 100 / 1,000 and starts; the messages stream as chat
   (customer bubble + Beanly's prepared reply), the panel rows stream beside them, the key-info
   block counts, one status line sits above the composer. In the prototype the run is SIMULATED
   from Spike S-4's measured shape (32 in flight, ~79/s) over the fixture phrases — each answer is a
   real S-3 answer. The real build sends real requests through the server. Same tokens either way. */
"use strict";
const SPEED = { target: 100, phase: "ready", answered: 0, correct: 0, errors: 0, usd: 0, t0: 0, elapsed: 0, timer: null };
const RATE = 79; // answers per second at 32 in flight — S-4

function speedMount() {
  const header = $(".chat-header"); const spacer = header.querySelector(".spacer");
  const pop = el("div", { class: "speed-pop", id: "speed-pop", "data-testid": "speed-pop", hidden: "" },
    el("div", { class: "chooser", id: "speed-chooser", "data-testid": "speed-chooser" },
      el("button", { class: "opt pressed", "data-n": "100", "data-testid": "speed-target-100", text: "100 rehearsal", onclick: () => speedChoose(100) }),
      el("button", { class: "opt", "data-n": "1000", "data-testid": "speed-target-1000", text: "1,000 demo", onclick: () => speedChoose(1000) })),
    el("div", { class: "note", text: "messages from the intent catalogue's test set · 32 in flight · full catalogue each" }),
    el("button", { class: "btn-start", id: "speed-start", "data-testid": "speed-start", text: "Start", onclick: speedStart }));
  const btn = el("button", { class: "btn-quiet", id: "speed-test-open", "data-testid": "speed-test-open", text: "speed test ▾", onclick: () => { pop.hidden = !pop.hidden; } });
  spacer.after(btn); header.append(pop);
  const status = el("div", { class: "speed-status", id: "speed-status", "data-testid": "speed-test", "data-phase": "ready", hidden: "" },
    el("span", { id: "speed-count", "data-testid": "speed-count" }), document.createTextNode(" / "), el("span", { id: "speed-target", "data-testid": "speed-target" }),
    document.createTextNode(" · "), el("span", { id: "speed-elapsed", "data-testid": "speed-elapsed-ms" }), document.createTextNode(" · "), el("span", { id: "speed-per-s", "data-testid": "speed-per-s" }),
    document.createTextNode(" · "), el("span", { id: "speed-correct", "data-testid": "speed-correct" }), el("span", { id: "speed-errors", "data-testid": "speed-errors" }),
    el("span", { id: "speed-summary", "data-testid": "speed-summary" }));
  $("#composer").before(status);
  speedRender();
}
function speedChoose(n) { if (SPEED.phase !== "ready") return; SPEED.target = n; document.querySelectorAll("#speed-chooser .opt").forEach((o) => o.classList.toggle("pressed", +o.dataset.n === n)); speedRender(); }
function speedRender() {
  const st = $("#speed-status"); if (!st) return; const ph = SPEED.phase; st.dataset.phase = ph; st.hidden = ph === "ready";
  const sec = (ms) => (ms / 1000).toFixed(1);
  const elapsed = ph === "running" ? performance.now() - SPEED.t0 : SPEED.elapsed;
  const set2 = (id, text, v) => { const n = $(id); n.textContent = text; n.setAttribute("data-value", v); };
  set2("#speed-count", `speed test · ${SPEED.answered.toLocaleString()}`, SPEED.answered); set2("#speed-target", SPEED.target.toLocaleString(), SPEED.target);
  set2("#speed-elapsed", `${sec(elapsed)} s`, Math.round(elapsed));
  const perS = elapsed > 300 ? SPEED.answered / (elapsed / 1000) : 0; set2("#speed-per-s", `${perS.toFixed(0)}/s`, perS.toFixed(1));
  set2("#speed-correct", `${SPEED.correct} ✓`, SPEED.correct); set2("#speed-errors", SPEED.errors ? ` · ${SPEED.errors} errors` : "", SPEED.errors);
  $("#speed-summary").textContent = ph === "done" ? ` — ${SPEED.target.toLocaleString()} answered in ${sec(SPEED.elapsed)} s · ${(SPEED.target / (SPEED.elapsed / 1000)).toFixed(0)}/s · ${SPEED.correct} correct` : "";  // cost lives in KeyInfo, not here
  const open = $("#speed-test-open"); if (open) open.disabled = ph === "running";
}
function reply(fx) {
  const I = FX.data.intents[fx.intent]; if (!I) return FX.data.fallback[0];
  if (fx.intent.startsWith("faq.")) { const id = { shipping_fee: "FAQ-01", payment_methods: "FAQ-02", roast_levels: "FAQ-03", storage: "FAQ-04", delivery_time: "FAQ-05", grinding: "FAQ-06", minimum_order: "FAQ-07", freshness: "FAQ-08" }[fx.intent.slice(4)]; return FX.data.faq[id].answer; }
  const p = fx.entities?.product && FX.data.products[fx.entities.product];
  if (p && (fx.intent === "product_info" || fx.intent === "ask_price" || fx.intent === "select_option")) return `${p.spoken_name} ถุงละ ${p.price} บาทค่ะ — ${p.note}`;
  if (fx.intent === "order_product" && p) return `ได้เลยค่ะ ${p.spoken_name}${fx.entities.quantity ? ` ${fx.entities.quantity} ถุง` : ""} นะคะ รับกี่ถุงดีคะ?`;
  const clean = I.response.replace(/\{[^}]*\}/g, "").replace(/\(.*?\)/g, "").trim();
  return clean.length > 90 ? clean.slice(0, 90) + "…" : clean || "ได้เลยค่ะ";
}
function speedStart() {
  if (SPEED.phase !== "ready") return;
  $("#speed-pop").hidden = true; const phrases = Object.keys(FX.data.jev);
  Object.assign(SPEED, { phase: "running", t0: performance.now(), answered: 0, correct: 0, errors: 0, usd: 0 });
  setComposer("paused"); document.querySelectorAll('.opt[data-live="true"]').forEach((o) => o.setAttribute("data-live", "false"));
  SPEED.timer = setInterval(() => {  // time-based, not tick-based: background tabs throttle timers
    const due = Math.min(SPEED.target, Math.floor(((performance.now() - SPEED.t0) / 1000) * RATE));
    let rendered = 0;
    while (SPEED.answered < due) {
      const text = phrases[SPEED.answered % phrases.length]; const fx = FX.data.jev[text];
      SPEED.answered += 1; SPEED.usd += fx.cost; if (fx.intent === fx.expected) SPEED.correct += 1;
      const s = S.session; s.turn_no += 1;
      const shown = fx.intent === "give_delivery_details" ? "[delivery details]" : text;  // masked, as everywhere (NFR10)
      const at = new Date().toISOString();
      const e = { turn_no: s.turn_no, at, input: { kind: "typed", text: shown }, outcome: fx.intent === "none" || fx.confidence < 0.45 ? "fallback" : "matched",
        jev: { status: 200, intent: fx.intent, confidence: fx.confidence, entities: fx.entities, ms: fx.ms, cost_usd: fx.cost, probs: fx.probs, t_sent: at, t_received: new Date(Date.parse(at) + fx.ms).toISOString(), ms_wall: fx.ms }, applied: [], contexts_before: fx.contexts, intents_in_scope: 23 };
      s.log.push(e); s.raw[s.turn_no] = { request: { state: { shop_said: "…", customer_said: shown, awaiting: null } }, response: e.jev };
      if (rendered < 6) {  // stream what a viewer can see; every answer is in the log
        rendered += 1; you(shown, "typed", fx.intent === "give_delivery_details");
        const b = el("div", { class: `bubble bot ${e.outcome === "fallback" ? "fallback" : "plain"}`, "data-response-id": fx.intent }, el("div", { class: "name", text: "Beanly" }), document.createTextNode(e.outcome === "fallback" ? FX.data.fallback[0] : reply(fx)));
        $("#messages").append(b); addTurnRow(e);
      }
    }
    const msgs = $("#messages"); while (msgs.children.length > 80) msgs.firstChild.remove();
    const rows = $("#rows"); while (rows.children.length > 50) rows.lastChild.remove();
    scrollNew(); updateKeyInfo(); speedRender();
    if (SPEED.answered >= SPEED.target) { clearInterval(SPEED.timer); SPEED.elapsed = performance.now() - SPEED.t0; SPEED.phase = "done"; speedRender(); setComposer("ready"); }
  }, 50);
}
function speedReset() { clearInterval(SPEED.timer); Object.assign(SPEED, { phase: "ready", answered: 0, correct: 0, errors: 0, usd: 0, elapsed: 0 }); speedRender(); }
