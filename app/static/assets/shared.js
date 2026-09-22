/* Component library — behaviour. Loop 2c Step 7. Renders every component of 05_components.md
   and drives every state of 06_states.md, against fixtures (Jev's real S-3 answers) — never the
   API. The page composes; it never defines. Session state follows session-state.md in shape. */
"use strict";

const FX = { data: null };
const S = { session: null };
const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v; else if (k === "text") n.textContent = v; else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v);
  }
  for (const k of kids) if (k != null) n.append(k);
  return n;
};
const fmt = {
  ms: (v) => `${Math.round(v)} ms`, ms10: (v) => `${Math.round(v / 10) * 10} ms`,
  baht: (usd, d = 4) => `฿${(usd * FX.data.rate.thb_per_usd).toFixed(d)}`, usd: (v) => `$${v.toFixed(6)}`,
  conf: (v) => (v == null ? "—" : v.toFixed(2)),
};

/* ---------------- session (session-state.md, prototype-weight) ---------------- */
function newSession() {
  S.session = { id: crypto.randomUUID(), turn_no: 0, contexts: {}, focus_sku: null, pending_prompt: null, last_bot: null, live_buttons: [], options_shown: [], miss_count: 0, promos_offered: [],
    order: { lines: [], promo_applied: null, payment: null, delivery_text: null, recommend: { brew: null, roast: null }, order_code: null },
    log: [], raw: {} };
  try { sessionStorage.setItem("session_id", S.session.id); } catch (e) {}
  return S.session;
}

/* ---------------- chat column ---------------- */
function bot(text, buttons = [], variant = "plain", responseId = "") {
  const s = S.session; const id = `m${++botCount}`;
  const b = el("div", { class: `bubble bot ${variant}`, "data-testid": `bot-${id}`, "data-response-id": responseId }, el("div", { class: "name", text: "Beanly" }));
  if (typeof text === "string") b.append(document.createTextNode(text)); else b.append(text);
  $("#messages").append(b);
  // every earlier set goes dead
  document.querySelectorAll(".opt[data-live='true']").forEach((o) => o.setAttribute("data-live", "false"));
  if (buttons.length) {
    const wrap = el("div", { class: "opts", "data-message-id": id });
    buttons.slice(0, 5).forEach((btn, i) => wrap.append(el("button", { class: "opt", "data-testid": `opt-${i + 1}`, "data-intent": btn.intent, "data-live": "true", text: btn.label, onclick: () => click(btn, wrap) })));
    $("#messages").append(wrap);
  }
  s.last_bot = { id, text: typeof text === "string" ? text : text.textContent };
  s.live_buttons = buttons.map((x, i) => ({ ...x, message_id: id }));
  scrollNew();
  return id;
}
let botCount = 0;
function you(text, kind = "typed", masked = false) {
  const s = S.session;
  const b = el("div", { class: "bubble you", "data-testid": `you-${s.turn_no}`, "data-kind": kind, "data-masked": String(masked) }, document.createTextNode(text));
  if (kind === "clicked") b.append(el("span", { class: "badge", "data-testid": "badge-clicked", text: "clicked · no model call" }));
  $("#messages").append(b); scrollNew();
}
function scrollNew() { const m = $("#messages"); m.scrollTop = m.scrollHeight; }

