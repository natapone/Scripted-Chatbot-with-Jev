"""Story 2.1 — the catalogue's test set and its scoring, in `app/testset.py` (lifted from the
rehearsal script, which now imports them). Hermetic: no network."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from app import flow, testset, turn

_spec = importlib.util.spec_from_file_location(
    "replay_s3", Path(__file__).resolve().parent / "rehearsal" / "replay_s3.py")
replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(replay)

FLOW = flow.load()
CAT = testset.read_catalogue()


class TestSetTests(unittest.TestCase):

    def test_one_copy_shared_with_the_rehearsal(self):
        for name in ("load_cases", "build_session", "scored_entities", "loop_intent", "score", "read_catalogue"):
            self.assertIs(getattr(replay, name), getattr(testset, name), name)
        cases = testset.load_cases(CAT)
        self.assertEqual(len(cases), 129)
        self.assertEqual([c["n"] for c in cases], list(range(1, 130)))
        self.assertTrue(any(c["intent"] == "give_delivery_details" for c in cases))
        self.assertTrue(any(c["intent"] == "none" for c in cases))

    def test_score_counts_the_loops_intent_against_the_label(self):
        cases = testset.load_cases(CAT)
        case = next(c for c in cases if c["intent"] == "greet")
        s = testset.build_session(case, FLOW)
        req = turn.build_request(s, case["text"], FLOW)
        v = turn.Verdict("matched", req, None, intent="greet")
        self.assertTrue(testset.score(CAT, case, v)["loop_ok"])
        v = turn.Verdict("model_failed", req, None)
        r = testset.score(CAT, case, v)
        self.assertEqual((r["loop"], r["loop_ok"], r["cost_usd"]), (None, False, 0.0))


if __name__ == "__main__":
    unittest.main()
