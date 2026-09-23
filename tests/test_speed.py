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
        at = lambda n: CASES[speed.case_index(n - 1, len(CASES))]      # the case row n sends
        fallback, refused, slow, broken = at(1)["text"], at(2)["text"], at(3)["text"], at(4)["text"]
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
        # errors: the refused, the timed-out and the 500 — rows 2-4, sent again at rows 131-133 (the set is cycled)
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
        self.assertEqual(item["you"]["text"], at(5)["text"])
        self.assertTrue(item["bot"] and all(b["buttons"] == [] for b in item["bot"]))
        self.assertEqual(next(i for i in run.items if i["entry"]["batch_n"] == 2)["bot"][0]["response_id"], "system.unreachable")
        # nothing else of the session was written by the run
        self.assertEqual((s.contexts, s.order, len(s.transcript)), ({}, session.empty_order(), 1))
        # NFR10: delivery details masked in the entry, the bubble and the retained request; never in the file
        masked = [e for e in batch if at(e["batch_n"])["intent"] == "give_delivery_details"]
        self.assertEqual(len(masked), 3)
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

    def test_the_set_is_cycled_so_a_hundred_meets_the_whole_catalogue(self):  # AC-1, AC-3
        order = [speed.case_index(i, len(CASES)) for i in range(len(CASES))]
        self.assertEqual(sorted(order), list(range(len(CASES))))                 # every case once per cycle
        first = [CASES[j] for j in order[:100]]
        self.assertEqual(sum(c["intent"] == "give_delivery_details" for c in first), 3)
        self.assertGreaterEqual(sum(c["intent"] == "none" for c in first), 3)
        self.assertEqual(len({c["intent"] for c in first}), len({c["intent"] for c in CASES}))
        self.assertEqual([speed.case_index(i, 10) for i in range(10)], list(range(10)))   # no coprime stride → in order

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


    def test_a_by_state_row_is_labelled_by_what_was_judged(self):  # Story 2.3 AC-1
        case = next(c for c in CASES if c["text"] == "เก็บปลายทางครับ")        # n 46, under ask_payment
        r = Rig(self, labelled(), cases=[case])
        started, run = r.run(1)
        e = r.store.get(r.s.session_id).log[-1]
        self.assertEqual((e["outcome"], e["jev"]["by_state"], e["jev"]["awaiting"], e["judged"]),
                         ("matched", True, "payment", "inform"))
        self.assertNotEqual(e["response_id"], "inform")               # the next prompt, which the row used to name
        self.assertEqual(e["contexts_before"], ["ask_payment"])        # what is measured is unchanged


class CapAndRecapTests(unittest.TestCase):

    def test_refused_before_its_first_call(self):  # AC-4
        conn = labelled()
        r = Rig(self, conn, cap=0.001)
        started = r.runs.start(r.s.session_id, 100)
        self.assertEqual((started["refused"], started["outcome"], started["model_status"]), (True, "cap_reached", "cap"))
        self.assertAlmostEqual(started["estimate_usd"], 100 * speed.EST_TURN_USD)
        self.assertEqual((conn.log["opened"], len(conn.log["sent"]), r.client.calls), (0, 0, 0))
        self.assertEqual((r.store.get(r.s.session_id).log, r.runs.get(r.s.session_id)), ([], None))
        with self.assertRaises(speed.RunError) as e:
            r.runs.progress(r.s.session_id)
        self.assertEqual(e.exception.status, 404)
        # within the room it starts: 1,000 at the estimate fits the default $0.50 cap
        ok = Rig(self, labelled(), cap=0.50)
        self.assertFalse(ok.run(1000)[0]["refused"])

    def test_the_cap_reached_mid_run_stops_sending(self):  # AC-4
        conn = labelled(cost=0.001)
        r = Rig(self, conn, cap=0.005, concurrency=1)
        started, run = r.run(20)                          # estimate $0.004: allowed; each answer costs $0.001
        self.assertFalse(started["refused"])
        self.assertEqual((run.state, len(conn.log["sent"]), len(run.items)), ("capped", 5, 6))
        last = run.items[-1]["entry"]
        self.assertEqual((last["outcome"], last["jev"]["error"], last["turn_no"]), ("cap_reached", "cap", 6))
        p = r.runs.progress(r.s.session_id)
        self.assertEqual((p["state"], p["model_status"], p["recap"]["errors"], p["recap"]["calls"]), ("capped", "cap", 1, 6))

    def test_recap_from_the_log_agrees_with_the_key_info_block(self):  # AC-5
        conn = labelled(fail={CASES[speed.case_index(1, len(CASES))]["text"]}, cost=0.000163)
        r = Rig(self, conn)
        started, run = r.run(140)
        p = r.runs.progress(r.s.session_id, since=130)
        self.assertEqual((p["state"], p["answered"], p["next"], len(p["items"]), p["since"]), ("done", 140, 140, 10, 130))
        rc = p["recap"]
        log = r.store.get(r.s.session_id).log
        # the key-info block's rule (shared.js § updateKeyInfo), over the whole log
        answered = [e for e in log if e.get("jev") and e["outcome"] not in ("model_failed", "cap_reached")]
        self.assertEqual(rc["avg_ms"], sum(e["jev"]["ms"] for e in answered) / len(answered))
        self.assertAlmostEqual(rc["total_usd"], sum(e["jev"]["cost_usd"] for e in answered), places=12)
        self.assertEqual((rc["calls"], rc["target"], rc["concurrency"], rc["answered"], rc["errors"]), (140, 140, 32, 138, 2))
        self.assertAlmostEqual(rc["total_usd"], 138 * 0.000163, places=12)
        self.assertAlmostEqual(rc["total_thb"], rc["total_usd"] * 34.9, places=12)
        self.assertAlmostEqual(rc["cost_per_call_usd"], rc["total_usd"] / 140, places=12)
        self.assertAlmostEqual(rc["cost_per_call_thb"], rc["total_thb"] / 140, places=12)
        self.assertEqual(rc["correct"], sum(e["correct"] for e in log))
        self.assertEqual(rc["correct_share"], rc["correct"] / 140)
        self.assertGreater(rc["correct"], 120)
        self.assertEqual(rc["calls_per_s"], 140 / (rc["elapsed_ms"] / 1000))
        self.assertGreaterEqual(rc["elapsed_ms"], 0)
        self.assertIsInstance(rc["wall_ms"], int)
        self.assertEqual((rc["thb_per_usd"], rc["rate_date"], rc["model"]), (34.9, "2026-09-22", "typesafe/jev-1.13"))
        # the recap from the entries alone (a static function the driver's figures can be re-derived with)
        self.assertEqual(speed.recap([], thb_per_usd=34.9, rate_date="d", target=0, concurrency=1, wall_ms=0, model="m")["calls"], 0)


