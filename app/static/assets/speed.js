/* Component library — the SpeedTest organism (05_components.md), as ruled 2026-09-22: it runs ON
   the W-001 screen. A header popover chooses 100 / 1,000 and starts; the messages stream as chat,
   the panel rows stream beside them, the key-info block counts, one status line sits above the
   composer. The prototype simulated the run from Spike S-4's shape over the fixture phrases; the
   fixtures left with Story 1.3b and the real run — real requests through the server — is Epic 2's.
   Until then every token is mounted and `Start` says so. */
"use strict";
const SPEED = { target: 100, phase: "ready", answered: 0, correct: 0, errors: 0, usd: 0, t0: 0, elapsed: 0, timer: null };
const NOT_WIRED = "not wired until Epic 2";

function speedMount() {
  const header = $(".chat-header"); const spacer = header.querySelector(".spacer");
  const pop = el("div", { class: "speed-pop", id: "speed-pop", "data-testid": "speed-pop", hidden: "" },
    el("div", { class: "chooser", id: "speed-chooser", "data-testid": "speed-chooser" },
      el("button", { class: "opt pressed", "data-n": "100", "data-testid": "speed-target-100", text: "100 rehearsal", onclick: () => speedChoose(100) }),
      el("button", { class: "opt", "data-n": "1000", "data-testid": "speed-target-1000", text: "1,000 demo", onclick: () => speedChoose(1000) })),
    el("div", { class: "note", text: `messages from the intent catalogue's test set · 32 in flight · full catalogue each — ${NOT_WIRED}` }),
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
function speedChoose(n) { if (SPEED.phase === "running") return; SPEED.target = n; document.querySelectorAll("#speed-chooser .opt").forEach((o) => o.classList.toggle("pressed", +o.dataset.n === n)); speedRender(); }
function speedRender() {
  const st = $("#speed-status"); if (!st) return; const ph = SPEED.phase; st.dataset.phase = ph; st.hidden = ph === "ready";
  const sec = (ms) => (ms / 1000).toFixed(1);
  const elapsed = ph === "running" ? performance.now() - SPEED.t0 : SPEED.elapsed;
  const set2 = (id, text, v) => { const n = $(id); n.textContent = text; n.setAttribute("data-value", v); };
  set2("#speed-count", `speed test · ${SPEED.answered.toLocaleString()}`, SPEED.answered); set2("#speed-target", SPEED.target.toLocaleString(), SPEED.target);
  set2("#speed-elapsed", `${sec(elapsed)} s`, Math.round(elapsed));
  const perS = elapsed > 300 ? SPEED.answered / (elapsed / 1000) : 0; set2("#speed-per-s", `${perS.toFixed(0)}/s`, perS.toFixed(1));
  set2("#speed-correct", `${SPEED.correct} ✓`, SPEED.correct); set2("#speed-errors", SPEED.errors ? ` · ${SPEED.errors} errors` : "", SPEED.errors);
  $("#speed-summary").textContent = ph === "done" ? ` — ${SPEED.target.toLocaleString()} answered in ${sec(SPEED.elapsed)} s · ${(SPEED.target / (SPEED.elapsed / 1000)).toFixed(0)}/s · ${SPEED.correct} correct` : ph === "unwired" ? ` — ${NOT_WIRED}` : "";  // cost lives in KeyInfo, not here
  const open = $("#speed-test-open"); if (open) open.disabled = ph === "running";
}
/* Epic 2 sends the real requests through the server. Here `Start` only shows the status line with
   the note; nothing is sent, nothing is counted, the chat is left alone. */
function speedStart() {
  if (SPEED.phase === "running") return;
  $("#speed-pop").hidden = true;
  SPEED.phase = "unwired"; speedRender();
}
function speedReset() { clearInterval(SPEED.timer); Object.assign(SPEED, { phase: "ready", answered: 0, correct: 0, errors: 0, usd: 0, elapsed: 0 }); speedRender(); }
