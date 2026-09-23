/* Component library — behaviour. Loop 2c Step 7 rendered every component of 05_components.md and
   drove every state of 06_states.md against fixtures. Story 1.3b re-points the same library at the
   server: a typed sentence is `POST /api/turn`, a click is the same with the button, the page opens
   on `GET /api/session`. The browser keeps `session_id` and a render cache — never the order, never
   the key (session-state.md § Where it lives). The page composes; it never defines. */
"use strict";

const CFG = { rate: { thb_per_usd: 0, date: "", source: "" }, model: "" };
const S = { session: null };   // the view cache: { id, turn_no, log: [entry…], raw: { <turn_id>: {request, response} } }
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
  baht: (usd, d = 4) => `฿${(usd * CFG.rate.thb_per_usd).toFixed(d)}`, usd: (v) => `$${v.toFixed(6)}`,
  conf: (v) => (v == null ? "—" : v.toFixed(2)),
};

/* ---------------- the server ---------------- */
const post = (body) => ({ method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
async function unwrap(r) {
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(data.error || `HTTP ${r.status}`); e.status = r.status; throw e; }
  return data;
}
function rememberId(id) { try { sessionStorage.setItem("session_id", id); } catch (e) {} }
function storedId() { try { return sessionStorage.getItem("session_id") || ""; } catch (e) { return ""; } }

/* ---------------- chat column ---------------- */
let botCount = 0, youCount = 0;
/* A bot bubble as the server sends it: {id, text, buttons:[{label,intent,params}], variant, response_id,
   readback?}. Its `id` is the message_id a click names; every earlier set of buttons goes dead. A
   read-back carries its grid as data (Story 1.4's Delta): {rows: [[label, amount]], total, delivery_text,
   lead, tail} — the page draws the grid from it and leaves `text` (the same read-back as one text) to Jev. */
function bot(m) {
  botCount += 1;
  const id = m.id; const buttons = m.buttons || [];
  const b = el("div", { class: `bubble bot ${m.variant || "plain"}`, "data-testid": `bot-${id}`, "data-response-id": m.response_id || "" }, el("div", { class: "name", text: "Beanly" }));
  if (m.readback) b.append(...readbackNodes(m.readback)); else b.append(document.createTextNode(m.text || ""));
  $("#messages").append(b);
  document.querySelectorAll(".opt[data-live='true']").forEach((o) => o.setAttribute("data-live", "false"));
  let wrap = null;
  if (buttons.length) {
    wrap = el("div", { class: "opts", "data-message-id": id });
    buttons.slice(0, 5).forEach((btn, i) => wrap.append(el("button", { class: "opt", "data-testid": `opt-${i + 1}`, "data-intent": btn.intent, "data-live": "true", text: btn.label, onclick: (ev) => click({ label: btn.label, intent: btn.intent, params: btn.params || {}, message_id: id }, ev.currentTarget) })));
    $("#messages").append(wrap);
  }
  scrollNew();
  return wrap;
}
/* A customer bubble as the server sends it: {text, kind: typed|clicked, masked}. Numbered by its
   place among the customer's bubbles (a miss does not advance the server's turn_no). */
function you(m) {
  youCount += 1;
  const b = el("div", { class: "bubble you", "data-testid": `you-${youCount}`, "data-kind": m.kind, "data-masked": String(!!m.masked) }, document.createTextNode(m.text || ""));
  if (m.kind === "clicked") b.append(el("span", { class: "badge", "data-testid": "badge-clicked", text: "clicked · no model call" }));
  $("#messages").append(b); scrollNew();
}
/* ReadBack (05_components.md): the prototype's grid — one row per line, the discount, the fee, the COD
   fee, the total in bold — from the server's data. The last row is the total, with `data-value`. */
function readbackNodes(rb) {
  const g = el("div", { class: "readback", "data-testid": "readback" });
  const rows = rb.rows || [];
  rows.forEach(([k, v], i) => {
    if (i < rows.length - 1) g.append(el("span", { text: k }), el("span", { text: v }));
    else g.append(el("span", { class: "total", text: k }), el("span", { class: "total", "data-testid": "readback-total", "data-value": rb.total, text: v }));
  });
  const out = [document.createTextNode(rb.lead || ""), g];
  if (rb.tail) out.push(document.createTextNode(rb.tail));
  return out;
}
function scrollNew() { const m = $("#messages"); m.scrollTop = m.scrollHeight; }
function pressed(wrap, label) { if (!wrap) return; wrap.querySelectorAll(".opt").forEach((o) => { o.setAttribute("data-live", "false"); if (o.textContent === label) o.classList.add("pressed"); }); }

/* ---------------- the turn: typed → POST /api/turn, the server asks Jev ---------------- */
async function send(text) {
  const comp = $("#composer"); text = (text || "").trim();
  if (!text || comp.dataset.state !== "ready" || !S.session) return;
  setComposer("judging");
  const turn_id = crypto.randomUUID();
  try {
    const r = await unwrap(await fetch("/api/turn", post({ session_id: S.session.id, turn_id, text })));
    renderTurn(r, turn_id);
  } catch (e) { await failed(e); }
  finally { setComposer("ready"); }
}
/* The result of one turn, as the server shapes it (app/turn.py § _result): you, bot[], log_entry,
   raw, model_status, ended. `ignored` and `repeat` render nothing new. */
function renderTurn(r, turn_id, wrap = null) {
  const s = S.session;
  if (r.ended) { fresh(r.session_id, r.turn_no); r.bot.forEach(bot); updateKeyInfo(); return; }
  if (r.outcome === "ignored" || r.repeat) return;
  s.turn_no = r.turn_no;
  if (r.you) { if (r.you.kind === "clicked") pressed(wrap, r.you.text); you(r.you); }
  r.bot.forEach(bot);
  if (r.log_entry) { s.log.push(r.log_entry); if (r.raw) s.raw[turn_id] = r.raw; if (r.log_entry.jev) addTurnRow(r.log_entry, s.log.length); }
  status(r);
  updateKeyInfo();
}
function status(r) {
  const st = $("#key-status"); if (!st) return;
  if (r.outcome === "model_failed") st.textContent = `● unreachable · ${r.log_entry?.jev?.error || "no answer"}`;
  else if (r.outcome === "cap_reached") st.textContent = "● spend cap reached";
  else if (r.model_status === "live" && r.log_entry?.jev) st.textContent = "";   // the model answered a call — cleared (a click makes none)
}
/* The server itself could not be reached, or the session it was asked about is gone: an unknown
   or expired id is "a new session, as if the page had just opened" (session-state.md). */
async function failed(e) {
  if (e.status === 404) { try { await load(""); return; } catch (e2) { e = e2; } }
  console.warn("server", e);
  const st = $("#key-status"); if (st) st.textContent = `● server unreachable · ${e.message}`;
}
/* A click is an event the server validates against the latest bot bubble (contract § Committing 4).
   A set the page already shows dead sends nothing; the server's `ignored` renders nothing. */
async function click(btn, opt) {
  const comp = $("#composer"); const wrap = opt.closest(".opts");
  if (comp.dataset.state !== "ready" || !S.session || opt.dataset.live !== "true") return;
  setComposer("judging");
  const turn_id = crypto.randomUUID();
  try {
    const r = await unwrap(await fetch("/api/turn", post({ session_id: S.session.id, turn_id, button: btn })));
    renderTurn(r, turn_id, wrap);
  } catch (e) { await failed(e); }
  finally { setComposer("ready"); }
}

/* ---------------- panel ---------------- */
/* One row per answered message, from the server's log entry. `n` is the entry's place in the log
   (1-based) — the row's token and what the viewer opens by. Four lines (05_components § TurnRow):
   `#n · text` / intent + confidence (or FALLBACK / MODEL FAILED) / values with the provenance /
   ms · ฿ · $ · open. A by-state turn names the intent the bot acted on and the slot it was awaiting;
   Jev's own answer stays on `data-jev-intent` and in the viewer. */
const PROV = (src) => src === "jev" ? "from Jev" : src === "focus_sku" ? "from focus" : src.startsWith("context:") ? `from context (${src.slice(8)})` : `from ${src.replace(/_/g, " ")}`;
function intentLine(e) {
  const j = e.jev || {};
  if (e.outcome === "model_failed") return `MODEL FAILED · ${j.error || "no answer"}`;
  if (e.outcome === "cap_reached") return "SPEND CAP REACHED · no call made";
  if (e.outcome === "fallback") return `FALLBACK · ${j.intent ?? "—"}`;
  if (j.by_state) return `${e.response_id || "inform"} · by state${j.awaiting ? ` (awaiting ${j.awaiting})` : ""}`;
  return j.intent ?? "—";
}
function addTurnRow(e, n, animate = true) {
  const rows = $("#rows"); $("#rows .empty")?.remove(); const j = e.jev;
  const row = el("div", { class: animate ? "turn arrived" : "turn", "data-testid": `turn-${n}`, "data-turn-id": e.turn_id || "", "data-outcome": e.outcome, "data-at": e.at || "" });
  row.append(el("div", { class: "t1" }, el("span", { class: "n", text: `#${n}` }), document.createTextNode(e.input.text)));
  const kv = (k, v, c, cls = "") => el("div", { class: `kv ${cls}` }, el("span", { class: "k", text: k }), el("span", { class: "v", text: v }), el("span", { class: "c", text: c || "" }));
  const failed = e.outcome === "model_failed" || e.outcome === "cap_reached";
  const iv = kv(e.outcome === "fallback" ? "fallback" : "intent", intentLine(e), failed ? "—" : fmt.conf(j?.confidence), "intent");
  iv.querySelector(".v").setAttribute("data-testid", `turn-${n}-intent`); iv.querySelector(".v").setAttribute("data-jev-intent", j?.intent ?? "");
  iv.querySelector(".c").setAttribute("data-testid", `turn-${n}-confidence`); iv.querySelector(".c").setAttribute("data-value", failed ? "" : (j?.confidence ?? ""));
  row.append(iv);
  const vals = j && Object.entries(j.entities || {}).filter(([, v]) => v !== "not_mentioned").map(([k, v]) => `${k} ${v}`).join(" · ");
  row.append(kv("values", vals || "—", ""));
  const a = (e.applied || []).find((x) => x.product_from);          // Provenance: where the product came from
  if (a) row.append(el("div", { class: "prov", "data-testid": `turn-${n}-prov-product`, "data-source": a.product_from, text: `product ${a.set.match(/\[(.+?)\]/)?.[1] || a.to || ""}  ← ${PROV(a.product_from)}` }));
  const t4 = el("div", { class: "t4" });
  t4.append(el("span", { "data-testid": `turn-${n}-ms`, "data-value": j?.ms ?? 0, text: j ? fmt.ms(j.ms || 0) : "—" }), el("span", { "data-testid": `turn-${n}-baht`, "data-value": j?.cost_usd ?? 0, text: j && j.cost_usd ? fmt.baht(j.cost_usd) : "฿0" }), el("span", { "data-testid": `turn-${n}-usd`, "data-value": j?.cost_usd ?? 0, text: j && j.cost_usd ? fmt.usd(j.cost_usd) : "—" }));
  t4.append(el("button", { class: "open", "data-testid": `turn-${n}-open`, text: "open", onclick: () => openViewer(n) }));
  row.append(t4); rows.prepend(row);
}
function updateKeyInfo() {
  const s = S.session; const answered = (s?.log || []).filter((e) => e.jev && e.outcome !== "model_failed" && e.outcome !== "cap_reached");
  const avg = answered.length ? answered.reduce((a, e) => a + (e.jev.ms || 0), 0) / answered.length : null;
  const usd = answered.reduce((a, e) => a + (e.jev.cost_usd || 0), 0);
  const turns = s?.log?.length ?? 0;   // every committed message — typed, clicked or missed — as the rows are numbered
  set("#avg-ms", avg == null ? "—" : fmt.ms10(avg), avg ?? 0); set("#total-baht", fmt.baht(usd, 3), usd); set("#total-turns", String(turns), turns);
  $("#key-info").setAttribute("data-total-usd", usd.toFixed(6));
}
function set(sel, text, value) { const n = $(sel); if (!n) return; n.textContent = text; n.setAttribute("data-value", value); n.classList.remove("bump"); void n.offsetWidth; n.classList.add("bump"); }
/* The viewer opens the n-th log entry; its raw bodies are looked up by the entry's turn_id and
   are only there while the server has held them in memory (empty after a restart). */
function openViewer(n) {
  const s = S.session; const e = s.log[n - 1]; if (!e) return; const raw = s.raw[e.turn_id] || {}; const v = $("#viewer");
  $("#viewer-title").textContent = `Turn #${n} · ${e.input.text}`;
  const dl = (pairs) => { const d = el("dl"); pairs.forEach(([k, val]) => d.append(el("dt", { text: k }), el("dd", { text: val }))); return d; };
  const pre = (x) => (x === undefined ? "— not in memory" : JSON.stringify(x, null, 1));
  $("#viewer-sent").replaceChildren(dl([["shop_said", raw.request?.state?.shop_said || "—"], ["customer_said", e.input.text], ["contexts", (e.contexts_before || []).join(", ") || "none"], ["intents in scope", String(e.intents_in_scope || "—")], ["entity questions", "product · quantity · brew · roast · payment"]]), el("details", {}, el("summary", { text: "raw request" }), el("pre", { "data-testid": "viewer-raw-request", text: pre(raw.request) })));
  const j = e.jev || {};
  const wall = j.t_sent && j.t_received ? Date.parse(j.t_received) - Date.parse(j.t_sent) : null;
  $("#viewer-back").replaceChildren(dl([["intent", j.intent ? `${j.intent} ${fmt.conf(j.confidence)}` : "—"], ...Object.entries(j.entities || {}).map(([k, val]) => [k, val]), ["cost", j.cost_usd ? `${fmt.usd(j.cost_usd)} → ${fmt.baht(j.cost_usd)}` : "—"], ["latency · status", `${j.ms ?? "—"} ms · ${j.status ?? "—"}`], ["t_sent → t_received", j.t_sent ? `${j.t_sent.slice(11, 23)} → ${(j.t_received || "").slice(11, 23)} (${wall} ms wall)` : "—"], ["received at", e.at || "—"]]), el("details", {}, el("summary", { text: "raw response" }), el("pre", { "data-testid": "viewer-raw-response", text: pre(raw.response) })));
  $("#viewer-applied").replaceChildren(dl((e.applied || []).length ? e.applied.map((a) => [a.set, `${a.to ?? ""}${a.product_from ? `  (product from ${a.product_from})` : ""}`]) : [["—", "nothing written"]]));
  v.style.bottom = `${$("#key-info").offsetHeight}px`;  // the drawer stops above the key-info block — never covers it
  v.style.display = "block"; setTimeout(() => v.setAttribute("data-open", "true"), 20); document.querySelector(`[data-testid="turn-${n}"]`)?.setAttribute("data-open", "true");
}
function closeViewer() { const v = $("#viewer"); v.setAttribute("data-open", "false"); setTimeout(() => { if (v.getAttribute("data-open") === "false") v.style.display = "none"; }, 220); document.querySelectorAll(".turn[data-open]").forEach((r) => r.removeAttribute("data-open")); }

/* ---------------- composer, start over, boot ---------------- */
function setComposer(state) { const c = $("#composer"); if (!c) return; c.dataset.state = state; c.querySelector("input").disabled = state === "judging"; c.querySelector(".helper").textContent = state === "judging" ? "Beanly กำลังคิด…" : state === "paused" ? "paused" : ""; }
/* The screen as it is before a session is drawn: chat and panel clear, key-info at zero. */
function fresh(id, turn_no = 0) {
  if (typeof speedReset === "function") speedReset();
  botCount = 0; youCount = 0; closeViewer();
  $("#messages")?.replaceChildren(); $("#rows").replaceChildren(el("div", { class: "empty", text: "Type something — clicks don't call the model." })); $("#key-status").textContent = "";
  S.session = { id, turn_no, log: [], raw: {} }; rememberId(id);
}
/* `GET /api/session?id=`: a new session, or the one the id names — its whole transcript rendered
   in one paint, only the latest bot bubble's buttons live, the rows from its log, no animation. */
async function load(id) {
  const v = await unwrap(await fetch("/api/session?id=" + encodeURIComponent(id || ""), { cache: "no-store" }));
  fresh(v.session_id, v.turn_no);
  S.session.log = v.log || []; S.session.raw = v.raw || {};
  let wrap = null;
  for (const m of v.transcript || []) { if (m.who === "you") { if (m.kind === "clicked") pressed(wrap, m.text); you(m); } else wrap = bot(m) || wrap; }
  S.session.log.forEach((e, i) => { if (e.jev) addTurnRow(e, i + 1, false); });
  updateKeyInfo();
  return v;
}
/* StartOverButton: the session is ended and a new one created — a new id (session-state.md). */
async function startOver() {
  const comp = $("#composer"); if (comp.dataset.state === "judging") return;
  setComposer("judging");
  try { if (S.session?.id) await unwrap(await fetch("/api/session/end", post({ session_id: S.session.id }))); await load(""); }
  catch (e) { await failed(e); }
  finally { setComposer("ready"); }
}
/* Story 1.1: the rate, its date and the model id come from the server (`/api/config`). */
async function loadConfig() {
  try {
    const r = await fetch("/api/config", { cache: "no-store" });
    if (!r.ok) throw new Error(`config ${r.status}`);
    const c = await r.json();
    return { rate: { thb_per_usd: c.thb_per_usd, date: c.rate_date, source: "server" }, model: c.model };
  } catch (e) { console.warn("config from the server failed", e); return null; }
}
async function boot(opts = {}) {
  const cfg = await loadConfig();
  if (cfg) { CFG.rate = cfg.rate; CFG.model = cfg.model; const m = $("#model-id"); if (m && cfg.model) m.textContent = cfg.model.split("/").pop(); }
  $("#rate").textContent = cfg ? `฿${CFG.rate.thb_per_usd}/$` : "rate —";
  $("#rate").setAttribute("data-source", CFG.rate.source || "none"); $("#rate").setAttribute("data-value", cfg ? CFG.rate.thb_per_usd : "");
  $("#rate-date").textContent = cfg ? CFG.rate.date : "—"; $("#rate-date").setAttribute("data-value", cfg ? CFG.rate.date : "");
  $("#composer input")?.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); const i = ev.target; const t = i.value; i.value = ""; send(t); } });
  $("#send")?.addEventListener("click", () => { const i = $("#composer input"); const t = i.value; i.value = ""; send(t); });
  $("#start-over").addEventListener("click", startOver);
  $("#viewer-close").addEventListener("click", closeViewer);
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeViewer(); });
  try { await load(storedId()); } catch (e) { await failed(e); }
  if (opts.after) opts.after();
}