class RouteTests(unittest.TestCase):
    """`POST /api/run` and `GET /api/run` over loopback; Jev is the labelled fake."""

    def serve(self, conn, cap="0.50"):
        from app import config, server
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = config.load(env_path=Path("/nonexistent/.env"),
                          environ={"OPENROUTER_API_KEY": FAKE_KEY, "THB_PER_USD": "34.9", "RATE_DATE": "2026-09-22",
                                   "VAR_DIR": tmp.name, "SPEND_CAP_USD": cap})
        client = jev.Client(FAKE_KEY, timeout=10, connection=conn)
        store = session.Store(session.flow_version_of(flow.CATALOGUE), cfg.var_dir)
        httpd = server.make_server(cfg, port=0, flow=FLOW, store=store, client=client)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        port = httpd.server_address[1]
        bodies = []

        def call(method, path, body=None):
            import http.client
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json"} if body is not None else {})
            r = c.getresponse()
            text = r.read().decode("utf-8")
            c.close()
            bodies.append(text)
            return r.status, json.loads(text)
        return call, httpd, bodies

    def test_start_poll_and_recap(self):  # AC-1, AC-5
        call, httpd, bodies = self.serve(labelled())
        _, sess = call("GET", "/api/session")
        sid = sess["session_id"]
        status, started = call("POST", "/api/run", {"session_id": sid, "target": 10})
        self.assertEqual((status, started["refused"], started["target"], started["concurrency"], started["state"]),
                         (200, False, 10, 10, "running"))
        self.assertTrue(httpd.runs.get(sid).wait(10))
        status, p = call("GET", f"/api/run?session_id={sid}&since=0")
        self.assertEqual((status, p["state"], p["answered"], len(p["items"]), p["run_id"]), (200, "done", 10, 10, started["run_id"]))
        self.assertEqual(p["recap"]["calls"], 10)
        for key in ("elapsed_ms", "calls_per_s", "avg_ms", "correct", "correct_share", "errors", "total_usd",
                    "total_thb", "cost_per_call_usd", "cost_per_call_thb"):
            self.assertIn(key, p["recap"])
        _, again = call("GET", f"/api/session?id={sid}")                # the log the page restores from
        self.assertEqual(len([e for e in again["log"] if e.get("batch") == started["run_id"]]), 10)
        self.assertEqual(call("GET", f"/api/run?session_id={sid}&since=10")[1]["items"], [])
        for b in bodies:
            self.assertNotIn(FAKE_KEY, b)

    def test_refusal_and_bad_requests(self):  # AC-4
        conn = labelled()
        call, httpd, _ = self.serve(conn, cap="0.001")
        sid = call("GET", "/api/session")[1]["session_id"]
        status, r = call("POST", "/api/run", {"session_id": sid, "target": 100})
        self.assertEqual((status, r["refused"], r["model_status"]), (200, True, "cap"))
        self.assertEqual((len(conn.log["sent"]), httpd.client.calls), (0, 0))
        self.assertEqual(call("GET", f"/api/run?session_id={sid}")[0], 404)
        self.assertEqual(call("GET", f"/api/session?id={sid}")[1]["log"], [])
        self.assertEqual(call("POST", "/api/run", {"session_id": sid, "target": "100"})[0], 400)
        self.assertEqual(call("POST", "/api/run", {"target": 100})[0], 400)
        self.assertEqual(call("POST", "/api/run", {"session_id": "nope", "target": 1})[0], 404)
        self.assertEqual(call("GET", "/api/run")[0], 400)
        self.assertEqual(call("GET", f"/api/run?session_id={sid}&since=x")[0], 400)


if __name__ == "__main__":
    unittest.main()