/* ---------------- the turn: typed → fixtures stand in for Jev ---------------- */
async function send(text) {
  const s = S.session; const comp = $("#composer");
  if (!text.trim() || comp.dataset.state !== "ready") return;
  setComposer("judging"); s.turn_no += 1; you(text, "typed", !!s.contexts.ask_delivery);
  const at = new Date().toISOString();
  // Fixtures replay Jev's S-3 answers. STATE FIRST (owner ruling 2026-09-22): under a pending slot,
  // a message that carries that slot's value is `inform` by state — the entity answer stands in
  // for Jev's entity question here, parsed locally when the phrase is not in the fixture set.
  let fx = FX.data.jev[text.trim()];
  const slot = s.pending_prompt?.slot; const parsed = slot ? parseSlot(slot, text) : null;
  if (slot && parsed) fx = { intent: "inform", confidence: fx?.confidence ?? 0.99, entities: { ...(fx?.entities || {}), ...parsed }, ms: fx?.ms ?? 340, cost: fx?.cost ?? 0.000164, probs: fx?.probs || {}, by_state: true };
  const t_sent = new Date().toISOString(); await sleep(fx ? Math.min(fx.ms, 900) : 340); const t_received = new Date().toISOString();
  const entry = { turn_no: s.turn_no, at, raw_text: text, input: { kind: "typed", text: s.contexts.ask_delivery ? "[delivery details]" : text }, contexts_before: Object.keys(s.contexts), intents_in_scope: 22 + Object.values(s.contexts).flatMap((c) => c.brings || []).length + 1, applied: [] };
  if (window.PROTO_FORCE_FAIL) { entry.outcome = "model_failed"; entry.jev = { status: 200, error: "no answers" , ms: 651, cost_usd: 0 }; }
  else if (s.contexts.ask_delivery) { entry.outcome = "matched"; entry.jev = { status: 200, intent: "give_delivery_details", confidence: 0.99, entities: {}, ms: 336, cost_usd: 0.000163 }; }
  else if (!fx || fx.intent === "none" || fx.confidence < 0.45) { entry.outcome = "fallback"; entry.jev = { status: 200, intent: fx ? fx.intent : "none", confidence: fx ? fx.confidence : 0.91, entities: fx ? fx.entities : {}, ms: fx ? fx.ms : 334, cost_usd: fx ? fx.cost : 0.000163, probs: fx ? fx.probs : {} }; }
  else { entry.outcome = "matched"; entry.jev = { status: 200, intent: fx.intent, confidence: fx.confidence, entities: fx.entities, ms: fx.ms, cost_usd: fx.cost, probs: fx.probs, by_state: !!fx.by_state, awaiting: slot || null }; }
  if (entry.jev) { entry.jev.t_sent = t_sent; entry.jev.t_received = t_received; entry.jev.ms_wall = Date.parse(t_received) - Date.parse(t_sent); }
  s.raw[s.turn_no] = { request: { model: "typesafe/jev-1.13", state: { shop_said: s.last_bot?.text?.slice(0, 120), customer_said: entry.input.text, awaiting: slot || null, history: s.log.slice(-4).map((x) => ({ who: "customer", text: x.input.text })) }, questions: "intent + product · quantity · brew · roast · payment (see catalogue)" }, response: entry.jev };
  act(entry);
  delete entry.raw_text;
  s.log.push(entry); addTurnRow(entry); updateKeyInfo();
  setComposer(window.PROTO_FORCE_FAIL ? "ready" : "ready");
}
function click(btn, wrap) {
  const s = S.session; const comp = $("#composer");
  if (comp.dataset.state === "judging") return;
  if (wrap.dataset.messageId !== s.last_bot.id) return; // stale
  s.turn_no += 1; you(btn.label, "clicked");
  wrap.querySelectorAll(".opt").forEach((o) => { o.setAttribute("data-live", "false"); if (o.textContent === btn.label) o.classList.add("pressed"); });
  const entry = { turn_no: s.turn_no, at: new Date().toISOString(), input: { kind: "clicked", text: btn.label }, outcome: "matched", jev: null, intent: btn.intent, params: btn.params || {}, applied: [] };
  act(entry); s.log.push(entry); updateKeyInfo();
}
/* what the bot does with a matched intent — a prototype-weight turn loop over the fixtures */
function act(e) {
  const s = S.session; const P = FX.data.products, I = FX.data.intents;
  if (e.outcome === "model_failed") { $("#key-status").textContent = "● unreachable · HTTP 200, no answers"; bot("ขอโทษด้วยน้า ตอนนี้ติดต่อระบบไม่ได้ค่ะ กดเลือกจากด้านล่างได้เลยน้า", s.live_buttons.map(strip), "system"); return; }
  if (e.outcome === "fallback") { s.miss_count += 1; bot(FX.data.fallback[Math.min(s.miss_count, 2) - 1], s.miss_count >= 2 ? helpButtons() : s.live_buttons.map(strip), "fallback", "fallback"); return; }
  s.miss_count = 0;
  if ($("#key-status").textContent.includes("unreachable")) $("#key-status").textContent = "";  // the API is back
  const intent = e.intent || e.jev.intent; const ent = e.jev ? e.jev.entities : e.params; const ctx = { ...s.contexts };
  const productFrom = ent.product ? "jev" : (ctx.ask_quantity?.sku || ctx.offer_product?.sku) ? "context" : s.focus_sku ? "focus" : null;
  const sku = ent.product || ctx.ask_quantity?.sku || ctx.offer_product?.sku || s.focus_sku;
  if (ent.product) s.focus_sku = ent.product;
  s.contexts = {};
  const lead = () => leadNext();
  switch (intent) {
    case "greet": case "help": case "thanks_bye": bot(I[intent].response, btns(I[intent].buttons), "plain", intent); break;
    case "start_over": startOver(); break;
    case "browse_catalog": bot(I.browse_catalog.response.split(" {")[0] + " อยากดูของโรงคั่วไหนคะ? หรือพิมพ์ชื่อตัวที่สนใจมาได้เลยน้า", [b("ดอยหอม", "browse_catalog", { roaster: "DH" }), b("คั่วบ้านนา", "browse_catalog", { roaster: "KBN" }), b("เมล็ดเมือง", "browse_catalog", { roaster: "MM" })], "plain", "browse_catalog"); break;
    case "ask_recommendation": case "inform": {
      if (ent.brew) { s.order.recommend.brew = ent.brew; e.applied.push({ set: "recommend.brew", to: ent.brew }); }
      if (ent.roast) { s.order.recommend.roast = ent.roast; e.applied.push({ set: "recommend.roast", to: ent.roast }); }
      if (ent.quantity && sku) { const l = line(sku); l.qty = +ent.quantity; e.applied.push({ set: `lines[${sku}].qty`, to: +ent.quantity, product_from: productFrom }); }
      if (ent.payment) { s.order.payment = ent.payment; e.applied.push({ set: "payment", to: ent.payment }); }
      if (intent === "ask_recommendation" || ctx.ask_brew || ctx.ask_roast) recommendStep(); else lead();
      break;
    }
    case "product_info": case "ask_price": case "select_option": {
      // A pick by position resolves against the list THIS screen showed. Real Jev does this from
      // shop_said (S-3); the fixture replays a phrase's S-3 answer, so the prototype maps it here.
      let pick = sku;
      if (intent === "select_option" && s.options_shown.length && !s.options_shown.includes(ent.product || "")) {
        const t = e.input.text; const i = /สอง|หลัง|ที่ 2/.test(t) ? 1 : /สาม|ที่ 3/.test(t) ? 2 : 0;
        pick = s.options_shown[Math.min(i, s.options_shown.length - 1)]; e.applied.push({ set: "focus_sku", to: pick, product_from: "options_shown" });
      }
      if (!pick) { bot("ตัวไหนคะ? พิมพ์ชื่อหรือเลือกจากรายการได้เลยน้า", [b("ดูเมล็ดทั้งหมด", "browse_catalog")]); break; }
      s.focus_sku = pick; const p = P[pick];
      bot(`${p.name} — ${p.description} ราคา ${p.price} บาทค่ะ รับตัวนี้เลยไหมคะ?`, [b("เอาตัวนี้", "affirm"), b("ดูตัวอื่น", "browse_catalog")], "plain", intent);
      s.contexts.offer_product = { sku: pick, brings: ["affirm", "deny"] }; break;
    }
    case "ask_promotion": bot("ตอนนี้มีโปรตามนี้ค่ะ — " + Object.values(FX.data.promotions).slice(0, 4).map((x) => `📍 ${x.title}: ${x.detail}`).join("\n"), [b("ช่วยแนะนำหน่อย", "ask_recommendation"), b("ดูเมล็ดทั้งหมด", "browse_catalog")], "plain", "ask_promotion"); lead(); break;
    case "order_product": {
      if (sku) { const l = line(sku); if (ent.quantity) l.qty = +ent.quantity; e.applied.push({ set: `lines[${sku}]`, to: ent.quantity ? +ent.quantity : null, product_from: productFrom }); }
      if (ent.payment) { s.order.payment = ent.payment; e.applied.push({ set: "payment", to: ent.payment }); }
      if (sku) bot(`ได้เลยค่ะ ${P[sku].spoken_name}${ent.quantity ? ` ${ent.quantity} ถุง` : ""}${ent.payment ? (ent.payment === "cod" ? " เก็บเงินปลายทาง" : " โอนเงิน") : ""} นะคะ`); else s.focus_sku = null;
      lead(); break;
    }
    case "affirm": {
      if (ctx.offer_product) { line(ctx.offer_product.sku); e.applied.push({ set: `lines[${ctx.offer_product.sku}]`, product_from: "context" }); lead(); }
      else if (ctx.offer_promo) { applyPromo(ctx.offer_promo); e.applied.push({ set: "promo_applied", to: ctx.offer_promo.promo_id }); bot("ได้เลยค่ะ ใส่ให้แล้วนะคะ"); lead(); }
      else if (ctx.confirm_order) { s.order.order_code = `BEAN-2609-${String(1000 + s.turn_no).slice(1)}`; e.applied.push({ set: "order_code", to: s.order.order_code }); bot(`ขอบคุณคุณพี่มากค่ะ ☕ รหัสออเดอร์ ${s.order.order_code} ${s.order.payment === "transfer" ? "โอนแล้วรบกวน reply slip ด้วยน้า — เดโมนี้ไม่มีบัญชีจริงค่ะ" : `เตรียมชำระ ${totals().total.toLocaleString()} บาทตอนรับของน้า`}`, [b("เริ่มใหม่", "start_over")], "plain", "done"); }
      else bot("ได้เลยค่ะ", helpButtons()); break;
    }
    case "deny": {
      if (ctx.offer_product) { bot("ได้ค่ะ ลองดูตัวอื่นไหมคะ?", [b("ดูเมล็ดทั้งหมด", "browse_catalog"), b("ช่วยแนะนำหน่อย", "ask_recommendation")]); }
      else if (ctx.offer_promo) { bot("ได้เลยค่ะ เอาเท่าเดิมนะคะ"); lead(); }
      else if (ctx.confirm_order) { bot("ได้เลยค่ะ อยากแก้ส่วนไหนคะ? หรือจะคิดดูก่อนก็ได้น้า", [b("เปลี่ยนสินค้า", "change_order"), b("เปลี่ยนจำนวน", "change_order"), b("เปลี่ยนวิธีชำระ", "change_order")]); }
      else bot("ได้ค่ะ", helpButtons()); break;
    }
    case "give_delivery_details": s.order.delivery_text = e.input.kind === "clicked" ? "สมชาย ใจดี 123/4 ซอยสุขุมวิท 50 คลองเตย กรุงเทพ 10110 โทร 081-000-0000" : e.raw_text; e.applied.push({ set: "delivery_text", to: "[kept as typed]" }); lead(); break;
    case "change_order": {
      // A change names a product that is not in the order → it applies to the line in focus
      // (session-state.md: Jev, then context, then focus_sku). The fixture can replay a product
      // from S-3's own shop_said, so this rule matters in the prototype too.
      let target = sku, from = productFrom;
      if (target && !s.order.lines.some((l) => l.sku === target)) { target = (s.order.lines.find((l) => l.sku === s.focus_sku) || s.order.lines[0])?.sku; from = "focus"; }
      if (ent.quantity && target) { line(target).qty = +ent.quantity; e.applied.push({ set: `lines[${target}].qty`, to: +ent.quantity, product_from: from }); }
      if (ent.payment) { s.order.payment = ent.payment; e.applied.push({ set: "payment", to: ent.payment }); }
      if (!ent.quantity && !ent.payment && !ent.product) { bot("ได้เลยค่ะ อยากแก้ส่วนไหนคะ?", [b("เปลี่ยนสินค้า", "browse_catalog"), b("เปลี่ยนจำนวน", "inform"), b("เปลี่ยนวิธีชำระ", "inform")]); break; }
      bot("ได้เลยค่ะ แก้ให้แล้วนะคะ"); lead(); break;
    }
    case "cancel_order": s.order.lines = []; s.order.payment = null; s.order.delivery_text = null; s.order.promo_applied = null; s.focus_sku = null; e.applied.push({ set: "order", to: "cleared" }); bot(I.cancel_order.response, btns(I.cancel_order.buttons), "plain", "cancel_order"); break;
    case "view_order": bot(s.order.lines.length ? readback(false) : "ตอนนี้ยังไม่มีรายการในออเดอร์ค่ะ"); lead(); break;
    default: if (intent.startsWith("faq.")) { const id = { shipping_fee: "FAQ-01", payment_methods: "FAQ-02", roast_levels: "FAQ-03", storage: "FAQ-04", delivery_time: "FAQ-05", grinding: "FAQ-06", minimum_order: "FAQ-07", freshness: "FAQ-08" }[intent.slice(4)]; bot(FX.data.faq[id].answer + (id === "FAQ-06" ? " กาแฟดีต้องคู่ grind ที่ตรงเสมอค่ะ" : ""), [], "plain", intent); resume(ctx); } else bot("ได้ค่ะ", helpButtons());
  }
}
function parseSlot(slot, t) {
  const num = (t.match(/(\d+)\s*ถุง/) || t.match(/^\s*(\d+)\s*$/))?.[1];
  const words = { "1": /หนึ่ง|ถุงเดียว/, "2": /สอง/, "3": /สาม/ };
  if (slot === "quantity") { const n = num || Object.keys(words).find((k) => words[k].test(t)); return n ? { quantity: n } : null; }
  if (slot === "brew") { const m = /เอสเปรส|ลาเต้|นม|คาปู/.test(t) ? "espresso_milk" : /ดริป|drip|pour|เฟรนช์|โมก้า|filter|กรอง/.test(t) ? "filter" : /โคลด์|cold|สกัดเย็น/.test(t) ? "cold_brew" : /ไม่แน่ใจ|แล้วแต่|แนะนำ/.test(t) ? "any" : null; return m ? { brew: m } : null; }
  if (slot === "roast") { const m = /อ่อน/.test(t) ? "light" : /กลาง/.test(t) ? "medium" : /เข้ม/.test(t) ? "dark" : /ดีแคฟ|คาเฟอีน/.test(t) ? "decaf" : /แล้วแต่|แนะนำ/.test(t) ? "any" : null; return m ? { roast: m } : null; }
  if (slot === "payment") { const m = /โอน/.test(t) ? "transfer" : /ปลายทาง|cod/i.test(t) ? "cod" : null; return m ? { payment: m } : null; }
  return null;
}
function strip(x) { return { label: x.label, intent: x.intent, params: x.params }; }
function b(label, intent, params = {}) { return { label, intent, params }; }
function btns(list) { return list.map((x) => { const [label, intent] = x.split("→"); return b(label.trim(), (intent || "help").trim()); }); }
function helpButtons() { return [b("ช่วยแนะนำหน่อย", "ask_recommendation"), b("ดูเมล็ดทั้งหมด", "browse_catalog"), b("มีโปรอะไรบ้าง", "ask_promotion"), b("ค่าส่งเท่าไหร่", "faq.shipping_fee")]; }
function line(sku) { const s = S.session; let l = s.order.lines.find((x) => x.sku === sku); if (!l) { l = { sku, qty: null, added_by: "customer" }; s.order.lines.push(l); } s.focus_sku = sku; return l; }
const REC = { espresso_milk: { light: ["DH-002", "MM-002"], medium: ["KBN-001", "DH-002"], dark: ["KBN-002", "MM-004"], any: ["KBN-001", "DH-002"] }, filter: { light: ["DH-001", "MM-001"], medium: ["MM-002", "DH-002"], dark: ["MM-004", "KBN-002"], any: ["MM-001", "MM-002"] }, cold_brew: { light: ["DH-003", "MM-003"], medium: ["MM-003", "DH-003"], dark: ["MM-003", "MM-004"], any: ["MM-003", "DH-003"] }, any: { light: ["DH-001", "MM-001"], medium: ["KBN-001", "DH-002"], dark: ["KBN-002", "MM-004"], any: ["KBN-001", "DH-002"] } };
function recommendStep() {
  const s = S.session; const r = s.order.recommend; const P = FX.data.products;
  if (!r.brew) { bot("เยี่ยมเลยค่ะ — งั้นรบกวนถามต่ออีกนิดน้า จะได้ recommend ตรงค่ะ ปกติชงแบบไหนคะ?", [b("เอสเปรสโซ่ / เมนูนม", "inform", { brew: "espresso_milk" }), b("ดริป / pour-over", "inform", { brew: "filter" }), b("โคลด์บรูว์", "inform", { brew: "cold_brew" }), b("ยังไม่แน่ใจ", "inform", { brew: "any" })], "plain", "ask_brew"); s.contexts.ask_brew = {}; s.pending_prompt = { slot: "brew" }; return; }
  if (!r.roast) { bot("ชอบคั่วระดับไหนคะ?", [b("คั่วอ่อน", "inform", { roast: "light" }), b("คั่วกลาง", "inform", { roast: "medium" }), b("คั่วเข้ม", "inform", { roast: "dark" }), b("ไม่มีคาเฟอีน", "inform", { roast: "decaf" }), b("แล้วแต่แนะนำ", "inform", { roast: "any" })], "plain", "ask_roast"); s.contexts.ask_roast = {}; s.pending_prompt = { slot: "roast" }; return; }
  const pair = r.roast === "decaf" ? ["KBN-003"] : (REC[r.brew] || REC.any)[r.roast] || REC.any.any;
  const [A, B] = pair.map((k) => P[k]);
  bot(`story bean ก่อนนะคะ — ตัวแรก ${A.spoken_name}: ${A.note}${B ? ` อีกตัว ${B.spoken_name}: ${B.note}` : ""} สนใจตัวไหนคะ?`, [...pair.map((k) => b(P[k].spoken_name, "select_option", { product: k })), b("ดูตัวอื่น", "browse_catalog")], "plain", "recommend");
  s.options_shown = pair; s.contexts.options_shown = { skus: pair, brings: ["select_option"] }; s.order.recommend = { brew: null, roast: null };
}
function leadNext() {
  const s = S.session; const o = s.order; const P = FX.data.products;
  const l = o.lines[o.lines.length - 1];
  if (!l) { recommendStep(); return; }
  if (l.qty == null) { bot("รับกี่ถุงดีคะ? สั่งครบ 5 ถุงส่งฟรีน้า", [1, 2, 3, 5].map((n) => b(`${n} ถุง`, "inform", { quantity: String(n) })), "plain", "ask_quantity"); s.contexts.ask_quantity = { sku: l.sku }; s.pending_prompt = { slot: "quantity", sku: l.sku }; return; }
  const promo = fitPromo(); if (promo && !s.promos_offered.includes(promo.id)) { s.promos_offered.push(promo.id); bot(`${FX.data.promotions[promo.id].detail} สนใจไหมคะ? ไม่ urgent น้า ลองดูก่อนได้`, [b(promo.take, "affirm"), b("ไม่เป็นไร เอาเท่าเดิม", "deny")], "plain", "promo.offer"); s.contexts.offer_promo = { promo_id: promo.id, effect: promo.effect, brings: ["affirm", "deny"] }; s.pending_prompt = { slot: "promotion" }; return; }
  if (!o.payment) { bot(`ค่าส่ง ${totals().shipping === 0 ? "ฟรี" : totals().shipping + " บาท"} ค่ะ ชำระแบบไหนสะดวกคะ? โอนผ่านบัญชีธนาคาร หรือเก็บเงินปลายทาง (มีค่าบริการเพิ่ม 30 บาท)`, [b("โอนผ่านธนาคาร", "inform", { payment: "transfer" }), b("เก็บเงินปลายทาง", "inform", { payment: "cod" })], "plain", "ask_payment"); s.contexts.ask_payment = {}; s.pending_prompt = { slot: "payment" }; return; }
  if (!o.delivery_text) { bot("รบกวนขอชื่อ ที่อยู่ และเบอร์โทรสำหรับจัดส่งค่ะ — เดโมนี้ไม่ส่งของจริง ใช้ข้อมูลสมมติได้เลยน้า", [b("ใช้ข้อมูลตัวอย่าง", "give_delivery_details")], "plain", "ask_delivery"); s.contexts.ask_delivery = { brings: ["give_delivery_details"] }; s.pending_prompt = { slot: "delivery" }; return; }
  if (!o.order_code) { bot(readback(true), [b("ยืนยัน", "affirm"), b("ขอแก้ไข", "deny")], "read-back", "confirm"); s.contexts.confirm_order = { order_hash: JSON.stringify(o), brings: ["affirm", "deny"] }; s.pending_prompt = { slot: "confirmation" }; }
}
function resume(ctx) { const s = S.session; s.contexts = ctx; if (s.pending_prompt) { const pp = s.pending_prompt; s.contexts = {}; leadNext(); } }
function fitPromo() {
  const o = S.session.order; const l = o.lines[0]; if (!l) return null; const q = l.qty || 0;
  if (l.sku === "KBN-001" && q < 6) return { id: "PROMO-03", take: "เพิ่มเป็น 6 ถุง", effect: { set_qty: 6 } };
  if (l.sku === "DH-001" || l.sku === "DH-003") return { id: "PROMO-02", take: `เพิ่ม${l.sku === "DH-001" ? "เนเชอรัล แอนแอโรบิก" : "เกอิชา"}`, effect: { add_line: l.sku === "DH-001" ? "DH-003" : "DH-001" } };
  if (l.sku === "KBN-003" && q < 2) return { id: "PROMO-04", take: "เพิ่มเป็น 2 ถุง", effect: { set_qty: 2 } };
  if (q < 5) return { id: "PROMO-01", take: "เพิ่มเป็น 5 ถุง", effect: { set_qty: 5 } };
  return null;
}
function applyPromo(p) { const o = S.session.order; if (p.effect.set_qty) o.lines[0].qty = p.effect.set_qty; if (p.effect.add_line) o.lines.push({ sku: p.effect.add_line, qty: 1, added_by: p.promo_id }); o.promo_applied = p.promo_id; }
function totals() {
  const o = S.session.order; const P = FX.data.products; let sub = 0, bags = 0;
  for (const l of o.lines) { sub += (+P[l.sku].price) * (l.qty || 0); bags += l.qty || 0; }
  let discount = 0; if (o.promo_applied === "PROMO-02") discount = 80; if (o.promo_applied === "PROMO-03") discount = 30 * (o.lines[0].qty || 0);
  const shipping = bags >= 5 ? 0 : 100; const cod = o.payment === "cod" ? 30 : 0;
  return { sub, discount, shipping, cod, total: sub - discount + shipping + cod };
}
function readback(ask) {
  const o = S.session.order; const P = FX.data.products; const t = totals();
  const g = el("div", { class: "readback", "data-testid": "readback" });
  const row = (k, v, cls = "") => { g.append(el("span", { class: cls, text: k }), el("span", { class: cls, text: v })); };
  o.lines.forEach((l) => row(`${P[l.sku].spoken_name} × ${l.qty} ถุง`, `${((+P[l.sku].price) * l.qty).toLocaleString()} บาท`));
  if (t.discount) row(`ส่วนลด ${FX.data.promotions[o.promo_applied].title}`, `−${t.discount} บาท`);
  row("ค่าส่ง", t.shipping ? `${t.shipping} บาท` : "ฟรี"); if (t.cod) row("ค่าบริการเก็บเงินปลายทาง", "30 บาท");
  row("รวม", `${t.total.toLocaleString()} บาท`, "total"); g.lastChild.setAttribute("data-testid", "readback-total"); g.lastChild.setAttribute("data-value", t.total);
  const wrap = el("div", {}, document.createTextNode("สรุปออเดอร์ค่ะ"), g);
  if (ask) wrap.append(document.createTextNode(`จัดส่งที่: ${o.delivery_text}\nรบกวนคุณพี่ตรวจรายการอีกครั้ง แล้วยืนยันให้แอดน้า 🙏🏻`));
  return wrap;
}

