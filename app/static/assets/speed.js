/* The speed test on the same screen (FR26, DR-010). It adds nothing to the page: no control, no
   status line, no element of its own. It is started from the address — `/?run=100` to rehearse,
   `/?run=1000` to record — and streams through the chat's own bubbles, rows and key-info block.
   The server runs it (Story 2.1: `POST /api/run`, `GET /api/run`); the recap's figures stay there. */
"use strict";

const RUN_TARGETS = [100, 1000];

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
}
function speedReset() {}
