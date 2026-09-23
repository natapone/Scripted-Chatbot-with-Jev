"""The speed test's engine (FR26; contract `session-state.md` § The speed test and the lock).

A run sends `target` messages from the catalogue's test set (`app/testset.py`, cycled by `case_index`) to Jev with
`CONCURRENCY` in flight, each built by `turn.classify` exactly as the chat builds a typed turn for
that case's contexts and pending slot. **Requests are concurrent; commits are serialised**: each
answer, as it completes, takes the session's lock, gets the next `turn_no`, and is appended to the
presenter's log with a `batch` mark — a fallback, a failed call or the cap included, so every message
is a row with its own number (F-5, decided for the run). Batch entries write nothing else of the
session: no order form, no contexts, no transcript. The snapshot is written once, at the run's end.

Each worker holds its own `Client.sibling()` — no retry, a timeout of at most `CALL_TIMEOUT_S` — so a
failed or timed-out call is one `model_failed` row, counted, never retried (F-9). `FAIL_STREAK`
failures in a row end the run as `failed`. Starting over (the session ends) stops the run and drops
the answers still in flight (contract step 8).

What the page is sent for each answer (`items`): the log entry, the customer bubble and Beanly's
prepared reply — the reply the chat's own `turn.act` gives on a copy of the case's session, so it is
never a canned string. Delivery details from the test set are masked in the entry, the bubbles and the
retained request (NFR10). Nothing here is drawn on the page by this module (DR-010).
"""
from __future__ import annotations

import math
import threading
import time
import uuid
from dataclasses import dataclass, field

from app import jev, testset, turn
from app.flow import Flow
from app.session import Session, Store, parse_stamp

CONCURRENCY = 32                  # S-4: 1,000 turns in 12.6 s at 32 in flight
CALL_TIMEOUT_S = 5.0              # F-9: a slow call frees its slot after this; F-12 saw none past 5 s
FAIL_STREAK = 32                  # failed calls in a row that end the run (S-3 saw 57 empty in a row)
MAX_TARGET = 1000                 # FR26: 100 to rehearse, 1,000 to record
STRIDE = 5                        # the order the set is cycled in: every 5th case, so a run of 100 meets
                                  # the whole catalogue — delivery details (cases 106–108) included
EST_TURN_USD = 0.0002             # S-4 measured $0.000163 a turn; the refusal estimates on the safe side
FAILED = ("model_failed", "cap_reached")


def case_index(i: int, n_cases: int) -> int:
    """The case the `i`-th message of a run sends (0-based): the set cycled with a stride coprime to
    its size, so every case is sent once per `n_cases` messages and none is skipped."""
    stride = STRIDE if math.gcd(STRIDE, n_cases) == 1 else 1
    return (i * stride) % n_cases


class RunError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class Run:
    run_id: str
    session_id: str
    target: int
    concurrency: int
    started_at: str
    state: str = "running"             # running | done | capped | failed | cancelled
    items: list = field(default_factory=list)
    errors: int = 0
    timeouts: int = 0
    correct: int = 0
    wall_ms: int | None = None         # the run's own clock, start to last commit
    _next: int = 0
    _streak: int = 0
    _stop: str | None = None           # why no further call is sent
    _t0: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _done: threading.Event = field(default_factory=threading.Event, repr=False)

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)


def prepared_reply(flow: Flow, case_session: Session, v: turn.Verdict, text: str, at: str,
                   masked: bool) -> list[dict]:
    """Beanly's reply to this message, as the chat would give it — `turn.act` on a copy of the case's
    session — with no buttons (nothing in a run is clickable) and the delivery details masked."""
    if v.outcome == "fallback":
        bubbles = [{"text": turn.strip_text(flow.fallback["ladder"][0]), "variant": "fallback", "response_id": "fallback.1"}]
    elif v.outcome == "cap_reached":
        bubbles = [{"text": turn.UNREACHABLE, "variant": "system", "response_id": "system.cap"}]
    elif v.outcome != "matched":
        bubbles = [{"text": turn.UNREACHABLE, "variant": "system", "response_id": "system.unreachable"}]
    elif v.intent == "start_over":
        greet = turn.flow_intent(flow, "greet")
        bubbles = [{"text": turn.strip_text(greet["response"]), "variant": "plain", "response_id": "greet"}]
    else:
        c = case_session.copy()
        c.transcript.append(turn.you_bubble(text, "typed", masked))
        before = len(c.transcript)
        try:
            turn.act(c, flow, v.intent, v.entities, sku=v.sku, product_from=v.product_from, turn_no_after=1,
                     text=text, at=at)
            bubbles = [{"text": b["text"], "variant": b.get("variant", "plain"), "response_id": b.get("response_id")}
                       for b in c.transcript[before:] if b.get("who") == "bot"]
        except Exception:                                # a reply must never cost the row: the catalogue's text
            it = turn.flow_intent(flow, v.intent)
            bubbles = [{"text": turn.strip_text(it["response"]) or it["response"], "variant": "plain",
                        "response_id": v.intent}]
    out = []
    for b in bubbles:
        t = b["text"]
        if masked and text.strip():
            t = t.replace(text.strip(), turn.MASK_FOR_JEV)
        out.append({"who": "bot", "text": t, "buttons": [], "variant": b["variant"], "response_id": b["response_id"]})
    return out


