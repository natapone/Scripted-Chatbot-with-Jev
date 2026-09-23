"""Story 2.1 — the speed test's engine (`app/speed.py`). Hermetic: every sibling client rides a fake
connection that answers each message with its test-set label, so no socket leaves the process;
snapshots go to a temp dir."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from app import flow, jev, session, speed, testset, turn
from tests.test_jev import FAKE_KEY
from tests.test_turn import reply

FLOW = flow.load()
CAT = testset.read_catalogue()
CASES = testset.load_cases(CAT)
LABEL = {c["text"]: c for c in CASES}
DELIVERY = [c["text"] for c in CASES if c["intent"] == "give_delivery_details"]


def labelled(*, fail=(), timeout=(), http=(), none=(), before=None, cost=0.000163):
    """A connection class: each request is answered with the label of the case whose text it carries
    (`none` → a low-confidence `none`); texts in `fail` refuse, in `timeout` time out, in `http` get a
    500. `before(body)` runs first, for a barrier or a gate. `log` counts, thread-safe."""
    log = {"opened": 0, "sent": [], "timeouts": set()}
    lock = threading.Lock()

    class Conn:
        def __init__(self, host, port=None, timeout=None):
            with lock:
                log["opened"] += 1
                log["timeouts"].add(timeout)
            self._next = None

        def request(self, method, path, body=None, headers=None):
            b = json.loads(body)
            with lock:
                log["sent"].append(b)
            if before is not None:
                before(b)
            text = b["state"]["customer_said"]
            if text in fail:
                raise ConnectionRefusedError("no")
            if text in timeout:
                raise TimeoutError("slow")
            if text in http:
                self._next = (500, {"error": {"message": "upstream"}})
            elif text in none or LABEL[text]["intent"] == "none":
                self._next = (200, reply("none", 0.2, cost=cost))
            else:
                c = LABEL[text]
                self._next = (200, reply((c["accept_intents"] or [c["intent"]])[0], 0.95, cost=cost, **c["entities"]))

        def getresponse(self):
            status, data = self._next

            class R:
                pass
            r = R()
            r.status = status
            r.read = lambda: json.dumps(data).encode("utf-8")
            return r

        def close(self):
            pass

    Conn.log = log
    return Conn


class Rig:
    def __init__(self, test, conn, *, cap=0.50, concurrency=32, cases=None):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.var = Path(self.tmp.name)
        self.conn = conn
        self.client = jev.Client(FAKE_KEY, timeout=10, connection=conn)
        self.store = session.Store("abc123", self.var)
        self.s = turn.new_session(self.store, FLOW)
        self.runs = speed.Runs(self.store, FLOW, self.client, spend_cap_usd=cap, thb_per_usd=34.9,
                               rate_date="2026-09-22", concurrency=concurrency, catalogue=CAT, cases=cases)

    def run(self, target, **kw):
        started = self.runs.start(self.s.session_id, target)
        run = self.runs.get(self.s.session_id)
        if not started["refused"]:
            self_ok = run.wait(20)
            assert self_ok, "the run did not finish"
        return started, run

    def snapshot_text(self):
        return (self.var / "sessions" / f"{self.s.session_id}.json").read_text(encoding="utf-8")


class RunTests(unittest.TestCase):

    def test_every_message_is_a_row_numbered_and_scored(self):  # AC-1, AC-2, AC-3
        fallback, refused, slow, broken = CASES[0]["text"], CASES[1]["text"], CASES[2]["text"], CASES[3]["text"]
        conn = labelled(none={fallback}, fail={refused}, timeout={slow}, http={broken})
        r = Rig(self, conn)
        with mock.patch.object(r.store, "_write", wraps=r.store._write) as write:
            started, run = r.run(140)                    # more than the 129 cases: the set is cycled
        self.assertEqual((started["refused"], started["concurrency"], run.state), (False, 32, "done"))
        s = r.store.get(r.s.session_id)
        batch = [e for e in s.log if e.get("batch") == run.run_id]
        self.assertEqual(len(batch), 140)
        self.assertEqual(sorted(e["turn_no"] for e in batch), list(range(1, 141)))     # F-5: a miss is a row
        self.assertEqual(sorted(e["batch_n"] for e in batch), list(range(1, 141)))
        self.assertEqual(s.turn_no, 140)
        self.assertEqual(write.call_count, 1)                                           # one snapshot, at the end
        # every call is one request, never retried; the server's client counts the pool (one meter)
        self.assertEqual((len(conn.log["sent"]), r.client.calls), (140, 140))
        self.assertEqual(conn.log["timeouts"], {speed.CALL_TIMEOUT_S})
        # the requests are the chat's own, for the case's contexts and pending slot
        for c in CASES[:20]:
            sent = next(b for b in conn.log["sent"] if b["state"]["customer_said"] == c["text"])
            self.assertEqual(sent, turn.build_request(testset.build_session(c, FLOW), c["text"], FLOW))
        # errors: the refused, the timed-out and the 500 — each case sent twice in 140 (n and n+129) for the first 11
        by = {e["batch_n"]: e for e in batch}
        self.assertEqual((by[2]["outcome"], by[2]["jev"]["error"]), ("model_failed", "ConnectionRefusedError"))
        self.assertEqual((by[3]["outcome"], by[3]["jev"]["error"]), ("model_failed", "TimeoutError"))
        self.assertEqual((by[4]["outcome"], by[4]["jev"]["error"]), ("model_failed", "http"))
        self.assertEqual(by[1]["outcome"], "fallback")
        self.assertEqual((run.errors, run.timeouts), (6, 2))
        self.assertEqual(run.correct, sum(e["correct"] for e in batch))
        self.assertFalse(by[1]["correct"] or by[2]["correct"])
        self.assertTrue(all(e["jev"]["t_sent"] and e["jev"]["t_received"] for e in batch))
        # the page's items: one per row, with the prepared reply and no buttons
        self.assertEqual(len(run.items), 140)
        item = next(i for i in run.items if i["entry"]["batch_n"] == 5)
        self.assertEqual(item["you"]["text"], CASES[4]["text"])
        self.assertTrue(item["bot"] and all(b["buttons"] == [] for b in item["bot"]))
        self.assertEqual(next(i for i in run.items if i["entry"]["batch_n"] == 2)["bot"][0]["response_id"], "system.unreachable")
        # nothing else of the session was written by the run
        self.assertEqual((s.contexts, s.order, len(s.transcript)), ({}, session.empty_order(), 1))
        # NFR10: delivery details masked in the entry, the bubble and the retained request; never in the file
        masked = [e for e in batch if CASES[(e["batch_n"] - 1) % 129]["intent"] == "give_delivery_details"]
        self.assertTrue(masked)
        for e in masked:
            self.assertEqual(e["input"]["text"], turn.MASK_FOR_LOG)
            self.assertEqual(s.raw[e["turn_id"]]["request"]["state"]["customer_said"], turn.MASK_FOR_JEV)
            it = next(i for i in run.items if i["entry"] is e)
            self.assertEqual(it["you"]["text"], turn.MASK_FOR_LOG)
            self.assertFalse(any(d in b["text"] for d in DELIVERY for b in it["bot"]))
        text = r.snapshot_text()
        for d in DELIVERY:
            self.assertNotIn(d, text)
        self.assertNotIn(FAKE_KEY, text)

    def test_thirty_two_in_flight_at_once(self):  # AC-1
        barrier = threading.Barrier(32, timeout=5)
        conn = labelled(before=lambda b: barrier.wait())     # every call waits until 32 are in flight
        r = Rig(self, conn)
        _, run = r.run(64)
        self.assertEqual((run.state, run.errors, len(run.items)), ("done", 0, 64))
        self.assertFalse(barrier.broken)

    def test_start_over_stops_the_run_and_drops_answers(self):  # AC-6
        gate, arrived = threading.Event(), threading.Semaphore(0)
        conn = labelled(before=lambda b: (arrived.release(), gate.wait(5)))
        r = Rig(self, conn, concurrency=4)
        r.runs.start(r.s.session_id, 100)
        run = r.runs.get(r.s.session_id)
        for _ in range(4):
            self.assertTrue(arrived.acquire(timeout=5))
        r.store.end(r.s.session_id)                     # เริ่มใหม่ while four calls are in flight
        gate.set()
        self.assertTrue(run.wait(10))
        self.assertEqual(run.state, "cancelled")
        self.assertEqual(len(conn.log["sent"]), 4)      # no further call after the first answer came back
        self.assertEqual(run.items, [])
        self.assertFalse((r.var / "sessions" / f"{r.s.session_id}.json").exists())

    def test_a_streak_of_failures_ends_the_run(self):  # AC-2
        conn = labelled(fail={c["text"] for c in CASES})
        r = Rig(self, conn, concurrency=4)
        _, run = r.run(1000)
        self.assertEqual(run.state, "failed")
        self.assertLess(len(run.items), 100)
        self.assertEqual(len(conn.log["sent"]), len(run.items))              # no retries
        self.assertEqual(run.errors, len(run.items))

    def test_bad_starts(self):
        r = Rig(self, labelled())
        for bad in (0, 1001, "100", True, 1.5, None):
            with self.assertRaises(speed.RunError) as e:
                r.runs.start(r.s.session_id, bad)
            self.assertEqual(e.exception.status, 400)
        with self.assertRaises(speed.RunError) as e:
            r.runs.start("nope", 10)
        self.assertEqual(e.exception.status, 404)
        gate = threading.Event()
        r2 = Rig(self, labelled(before=lambda b: gate.wait(5)), concurrency=2)
        r2.runs.start(r2.s.session_id, 4)
        with self.assertRaises(speed.RunError) as e:
            r2.runs.start(r2.s.session_id, 4)
        self.assertEqual(e.exception.status, 409)
        gate.set()
        self.assertTrue(r2.runs.get(r2.s.session_id).wait(5))


if __name__ == "__main__":
    unittest.main()
