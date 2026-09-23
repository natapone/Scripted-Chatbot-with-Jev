"""Story 2.5 — the demo driver's pure helpers (`tests/demo/storyboard.mjs`), run by Node's own test
runner from inside this suite. Hermetic: an inline storyboard fixture, no browser, no server, no
network. Skipped where `node` is not installed — the driver needs Node 22.18+ for type stripping."""
from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not installed")
class DemoHelperTests(unittest.TestCase):
    def test_node_helper_tests_pass(self):
        r = subprocess.run([NODE, "--test", str(HERE / "demo" / "storyboard.test.mjs")],
                           capture_output=True, text=True, timeout=60, cwd=HERE.parent)
        out = r.stdout + r.stderr
        passed = int((re.search(r"^ℹ pass (\d+)", out, re.M) or [0, 0])[1])
        failed = int((re.search(r"^ℹ fail (\d+)", out, re.M) or [0, -1])[1])
        self.assertEqual(r.returncode, 0, out[-2000:])
        self.assertEqual(failed, 0, out[-2000:])
        self.assertGreaterEqual(passed, 11, out[-2000:])   # the count the Story closed with


if __name__ == "__main__":
    unittest.main()