class Runs:
    """The runs of one server, one per session at a time, the latest kept for its progress."""

    def __init__(self, store: Store, flow: Flow, client: jev.Client, *, spend_cap_usd: float | None = None,
                 thb_per_usd: float = 0.0, rate_date: str = "", concurrency: int = CONCURRENCY,
                 call_timeout_s: float = CALL_TIMEOUT_S, cases: list[dict] | None = None,
                 catalogue: dict | None = None, clock=jev.now_utc):
        self.store, self.flow, self.client = store, flow, client
        self.spend_cap_usd, self.thb_per_usd, self.rate_date = spend_cap_usd, thb_per_usd, rate_date
        self.concurrency = concurrency
        self.call_timeout_s = min(call_timeout_s, client.timeout)
        self.catalogue = catalogue if catalogue is not None else testset.read_catalogue()
        self.cases = cases if cases is not None else testset.load_cases(self.catalogue)
        self.clock = clock
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()

    # --- start

    def start(self, session_id: str, target) -> dict:
        if isinstance(target, bool) or not isinstance(target, int) or not 1 <= target <= MAX_TARGET:
            raise RunError(400, f"target must be a whole number from 1 to {MAX_TARGET}")
        with self.store.lock(session_id):
            if self.store.get(session_id) is None:
                raise RunError(404, "unknown or expired session")
            if self.spend_cap_usd is not None:           # NFR4: refused before its first call
                estimate = target * EST_TURN_USD
                room = self.spend_cap_usd - self.client.spent_usd
                if estimate > room:
                    return {"refused": True, "outcome": "cap_reached", "model_status": "cap",
                            "session_id": session_id, "target": target, "estimate_usd": estimate,
                            "room_usd": max(room, 0.0)}
            with self._lock:
                current = self._runs.get(session_id)
                if current is not None and current.state == "running":
                    raise RunError(409, "a run is already going on this session")
                run = Run(run_id=f"run-{uuid.uuid4().hex[:8]}", session_id=session_id, target=target,
                          concurrency=min(self.concurrency, target), started_at=jev.stamp(self.clock()))
                run._t0 = time.monotonic()
                self._runs[session_id] = run
        threading.Thread(target=self._drive, args=(run,), name=run.run_id, daemon=True).start()
        return {"refused": False, "run_id": run.run_id, "session_id": session_id, "target": target,
                "concurrency": run.concurrency, "state": run.state, "model_status": "live"}

    def get(self, session_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(session_id)

    def progress(self, session_id: str, since: int = 0) -> dict:
        """The latest run on this session: its counts, the items from `since` on, and — once it has
        ended — the recap, computed from the session's turn log."""
        run = self.get(session_id)
        if run is None:
            raise RunError(404, "no run on this session")
        with run._lock:
            state, items = run.state, list(run.items)
        since = max(0, since)
        out = {"run_id": run.run_id, "session_id": session_id, "target": run.target,
               "concurrency": run.concurrency, "started_at": run.started_at, "state": state,
               "answered": len(items), "errors": run.errors, "timeouts": run.timeouts, "correct": run.correct,
               "model_status": "cap" if state == "capped" else "live",
               "since": since, "next": len(items), "items": items[since:], "recap": None}
        if state != "running":
            with self.store.lock(session_id):
                s = self.store.get(session_id)
                log = list(s.log) if s is not None else [i["entry"] for i in items]
            entries = [e for e in log if e.get("batch") == run.run_id]
            out["recap"] = recap(entries, thb_per_usd=self.thb_per_usd, rate_date=self.rate_date,
                                 target=run.target, concurrency=run.concurrency, wall_ms=run.wall_ms,
                                 model=self.flow.model)
        return out

    # --- the run

    def _drive(self, run: Run) -> None:
        workers = [threading.Thread(target=self._work, args=(run,), name=f"{run.run_id}-{i}", daemon=True)
                   for i in range(run.concurrency)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        with self.store.lock(run.session_id):
            s = self.store.get(run.session_id)
            if s is None:
                run._stop = "cancelled"
            else:
                self.store.commit(s)                     # the one snapshot of the run
        run.state = {None: "done", "cap": "capped", "streak": "failed", "cancelled": "cancelled"}[run._stop]
        run.wall_ms = int((time.monotonic() - run._t0) * 1000)
        run._done.set()

    def _work(self, run: Run) -> None:
        client = self.client.sibling(timeout=self.call_timeout_s)
        try:
            while True:
                with run._lock:
                    if run._stop is not None or run._next >= run.target:
                        return
                    i = run._next
                    run._next += 1
                case = self.cases[case_index(i, len(self.cases))]
                cs = testset.build_session(case, self.flow)
                at = jev.stamp(self.clock())
                v = turn.classify(cs, case["text"], self.flow, client, spend_cap_usd=self.spend_cap_usd,
                                  clock=self.clock)
                self._commit(run, i + 1, case, cs, v, at)
        finally:
            client.close()

    def _commit(self, run: Run, n: int, case: dict, cs: Session, v: turn.Verdict, at: str) -> None:
        text = case["text"]
        masked = (case["intent"] == "give_delivery_details" or v.intent == "give_delivery_details"
                  or (cs.pending_prompt or {}).get("slot") == turn.DELIVERY_SLOT)
        shown = turn.MASK_FOR_LOG if masked else text
        request = v.request
        if masked:
            request = dict(request, state=dict(request.get("state") or {}, customer_said=turn.MASK_FOR_JEV))
        raw = {"request": request, "response": v.answer.raw if v.answer is not None else None}
        bot = prepared_reply(self.flow, cs, v, text, at, masked)
        score = testset.score(self.catalogue, case, v)
        with self.store.lock(run.session_id):
            s = self.store.get(run.session_id)
            if s is None:                                # started over: the answer is dropped
                with run._lock:
                    run._stop = "cancelled"
                return
            turn_id = f"{run.run_id}-{n}"
            entry = turn.log_entry(cs, self.flow, turn_no=s.turn_no + 1, turn_id=turn_id, at=at, kind="typed",
                                   text=shown, outcome=v.outcome, verdict=v, applied=[],
                                   response_id=bot[0]["response_id"] if bot else None,
                                   contexts_after=cs.live_contexts())
            entry["batch"] = run.run_id
            entry["batch_n"] = n
            entry["judged"] = v.intent               # what the message was judged as; a by-state row names it
            entry["correct"] = bool(score["loop_ok"])
            s.turn_no += 1
            s.log.append(entry)
            s.raw[turn_id] = raw
            failed = v.outcome in FAILED
            with run._lock:
                run.items.append({"entry": entry, "you": turn.you_bubble(shown, "typed", masked), "bot": bot,
                                  "raw": raw})
                run.correct += entry["correct"]
                run.errors += failed
                run.timeouts += bool(v.answer is not None and v.answer.error == "TimeoutError")
                run._streak = run._streak + 1 if v.outcome == "model_failed" else 0
                if v.outcome == "cap_reached":
                    run._stop = run._stop or "cap"
                elif run._streak >= FAIL_STREAK:
                    run._stop = run._stop or "streak"


def recap(entries: list[dict], *, thb_per_usd: float, rate_date: str, target: int, concurrency: int,
          wall_ms: int | None, model: str) -> dict:
    """The recap's figures, from a run's log entries — raw, unrounded, for the recording driver.
    `avg_ms` and `total_usd` follow the key-info block's rule (`shared.js` § `updateKeyInfo`): over
    entries with a `jev` block that are neither `model_failed` nor `cap_reached`. `elapsed_ms` is the
    first `t_sent` to the last `t_received` in the log; `wall_ms` is the run's own clock."""
    calls = len(entries)
    answered = [e for e in entries if e.get("jev") and e.get("outcome") not in FAILED]
    ms = [e["jev"].get("ms") or 0 for e in answered]
    total_usd = sum(e["jev"].get("cost_usd") or 0.0 for e in answered)
    stamped = [e["jev"] for e in entries if (e.get("jev") or {}).get("t_sent") and e["jev"].get("t_received")]
    elapsed_ms = None
    if stamped:
        first = min(parse_stamp(j["t_sent"]) for j in stamped)
        last = max(parse_stamp(j["t_received"]) for j in stamped)
        elapsed_ms = (last - first).total_seconds() * 1000
    correct = sum(1 for e in entries if e.get("correct"))
    return {"calls": calls, "target": target, "concurrency": concurrency,
            "elapsed_ms": elapsed_ms, "wall_ms": wall_ms,
            "calls_per_s": calls / (elapsed_ms / 1000) if elapsed_ms else None,
            "avg_ms": sum(ms) / len(ms) if ms else None,
            "answered": len(answered),
            "correct": correct, "correct_share": correct / calls if calls else None,
            "fallbacks": sum(1 for e in entries if e.get("outcome") == "fallback"),
            "errors": sum(1 for e in entries if e.get("outcome") in FAILED),
            "timeouts": sum(1 for e in entries if (e.get("jev") or {}).get("error") == "TimeoutError"),
            "total_usd": total_usd, "total_thb": total_usd * thb_per_usd,
            "cost_per_call_usd": total_usd / calls if calls else None,
            "cost_per_call_thb": total_usd * thb_per_usd / calls if calls else None,
            "thb_per_usd": thb_per_usd, "rate_date": rate_date, "model": model}