/* ---------------- panel ---------------- */
function addTurnRow(e) {
  const rows = $("#rows"); $("#rows .empty")?.remove(); const n = e.turn_no; const j = e.jev;
  const row = el("div", { class: "turn arrived", "data-testid": `turn-${n}`, "data-outcome": e.outcome, "data-at": e.at || "" });
  row.append(el("div", { class: "t1" }, el("span", { class: "n", text: `#${n}` }), document.createTextNode(e.input.text)));
  const kv = (k, v, c, cls = "") => el("div", { class: `kv ${cls}` }, el("span", { class: "k", text: k }), el("span", { class: "v", text: v }), el("span", { class: "c", text: c || "" }));
  if (e.outcome === "model_failed") row.append(kv("intent", "MODEL FAILED · HTTP 200, no answers", "", "intent"));
  else { const iv = kv(e.outcome === "fallback" ? "fallback" : "intent", j.intent + (j.by_state ? "  · by state (awaiting " + j.awaiting + ")" : ""), fmt.conf(j.confidence), "intent"); iv.querySelector(".v").setAttribute("data-testid", `turn-${n}-intent`); iv.querySelector(".c").setAttribute("data-testid", `turn-${n}-confidence`); iv.querySelector(".c").setAttribute("data-value", j.confidence); row.append(iv); }
  const vals = j && Object.entries(j.entities || {}).map(([k, v]) => `${k} ${v}`).join(" · ");
  row.append(kv("values", vals || "—", ""));
  for (const a of e.applied || []) if (a.product_from && a.product_from !== "jev") row.append(el("div", { class: "prov", "data-testid": `turn-${n}-prov-product`, "data-source": a.product_from, text: `product ${a.set.match(/\[(.+?)\]/)?.[1] || a.to || ""}  ← from ${a.product_from}${a.product_from === "options_shown" && j?.entities?.product ? ` (fixture replayed ${j.entities.product})` : ""}` }));
  const t4 = el("div", { class: "t4" });
  t4.append(el("span", { "data-testid": `turn-${n}-ms`, "data-value": j?.ms ?? 0, text: j ? fmt.ms(j.ms) : "—" }), el("span", { "data-testid": `turn-${n}-baht`, "data-value": j?.cost_usd ?? 0, text: j && j.cost_usd ? fmt.baht(j.cost_usd) : "฿0" }), el("span", { "data-testid": `turn-${n}-usd`, text: j && j.cost_usd ? fmt.usd(j.cost_usd) : "—" }));
  t4.append(el("button", { class: "open", "data-testid": `turn-${n}-open`, text: "open", onclick: () => openViewer(n) }));
  row.append(t4); rows.prepend(row);
}
function updateKeyInfo() {
  const s = S.session; const typed = s.log.filter((e) => e.jev && e.outcome !== "model_failed");
  const avg = typed.length ? typed.reduce((a, e) => a + e.jev.ms, 0) / typed.length : null;
  const usd = typed.reduce((a, e) => a + (e.jev.cost_usd || 0), 0);
  set("#avg-ms", avg == null ? "—" : fmt.ms10(avg), avg ?? 0); set("#total-baht", fmt.baht(usd, 3), usd); set("#total-turns", String(s.turn_no), s.turn_no);
  $("#key-info").setAttribute("data-total-usd", usd.toFixed(6));
}
function set(sel, text, value) { const n = $(sel); if (!n) return; n.textContent = text; n.setAttribute("data-value", value); n.classList.remove("bump"); void n.offsetWidth; n.classList.add("bump"); }
function openViewer(n) {
  const s = S.session; const e = s.log.find((x) => x.turn_no === n); const raw = s.raw[n] || {}; const v = $("#viewer");
  $("#viewer-title").textContent = `Turn #${n} · ${e.input.text}`;
  const dl = (pairs) => { const d = el("dl"); pairs.forEach(([k, val]) => d.append(el("dt", { text: k }), el("dd", { text: val }))); return d; };
  $("#viewer-sent").replaceChildren(dl([["shop_said", raw.request?.state?.shop_said || "—"], ["customer_said", e.input.text], ["contexts", (e.contexts_before || []).join(", ") || "none"], ["intents in scope", String(e.intents_in_scope || "—")], ["entity questions", "product · quantity · brew · roast · payment"]]), el("details", {}, el("summary", { text: "raw request" }), el("pre", { "data-testid": "viewer-raw-request", text: JSON.stringify(raw.request, null, 1) })));
  const j = e.jev || {};
  $("#viewer-back").replaceChildren(dl([["intent", j.intent ? `${j.intent} ${fmt.conf(j.confidence)}` + (j.probs ? " · " + Object.entries(j.probs).slice(1, 3).map(([k, v]) => `${k} ${v.toFixed(2)}`).join(" · ") : "") : "—"], ...Object.entries(j.entities || {}).map(([k, val]) => [k, val]), ["cost", j.cost_usd ? `${fmt.usd(j.cost_usd)} → ${fmt.baht(j.cost_usd)}` : "—"], ["latency · status", `${j.ms ?? "—"} ms · ${j.status ?? "—"}`], ["t_sent → t_received", j.t_sent ? `${j.t_sent.slice(11, 23)} → ${j.t_received.slice(11, 23)} (${j.ms_wall} ms wall)` : "—"], ["received at", e.at || "—"]]), el("details", {}, el("summary", { text: "raw response" }), el("pre", { "data-testid": "viewer-raw-response", text: JSON.stringify(raw.response, null, 1) })));
  $("#viewer-applied").replaceChildren(dl((e.applied || []).length ? e.applied.map((a) => [a.set, `${a.to ?? ""}${a.product_from ? `  (product from ${a.product_from})` : ""}`]) : [["—", "nothing written"]]));
  v.style.bottom = `${$("#key-info").offsetHeight}px`;  // the drawer stops above the key-info block — never covers it
  v.style.display = "block"; setTimeout(() => v.setAttribute("data-open", "true"), 20); document.querySelector(`[data-testid="turn-${n}"]`)?.setAttribute("data-open", "true");
}
function closeViewer() { const v = $("#viewer"); v.setAttribute("data-open", "false"); setTimeout(() => { if (v.getAttribute("data-open") === "false") v.style.display = "none"; }, 220); document.querySelectorAll(".turn[data-open]").forEach((r) => r.removeAttribute("data-open")); }

