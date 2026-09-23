/* The speed test on the same screen (FR26, DR-010). It adds nothing to the page: no control, no
   status line, no element of its own. It is started from the address — `/?run=100` to rehearse,
   `/?run=1000` to record — and streams through the chat's own bubbles, rows and key-info block.
   The server runs it (Story 2.1: `POST /api/run`, `GET /api/run`); the recap's figures stay there. */
"use strict";

const RUN_TARGETS = [100, 1000];
const POLL_MS = 150;                     // how often the page asks for the answers that have arrived
const RUN = { id: "", session: "", next: 0, timer: 0, streaming: false };

/* The target the address asks for: exactly `100` or `1000`, anything else is no run. */
function runTarget(search) {
  const v = new URLSearchParams(search || "").get("run");
  return RUN_TARGETS.find((n) => String(n) === v) || 0;
}
/* `?run=` leaves the address before the run is asked for, so a reload or เริ่มใหม่ never starts a
   second paid run. The rest of the address is kept. */
function dropRunParam() {
  const u = new URL(location.href);
  if (!u.searchParams.has("run")) return false;
  u.searchParams.delete("run");
  history.replaceState(history.state, "", u.pathname + u.search + u.hash);
  return true;
}
async function speedFromAddress() {
  const target = runTarget(location.search);
  dropRunParam();
  if (target && S.session) await speedStart(target);
}
/* One run on the page's session. A refusal (the cap) shows the key-info block's own cap line and
   nothing streams. */
async function speedStart(target) {
  const id = S.session.id; let r;
  try { r = await unwrap(await fetch("/api/run", post({ session_id: id, target }))); }
  catch (e) { await failed(e); return; }
  if (r.refused) { showStatus(null, { status: "cap", line: "● spend cap reached" }); fitViewer(); return; }
  if (S.session?.id !== id) return;                          // started over while the run was asked for
  Object.assign(RUN, { id: r.run_id, session: id, next: 0, streaming: true });
  setComposer("judging");                                    // the composer's own disabled state
  await speedPoll();
}
/* The answers that arrived since the last ask, drawn as the chat draws a turn: the customer bubble,
   Beanly's prepared reply, the row, the key-info block from the log. Until the run has ended. */
async function speedPoll() {
  if (!RUN.streaming) return;
  const run = RUN.id; let p;
  try { p = await unwrap(await fetch(`/api/run?session_id=${encodeURIComponent(RUN.session)}&since=${RUN.next}`, { cache: "no-store" })); }
  catch (e) { if (RUN.id === run) speedStop(); console.warn("run", e); return; }
  if (!RUN.streaming || RUN.id !== run || p.run_id !== run || S.session?.id !== RUN.session) return;
  speedDraw(p.items || []); RUN.next = p.next;
  if (p.state === "running") RUN.timer = setTimeout(speedPoll, POLL_MS); else speedStop();
}
function speedDraw(items) {
  const s = S.session;
  for (const it of items) {
    const e = it.entry;
    you(it.you);
    (it.bot || []).forEach((b, k) => bot({ ...b, id: `${e.turn_id}-${k + 1}` }));
    s.log.push(e); s.turn_no = Math.max(s.turn_no, e.turn_no || 0);
    if (it.raw) s.raw[e.turn_id] = it.raw;
    if (e.jev) addTurnRow(e, s.log.length);
  }
  if (items.length) updateKeyInfo();
}
/* The stream ends: the screen keeps the last chats and the totals; the composer is ready. */
function speedStop() {
  clearTimeout(RUN.timer);
  if (!RUN.streaming) return;
  RUN.streaming = false; setComposer("ready");
}
function speedRunning() { return RUN.streaming; }
/* Start over (fresh): nothing more is drawn; the server has already stopped the run. */
function speedReset() { clearTimeout(RUN.timer); Object.assign(RUN, { id: "", session: "", next: 0, streaming: false }); }