/* ---------------- composer, start over, boot ---------------- */
function setComposer(state) { const c = $("#composer"); if (!c) return; c.dataset.state = state; c.querySelector("input").disabled = state === "judging"; c.querySelector(".helper").textContent = state === "judging" ? "Beanly กำลังคิด…" : state === "paused" ? "paused" : ""; }
function startOver() { if (typeof speedReset === "function") speedReset(); botCount = 0; $("#messages")?.replaceChildren(); $("#rows").replaceChildren(el("div", { class: "empty", text: $("#messages") ? "Type something — clicks don't call the model." : "Each answered message adds a row; the last 50 stay on screen." })); $("#key-status").textContent = ""; newSession(); updateKeyInfo(); if ($("#messages")) welcome(); }
function welcome() { const I = FX.data.intents.greet; bot(I.response, btns(I.buttons), "plain", "welcome"); }
/* Story 1.1: the rate, its date and the model id come from the server (`/api/config`), not from
   the fixture file. The fixture's `rate` is only a fallback for when the server has none — which
   it never does: it refuses to start without one. The chat itself still runs on fixtures until
   Story 1.3 wires the turn loop. */
async function loadConfig() {
  try {
    const r = await fetch("/api/config", { cache: "no-store" });
    if (!r.ok) throw new Error(`config ${r.status}`);
    const c = await r.json();
    return { rate: { thb_per_usd: c.thb_per_usd, date: c.rate_date, source: "server" }, model: c.model };
  } catch (e) { console.warn("config from the server failed; using the fixture rate", e); return null; }
}
async function boot(opts = {}) {
  const [fx, cfg] = await Promise.all([(await fetch("assets/fixtures.json")).json(), loadConfig()]);
  FX.data = fx;
  if (cfg) { FX.data.rate = cfg.rate; const m = $("#model-id"); if (m && cfg.model) m.textContent = cfg.model.split("/").pop(); }
  $("#rate").textContent = `฿${FX.data.rate.thb_per_usd}/$ (${FX.data.rate.date.slice(5)})`;
  $("#rate").setAttribute("data-source", FX.data.rate.source || "fixture");
  $('[data-testid="band-bottom"]').append(el("div", { class: "proto-mark", text: "PROTOTYPE · FIXTURES, NOT JEV" }));
  $("#composer input")?.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); const i = ev.target; const t = i.value; i.value = ""; send(t); } });
  $("#send")?.addEventListener("click", () => { const i = $("#composer input"); const t = i.value; i.value = ""; send(t); });
  $("#start-over").addEventListener("click", startOver);
  $("#viewer-close").addEventListener("click", closeViewer);
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeViewer(); });
  startOver();
  if (opts.after) opts.after();
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
